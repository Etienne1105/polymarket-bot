"""
MAPEM Integration pour RupeeHunter v3
======================================
- Catégorisation par mots-clés (gratuit)
- Scoring heuristique (gratuit)
- Analyse Claude via Navi (gratuit via Max)
- Score composite v3 : 35% scanner + 65% MAPEM
- Support expertise humaine (notes, boost, flag)
- Logging des trades dans MAPEM DB
- Dashboard de performance
"""

import sys
import os
import sqlite3
import logging
from datetime import datetime

from keychain import get_secret
from models import Opportunity

from config import (
    MAPEM_DB_PATH, MAPEM_SCHEMA_PATH, MAPEM_SYSTEM_PATH,
    MAPEM_WEIGHT, SCANNER_WEIGHT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import conditionnel du système MAPEM
# ---------------------------------------------------------------------------
_mapem_available = False
try:
    sys.path.insert(0, MAPEM_SYSTEM_PATH)
    from mapem_agent import (
        MAPEMAgent, MAPEMEvent, MAPEMAnalysis,
        BayesianScenario, TradingSignal,
    )
    from mapem_auto_analyzer import MAPEMAutoAnalyzer
    _mapem_available = True
except (ImportError, TypeError) as e:
    logger.warning(f"MAPEM non disponible: {e}")


# ---------------------------------------------------------------------------
# 2A. Catégoriseur par mots-clés
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS = {
    "SPORT_MAJEUR": [
        "win", "game", "match", "championship", "playoff", "finals", "mvp",
        "nba", "nfl", "mlb", "nhl", "ufc", "fight", "boxing", "soccer",
        "football", "basketball", "baseball", "hockey", "tennis", "golf",
        "super bowl", "world series", "world cup", "olympics", "lakers",
        "celtics", "warriors", "yankees", "dodgers", "premier league",
        "champions league", "grand slam", "f1", "formula", "race",
        "team", "player", "coach", "season", "tournament", "score",
    ],
    "MONETAIRE": [
        "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
        "fomc", "powell", "inflation", "cpi", "ppi", "monetary",
        "central bank", "ecb", "boj", "bank of england", "basis points",
        "quantitative", "tightening", "easing", "yield", "treasury",
    ],
    "POLITIQUE_NAT": [
        "trump", "biden", "president", "election", "senate", "congress",
        "governor", "mayor", "republican", "democrat", "gop", "vote",
        "poll", "approval", "impeach", "pardon", "executive order",
        "supreme court", "legislation", "bill", "law", "cabinet",
        "primary", "nominee", "candidate", "midterm",
    ],
    "GEOPOLITIQUE": [
        "war", "invasion", "military", "nato", "sanctions", "conflict",
        "missile", "nuclear", "ceasefire", "peace", "territory",
        "ukraine", "russia", "taiwan", "china threat", "iran",
        "north korea", "coup", "regime",
    ],
    "TRADE_TARIFS": [
        "tariff", "trade war", "import", "export", "duty", "customs",
        "trade deal", "trade agreement", "wto", "embargo",
    ],
    "TECHNOLOGIE": [
        "ai ", "artificial intelligence", "openai", "google", "apple",
        "microsoft", "meta", "tesla", "spacex", "crypto", "bitcoin",
        "ethereum", "blockchain", "semiconductor", "chip", "nvidia",
        "launch", "ipo", "tech",
    ],
    "ECONOMIE_MACRO": [
        "gdp", "recession", "unemployment", "jobs report", "payroll",
        "economic", "growth", "stimulus", "debt ceiling", "default",
        "housing", "consumer", "retail", "manufacturing",
    ],
    "SANTE_PANDEMIE": [
        "covid", "pandemic", "vaccine", "virus", "outbreak", "who",
        "health", "fda", "drug", "clinical trial", "epidemic",
    ],
    "ENVIRONNEMENT": [
        "climate", "hurricane", "earthquake", "wildfire", "flood",
        "storm", "temperature", "carbon", "emissions", "renewable",
    ],
    "ENERGIE": [
        "oil", "opec", "crude", "natural gas", "energy", "pipeline",
        "drilling", "barrel", "petroleum", "solar", "wind power",
    ],
    "CYGNE_NOIR": [
        "asteroid", "alien", "extinction", "collapse", "apocal",
        "catastroph", "unprecedented", "never before",
    ],
}


def categorize_market(question: str) -> str:
    """Mappe une question Polymarket vers un code catégorie MAPEM."""
    q = question.lower()
    best_cat = "SOCIETE_CULTURE"
    best_count = 0

    for category, keywords in _CATEGORY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in q)
        if count > best_count:
            best_count = count
            best_cat = category

    return best_cat


# Abréviations pour l'affichage (max 4 chars)
_CATEGORY_SHORT = {
    "SPORT_MAJEUR": "SPRT",
    "MONETAIRE": "MONE",
    "POLITIQUE_NAT": "POLN",
    "POLITIQUE_INT": "POLI",
    "GEOPOLITIQUE": "GEOP",
    "TRADE_TARIFS": "TRAD",
    "TECHNOLOGIE": "TECH",
    "ECONOMIE_MACRO": "ECON",
    "SANTE_PANDEMIE": "SANT",
    "ENVIRONNEMENT": "ENVI",
    "ENERGIE": "ENER",
    "CYGNE_NOIR": "CYGN",
    "SOCIETE_CULTURE": "SOCI",
    "FINANCE_MARCHE": "FINA",
    "SCIENCE": "SCIE",
}


def category_short(code: str) -> str:
    """Retourne l'abréviation 4 chars d'une catégorie."""
    return _CATEGORY_SHORT.get(code, code[:4].upper())


# ---------------------------------------------------------------------------
# 2B. Scorer heuristique — PRÉVISIBILITÉ CATÉGORIELLE
# ---------------------------------------------------------------------------

_CATEGORY_PREDICTABILITY = {
    "SPORT_MAJEUR":    0.80,
    "MONETAIRE":       0.75,
    "ECONOMIE_MACRO":  0.60,
    "TECHNOLOGIE":     0.55,
    "ENERGIE":         0.50,
    "TRADE_TARIFS":    0.40,
    "POLITIQUE_NAT":   0.35,
    "POLITIQUE_INT":   0.30,
    "SANTE_PANDEMIE":  0.30,
    "ENVIRONNEMENT":   0.25,
    "GEOPOLITIQUE":    0.20,
    "CYGNE_NOIR":      0.05,
    "SOCIETE_CULTURE": 0.40,
    "FINANCE_MARCHE":  0.55,
    "SCIENCE":         0.45,
}


def heuristic_mapem_score(opp, category: str) -> int:
    """Score MAPEM 0-100 basé sur la PRÉVISIBILITÉ catégorielle."""
    base = _CATEGORY_PREDICTABILITY.get(category, 0.40)
    score = base * 100

    # Cohérence catégorie × horizon
    if 0 < opp.hours_left < float("inf"):
        if category == "SPORT_MAJEUR" and opp.hours_left > 168:
            score -= 15
        elif category == "MONETAIRE" and opp.hours_left > 720:
            score -= 10
        elif category in ("POLITIQUE_NAT", "GEOPOLITIQUE") and opp.hours_left < 6:
            score -= 10
        elif category == "SPORT_MAJEUR" and opp.hours_left < 3:
            score -= 5

    # Piège du profit trop beau
    if opp.profit_potential > 0.20 and base > 0.60:
        score -= 15
    elif opp.profit_potential > 0.40:
        score -= 10

    # Zone d'incertitude maximale
    price = opp.current_price
    if 0.40 <= price <= 0.60:
        if category in ("GEOPOLITIQUE", "POLITIQUE_NAT", "POLITIQUE_INT"):
            score -= 20
        elif category in ("TRADE_TARIFS", "CYGNE_NOIR"):
            score -= 15
        else:
            score -= 5

    # Convergence prix extrême × catégorie prévisible
    if price >= 0.90 and category in ("SPORT_MAJEUR", "MONETAIRE"):
        score += 10
    elif price <= 0.10 and category in ("CYGNE_NOIR", "GEOPOLITIQUE"):
        score += 5

    # Calibration historique
    score = _apply_calibration_adjustment(score, category)

    return max(0, min(100, int(score)))


def _apply_calibration_adjustment(score: float, category: str) -> float:
    """Ajuste le score selon la performance historique dans cette catégorie."""
    # D'abord vérifier le learner (v3)
    try:
        from learner import get_learner
        learner = get_learner()
        adj = learner.get_category_adjustment(category)
        if adj != 0:
            return score + adj
    except (ImportError, Exception):
        pass

    # Fallback : MAPEM DB
    if not os.path.exists(MAPEM_DB_PATH):
        return score

    try:
        db = sqlite3.connect(MAPEM_DB_PATH)
        row = db.execute("""
            SELECT COUNT(*) as n,
                   AVG(fo.brier_score) as avg_brier
            FROM forecast_outcomes fo
            JOIN bayesian_forecasts bf ON fo.forecast_id = bf.forecast_id
            JOIN major_events me ON bf.event_id = me.event_id
            JOIN event_categories ec ON me.category_id = ec.category_id
            WHERE ec.code = ?
        """, (category,)).fetchone()
        db.close()

        if row and row[0] >= 5:
            n_trades, avg_brier = row
            if avg_brier is not None:
                if avg_brier < 0.15:
                    score += 10
                elif avg_brier > 0.30:
                    score -= 15
                elif avg_brier > 0.25:
                    score -= 5
    except Exception:
        pass

    return score


# ---------------------------------------------------------------------------
# 2C. Score composite v3 — 35% scanner + 65% MAPEM + humain
# ---------------------------------------------------------------------------

def compute_composite_v3(scanner_score: int, mapem_score: int,
                         human_score: int = 0) -> int:
    """Score composite v3 : 35% scanner + 65% MAPEM, ajusté par l'humain.

    MAPEM (65%) se décompose en :
    - 30% heuristique (le mapem_score passé ici)
    - 50% Claude qualitatif (intégré via navi_prob quand disponible)
    - 20% expertise humaine (human_score, -100 à +100)

    Quand Navi n'est pas dispo, on utilise le score heuristique seul pour MAPEM.
    """
    base = SCANNER_WEIGHT * scanner_score + MAPEM_WEIGHT * mapem_score
    # Appliquer l'overlay humain (clampé entre -20 et +20 d'impact)
    human_adj = max(-20, min(20, human_score))
    return max(0, min(100, int(base + human_adj)))


# Backward compat
def compute_composite(scanner_score: int, mapem_score: int) -> int:
    """Backward compatible — appelle compute_composite_v3 sans humain."""
    return compute_composite_v3(scanner_score, mapem_score, 0)


# ---------------------------------------------------------------------------
# 2D. Screening via Navi (gratuit via Claude Max)
# ---------------------------------------------------------------------------

def screening_top(opportunities: list, console, count: int = 5) -> list:
    """Screening des top N opportunités via Navi (gratuit).
    Retourne la liste des verdicts [{num, verdict, raison, prob_estimee}].
    """
    from navi import get_navi
    navi = get_navi()

    if not navi.available:
        console.print("[yellow]Navi indisponible — utilise 'claude --version' pour vérifier.[/yellow]")
        return []

    top = opportunities[:count]
    if not top:
        console.print("[yellow]Aucune opportunité à analyser.[/yellow]")
        return []

    quota = navi.quota_status()
    console.print(f"[dim]Navi analyse {len(top)} marchés (gratuit via Max) "
                  f"[{quota['remaining']}/{quota['limit']} appels restants]...[/dim]")

    results = navi.analyze_batch(top)

    from rich.table import Table

    table = Table(title=f"🧚 Navi — Screening Top {len(top)}", border_style="magenta")
    table.add_column("#", width=3)
    table.add_column("Verdict", width=10)
    table.add_column("Prob.", justify="right", width=6)
    table.add_column("vs Prix", justify="right", width=7)
    table.add_column("Raison", max_width=50)

    verdicts = []
    for i, (opp, result) in enumerate(zip(top, results), 1):
        if result is None:
            table.add_row(str(i), "[dim]—[/dim]", "—", "—", "Navi n'a pas pu analyser")
            continue

        verdict = result.get("verdict", "?")
        raison = result.get("raison", "").replace("[", "\\[")
        prob = result.get("prob_estimee", 0)

        if verdict == "GO":
            v_str = "[bold green]GO[/bold green]"
        elif verdict == "PIEGE":
            v_str = "[bold red]PIEGE[/bold red]"
        else:
            v_str = "[bold yellow]INCERTAIN[/bold yellow]"

        div = prob - opp.current_price
        if div > 0.05:
            div_str = f"[green]+{div:.0%}[/green]"
        elif div < -0.05:
            div_str = f"[red]{div:.0%}[/red]"
        else:
            div_str = f"[yellow]{div:+.0%}[/yellow]"

        table.add_row(str(i), v_str, f"{prob:.0%}", div_str, raison)

        # Mettre à jour l'opportunité avec les résultats Navi
        opp.navi_verdict = verdict
        opp.navi_analysis = result.get("raison", "")
        opp.navi_prob = prob

        verdicts.append({"num": i, **result})

    console.print(table)

    n_go = sum(1 for v in verdicts if v.get("verdict") == "GO")
    n_piege = sum(1 for v in verdicts if v.get("verdict") == "PIEGE")
    if n_piege > 0:
        console.print(f"\n[bold yellow]⚠️ {n_piege} piège(s) détecté(s)[/bold yellow]")
    if n_go > 0:
        console.print(f"[bold green]✅ {n_go} opportunité(s) validée(s)[/bold green]")

    return verdicts


def screening_single(opp, console) -> dict:
    """Analyse Navi d'une seule opportunité. Retourne le verdict ou {}."""
    from navi import get_navi
    navi = get_navi()

    if not navi.available:
        console.print("[yellow]Navi indisponible.[/yellow]")
        return {}

    cat = getattr(opp, "mapem_category", "?") or "?"
    quota = navi.quota_status()
    console.print(f"[dim]Navi analyse ce marché (gratuit via Max) "
                  f"[{quota['remaining']}/{quota['limit']}]...[/dim]")

    result = navi.analyze_single(
        question=opp.market_question,
        price=opp.current_price,
        category=cat,
        strategy=opp.strategy,
        outcome=opp.outcome,
        hours_left=opp.hours_left,
        volume=opp.volume_24h,
        description=opp.market_description,
    )

    if not result:
        console.print("[yellow]Navi n'a pas pu analyser ce marché.[/yellow]")
        return {}

    from rich.panel import Panel

    verdict = result.get("verdict", "?")
    raison = result.get("raison", "").replace("[", "\\[")
    prob = result.get("prob_estimee", 0)

    if verdict == "GO":
        v_color = "green"
    elif verdict == "PIEGE":
        v_color = "red"
    else:
        v_color = "yellow"

    div = prob - opp.current_price
    if div > 0.05:
        div_str = f"[green]+{div:.0%}[/green] vs prix marché"
    elif div < -0.05:
        div_str = f"[red]{div:.0%}[/red] vs prix marché"
    else:
        div_str = f"[yellow]{div:+.0%}[/yellow] vs prix marché"

    safe_question = opp.market_question.replace("[", "\\[")
    console.print(Panel(
        f"[bold {v_color}]{verdict}[/bold {v_color}]  —  {safe_question}\n\n"
        f"{raison}\n\n"
        f"Probabilité estimée: [bold]{prob:.0%}[/bold]  ({div_str})",
        title="🧚 Avis Navi",
        border_style=v_color,
    ))

    # Mettre à jour l'opportunité
    opp.navi_verdict = verdict
    opp.navi_analysis = result.get("raison", "")
    opp.navi_prob = prob

    return result


# Backward compat aliases
def screening_top3(opportunities: list, console) -> list:
    """Alias v2 → v3 : screening top 5 via Navi."""
    return screening_top(opportunities, console, count=5)


# ---------------------------------------------------------------------------
# 2E. Logger de trades
# ---------------------------------------------------------------------------

def log_trade_to_mapem(opp, amount: float, response: dict):
    """Enregistre un trade dans la DB MAPEM pour le tracking."""
    if not _mapem_available:
        return

    try:
        agent = get_mapem_agent()

        event = MAPEMEvent(
            title=f"Polymarket: {opp.market_question[:100]}",
            summary=f"Trade {opp.outcome} @ ${opp.current_price:.3f} pour ${amount:.2f}",
            category=getattr(opp, "mapem_category", "SOCIETE_CULTURE") or "SOCIETE_CULTURE",
            severity=3,
            regions=["US"],
            horizon="days" if 0 < opp.hours_left < 72 else "weeks",
        )

        analysis = MAPEMAnalysis(
            level_1_facts=f"Achat {opp.outcome} sur '{opp.market_question}' "
                          f"à ${opp.current_price:.3f}. Stratégie: {opp.strategy}. "
                          f"Volume 24h: ${opp.volume_24h:,.0f}.",
            level_2_strategy=f"Score scanner: {opp.confidence_score}/100. "
                             f"Estimation valeur: ${opp.estimated_value:.3f}. "
                             f"Profit potentiel: {opp.profit_potential:.1%}.",
            level_3_philosophy="Trade court terme sur marché de prédiction.",
            level_4_systemic=f"Catégorie MAPEM: {getattr(opp, 'mapem_category', 'N/A')}. "
                             f"Score MAPEM heuristique: {getattr(opp, 'mapem_score', -1)}.",
            confidence_level=opp.confidence_score / 100.0,
        )

        scenario = BayesianScenario(
            label=f"{opp.outcome} résout positif",
            description=f"Le marché '{opp.market_question}' se résout en faveur de {opp.outcome}.",
            prior_prob=opp.current_price,
            evidence=[{
                "evidence": f"Estimation scanner: {opp.estimated_value:.3f}",
                "likelihood_ratio": opp.estimated_value / max(opp.current_price, 0.01),
            }],
            horizon_months=1,
            market_impact_direction="bullish",
            market_impact_magnitude=amount,
            affected_sectors=[],
            affected_tickers=[{
                "ticker": "POLYMARKET",
                "impact": opp.profit_potential,
                "direction": "bullish",
                "rationale": opp.details,
            }],
        )

        signal = TradingSignal(
            ticker="POLYMARKET",
            direction="BUY",
            conviction=opp.confidence_score / 100.0,
            rationale=f"Scanner: {opp.strategy} | Score: {opp.confidence_score} | {opp.details}",
            urgency="immediate",
            suggested_weight=amount / 42.0,
            stop_loss_pct=0.15,
            take_profit_pct=opp.profit_potential,
            mapem_score=getattr(opp, "mapem_score", 50),
        )

        try:
            conn = agent._connect()
            conn.execute(
                "INSERT OR IGNORE INTO asset_universe (ticker, name, sector, country) "
                "VALUES ('POLYMARKET', 'Polymarket Predictions', 'Prediction Markets', 'US')"
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        agent.full_pipeline(
            event=event,
            analysis=analysis,
            scenarios=[scenario],
            signals=[signal],
            auto_approve=True,
        )

        logger.info(f"Trade logged to MAPEM: {opp.market_question[:40]} ${amount:.2f}")

    except Exception as e:
        logger.warning(f"MAPEM logging failed: {e}")


# ---------------------------------------------------------------------------
# 2F. Dashboard de performance
# ---------------------------------------------------------------------------

def show_performance_dashboard(console):
    """Affiche un dashboard de performance avec les données MAPEM + Learner."""
    from rich.table import Table
    from rich.panel import Panel

    # D'abord essayer le Learner v3
    try:
        from learner import get_learner
        learner = get_learner()
        stats = learner.get_overall_stats()
        if stats and stats.get("total_trades", 0) > 0:
            _show_learner_dashboard(console, learner, stats)
            return
    except (ImportError, Exception):
        pass

    # Fallback : dashboard MAPEM
    if not os.path.exists(MAPEM_DB_PATH):
        console.print("[yellow]Pas encore de données. Effectue des trades d'abord.[/yellow]")
        return

    try:
        db = sqlite3.connect(MAPEM_DB_PATH)

        rows = db.execute("""
            SELECT ec.code, COUNT(*) as n_trades,
                   ROUND(AVG(ts.conviction), 2) as avg_conviction,
                   ROUND(AVG(ts.mapem_score), 1) as avg_mapem
            FROM trading_signals ts
            JOIN major_events me ON ts.event_id = me.event_id
            JOIN event_categories ec ON me.category_id = ec.category_id
            WHERE ts.ticker = 'POLYMARKET'
            GROUP BY ec.code
            ORDER BY n_trades DESC
        """).fetchall()

        if rows:
            table = Table(title="Trades Polymarket par Catégorie MAPEM")
            table.add_column("Catégorie", width=18)
            table.add_column("Trades", justify="right", width=7)
            table.add_column("Conviction moy.", justify="right", width=14)
            table.add_column("Score MAPEM moy.", justify="right", width=15)

            total_trades = 0
            for code, n, conv, mapem in rows:
                table.add_row(code, str(n), f"{conv:.2f}", f"{mapem:.1f}")
                total_trades += n

            console.print(table)
            console.print(f"\n[bold]Total trades loggés: {total_trades}[/bold]")
        else:
            console.print("[yellow]Aucun trade Polymarket trouvé dans la DB MAPEM.[/yellow]")

        db.close()

    except Exception as e:
        console.print(f"[red]Erreur dashboard: {e}[/red]")


def _show_learner_dashboard(console, learner, stats):
    """Affiche le dashboard basé sur le Learner v3."""
    from rich.table import Table
    from rich.panel import Panel

    # Stats globales
    total = stats["total_trades"]
    resolved = stats["resolved_trades"]
    win_rate = stats.get("win_rate", 0)
    total_pnl = stats.get("total_pnl", 0)

    pnl_color = "green" if total_pnl >= 0 else "red"
    console.print(Panel(
        f"[bold]Trades: {total}[/bold] | Résolus: {resolved} | "
        f"Win rate: [bold]{win_rate:.0%}[/bold] | "
        f"PnL: [{pnl_color}]${total_pnl:+.2f}[/{pnl_color}]",
        title="📊 Sheikah Slate",
        border_style="cyan",
    ))

    # Par catégorie
    cat_stats = learner.accuracy_by_category()
    if cat_stats:
        table = Table(title="Performance par catégorie")
        table.add_column("Cat.", width=6)
        table.add_column("Trades", justify="right", width=7)
        table.add_column("Win %", justify="right", width=7)
        table.add_column("PnL", justify="right", width=8)
        table.add_column("Adj.", justify="right", width=5)

        for cat, data in cat_stats.items():
            wr = data.get("win_rate", 0)
            pnl = data.get("total_pnl", 0)
            adj = learner.get_category_adjustment(cat)
            wr_color = "green" if wr >= 0.5 else "red"
            pnl_color = "green" if pnl >= 0 else "red"
            table.add_row(
                category_short(cat),
                str(data.get("count", 0)),
                f"[{wr_color}]{wr:.0%}[/{wr_color}]",
                f"[{pnl_color}]${pnl:+.2f}[/{pnl_color}]",
                f"{adj:+d}" if adj != 0 else "—",
            )
        console.print(table)

    # Par stratégie
    strat_stats = learner.accuracy_by_strategy()
    if strat_stats:
        table = Table(title="Performance par stratégie")
        table.add_column("Stratégie", width=16)
        table.add_column("Trades", justify="right", width=7)
        table.add_column("Win %", justify="right", width=7)
        table.add_column("PnL", justify="right", width=8)

        for strat, data in strat_stats.items():
            wr = data.get("win_rate", 0)
            pnl = data.get("total_pnl", 0)
            wr_color = "green" if wr >= 0.5 else "red"
            pnl_color = "green" if pnl >= 0 else "red"
            table.add_row(
                strat,
                str(data.get("count", 0)),
                f"[{wr_color}]{wr:.0%}[/{wr_color}]",
                f"[{pnl_color}]${pnl:+.2f}[/{pnl_color}]",
            )
        console.print(table)


# ---------------------------------------------------------------------------
# 2G. Helper — Singleton MAPEMAgent
# ---------------------------------------------------------------------------

_agent_instance = None


def get_mapem_agent() -> "MAPEMAgent":
    """Retourne un singleton MAPEMAgent avec la DB Polymarket."""
    global _agent_instance
    if _agent_instance is None:
        if not _mapem_available:
            raise RuntimeError("MAPEM non disponible")
        _agent_instance = MAPEMAgent(db_path=MAPEM_DB_PATH)
    return _agent_instance
