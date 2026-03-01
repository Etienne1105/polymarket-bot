"""
MAPEM Integration pour Polymarket Bot
======================================
Module pont entre le scanner Polymarket et le système MAPEM.
- Catégorisation par mots-clés (gratuit)
- Scoring heuristique (gratuit)
- Analyse Claude API (à la demande)
- Logging des trades dans MAPEM DB
- Dashboard de performance
"""

import sys
import os
import sqlite3
import logging
from datetime import datetime

from keychain import get_secret

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
    # TypeError: Python 3.9 ne supporte pas la syntaxe X | Y dans les annotations
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
# Ce score mesure "à quel point on peut faire confiance à l'estimation du
# scanner pour CE TYPE de marché". Il ne re-score PAS prix/volume/temps
# (le scanner le fait déjà). Il apporte une info NOUVELLE : la prévisibilité
# intrinsèque de la catégorie × la cohérence du contexte.

# Prévisibilité de base par catégorie (0-1)
# = historiquement, à quel point les prix des marchés de cette catégorie
#   reflètent fidèlement le résultat final ?
_CATEGORY_PREDICTABILITY = {
    "SPORT_MAJEUR":    0.80,  # Résultats binaires, stats abondantes, modèles matures
    "MONETAIRE":       0.75,  # Fed telegraph ses décisions, marchés CME bien calibrés
    "ECONOMIE_MACRO":  0.60,  # Données publiques mais interprétation variable
    "TECHNOLOGIE":     0.55,  # IPOs/launches prévisibles, disruptions non
    "ENERGIE":         0.50,  # OPEC = cartel opaque, prix volatils
    "TRADE_TARIFS":    0.40,  # Dépend d'un acteur unique (président), imprévisible
    "POLITIQUE_NAT":   0.35,  # Sondages ≠ résultats, surprises fréquentes
    "POLITIQUE_INT":   0.30,  # Diplomatie opaque, jeux d'acteurs complexes
    "SANTE_PANDEMIE":  0.30,  # Virus = chaotique, FDA = lent mais binaire
    "ENVIRONNEMENT":   0.25,  # Météo > 48h = imprévisible
    "GEOPOLITIQUE":    0.20,  # Guerres, coups d'état = cygnes gris
    "CYGNE_NOIR":      0.05,  # Par définition imprévisible
    "SOCIETE_CULTURE":  0.40,  # Fourre-tout, prévisibilité moyenne
    "FINANCE_MARCHE":  0.55,  # Semi-efficient
    "SCIENCE":         0.45,  # Résultats longs, peer review
}


def heuristic_mapem_score(opp, category: str) -> int:
    """
    Score MAPEM 0-100 basé sur la PRÉVISIBILITÉ catégorielle.

    Mesure : "peut-on faire confiance au scanner pour ce type de marché ?"
    N'utilise PAS les mêmes signaux que le scanner (prix, volume, temps).
    Apporte une couche d'info nouvelle : catégorie × cohérence du contexte.
    """
    # --- 1. Prévisibilité de base de la catégorie (0-100) ---
    base = _CATEGORY_PREDICTABILITY.get(category, 0.40)
    score = base * 100  # 0-100

    # --- 2. Cohérence catégorie × horizon ---
    # Détecte les pièges : "Will X happen by end of year?" à 0.85 en janvier
    # vs en décembre. Le scanner ne voit pas cette différence.
    if 0 < opp.hours_left < float("inf"):
        if category == "SPORT_MAJEUR" and opp.hours_left > 168:
            # Sport à >7 jours = pari anticipé, moins fiable
            score -= 15
        elif category == "MONETAIRE" and opp.hours_left > 720:
            # Fed dans >30 jours = trop de temps pour un changement
            score -= 10
        elif category in ("POLITIQUE_NAT", "GEOPOLITIQUE") and opp.hours_left < 6:
            # Politique avec résolution imminente = souvent, le marché A raison
            # → le scanner surestime sa capacité à battre le marché
            score -= 10
        elif category == "SPORT_MAJEUR" and opp.hours_left < 3:
            # Sport imminent = le marché est ultra-efficient (scores en direct)
            # → le scanner surestime son edge, le prix EST la réalité
            score -= 5

    # --- 3. Piège du profit trop beau ---
    # Si le scanner voit >20% de profit sur une catégorie très prévisible,
    # c'est suspect — le marché efficient aurait déjà corrigé
    if opp.profit_potential > 0.20 and base > 0.60:
        score -= 15  # "si c'était vrai, quelqu'un l'aurait déjà acheté"
    elif opp.profit_potential > 0.40:
        score -= 10  # profit extrême = probablement un piège

    # --- 4. Zone d'incertitude maximale par catégorie ---
    # Prix ~50% = coin flip. Certaines catégories sont pires que d'autres ici.
    price = opp.current_price
    if 0.40 <= price <= 0.60:
        if category in ("GEOPOLITIQUE", "POLITIQUE_NAT", "POLITIQUE_INT"):
            score -= 20  # 50/50 + catégorie volatile = danger maximum
        elif category in ("TRADE_TARIFS", "CYGNE_NOIR"):
            score -= 15
        else:
            score -= 5  # toute catégorie est moins fiable en zone 50/50

    # --- 5. Convergence prix extrême × catégorie prévisible ---
    # Prix >90% sur du sport ou du monétaire = très forte conviction justifiée
    if price >= 0.90 and category in ("SPORT_MAJEUR", "MONETAIRE"):
        score += 10  # le marché ET la catégorie convergent
    elif price <= 0.10 and category in ("CYGNE_NOIR", "GEOPOLITIQUE"):
        score += 5  # "non, l'astéroïde ne va pas frapper" = safe

    # --- 6. Calibration historique (feedback loop) ---
    # Si on a des données MAPEM, ajuster selon notre performance passée
    score = _apply_calibration_adjustment(score, category)

    return max(0, min(100, int(score)))


def _apply_calibration_adjustment(score: float, category: str) -> float:
    """Ajuste le score selon la performance historique dans cette catégorie."""
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

        if row and row[0] >= 5:  # minimum 5 trades pour un signal fiable
            n_trades, avg_brier = row
            if avg_brier is not None:
                # Brier < 0.15 = bien calibré → bonus
                # Brier > 0.30 = on se trompe souvent → malus
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
# 2C. Score composite
# ---------------------------------------------------------------------------

def compute_composite(scanner_score: int, mapem_score: int) -> int:
    """Moyenne pondérée 60% scanner + 40% MAPEM."""
    return int(SCANNER_WEIGHT * scanner_score + MAPEM_WEIGHT * mapem_score)


# ---------------------------------------------------------------------------
# 2D. Analyseur Claude (à la demande)
# ---------------------------------------------------------------------------

POLYMARKET_MAPEM_PROMPT = """Tu analyses un marché de prédiction Polymarket.

MARCHÉ: {question}
PRIX ACTUEL: {price:.2f} (= probabilité implicite de {price:.0%})
CATÉGORIE: {category}

Donne une analyse MAPEM adaptée aux marchés de prédiction:
- Les "tickers" ne s'appliquent pas (marché binaire Yes/No)
- Le "posterior_prob" est ta meilleure estimation de la probabilité réelle
- Compare ta probabilité au prix du marché pour identifier les mispricings
- Utilise les 4 niveaux d'analyse MAPEM

Pour les signaux, utilise:
- ticker: "POLYMARKET"
- direction: "BUY" si ta probabilité > prix (sous-évalué), "SELL" si < prix (sur-évalué)
- Le mapem_score reflète la divergence entre ta probabilité et le prix × 100
"""


class PolymarketMAPEMAnalyzer:
    """Wrapper autour de MAPEMAutoAnalyzer adapté pour Polymarket."""

    def __init__(self):
        if not _mapem_available:
            raise RuntimeError("MAPEM non disponible — vérifiez ~/Desktop/Mapem/")
        self._analyzer = None

    def _get_analyzer(self):
        if self._analyzer is None:
            self._analyzer = MAPEMAutoAnalyzer(db_path=MAPEM_DB_PATH)
        return self._analyzer

    def deep_analyze(self, opp, category: str) -> dict:
        """
        Analyse approfondie via Claude API.
        Returns: {posterior_prob, mapem_score, analysis_summary, raw_result}
        """
        analyzer = self._get_analyzer()

        prompt = POLYMARKET_MAPEM_PROMPT.format(
            question=opp.market_question,
            price=opp.current_price,
            category=category,
        )

        result = analyzer.analyze_event(
            title=f"Polymarket: {opp.market_question[:80]}",
            summary=prompt,
            category=category,
            severity=5,
            regions=["US"],
            horizon="days" if 0 < opp.hours_left < 72 else "weeks",
        )

        if "error" in result:
            return {
                "posterior_prob": opp.estimated_value,
                "mapem_score": 50,
                "analysis_summary": f"Erreur: {result['error']}",
                "raw_result": result,
            }

        # Extraire la probabilité postérieure du premier scénario
        posterior_prob = opp.estimated_value
        analysis_summary = ""

        agent = get_mapem_agent()
        if result.get("forecast_ids"):
            try:
                conn = agent._connect()
                cursor = conn.execute(
                    "SELECT posterior_prob, scenario_label FROM bayesian_forecasts WHERE forecast_id = ?",
                    (result["forecast_ids"][0],)
                )
                row = cursor.fetchone()
                conn.close()
                if row:
                    posterior_prob = row["posterior_prob"]
                    analysis_summary = row["scenario_label"]
            except Exception:
                pass

        # Score MAPEM = divergence × 100
        divergence = abs(posterior_prob - opp.current_price)
        mapem_score = int(min(100, divergence * 100 + 50))

        return {
            "posterior_prob": posterior_prob,
            "mapem_score": mapem_score,
            "analysis_summary": analysis_summary,
            "raw_result": result,
        }


# ---------------------------------------------------------------------------
# 2D-bis. Avis rapide Claude — Screening top 3
# ---------------------------------------------------------------------------

SCREENING_PROMPT = """Tu es un analyste de marchés de prédiction. Voici les 3 meilleures opportunités détectées par un scanner automatique.

Pour CHAQUE opportunité, donne un verdict en 1-2 lignes :
- GO : l'opportunité semble solide, le prix est probablement sous-évalué
- PIEGE : quelque chose que le scanner ne voit pas (timing, contexte, ambiguïté de la question)
- INCERTAIN : pas assez d'info pour trancher

{opportunities}

Réponds UNIQUEMENT en JSON valide (pas de markdown) :
{{
  "verdicts": [
    {{"num": 1, "verdict": "GO|PIEGE|INCERTAIN", "raison": "1-2 phrases", "prob_estimee": 0.0-1.0}},
    {{"num": 2, "verdict": "GO|PIEGE|INCERTAIN", "raison": "1-2 phrases", "prob_estimee": 0.0-1.0}},
    {{"num": 3, "verdict": "GO|PIEGE|INCERTAIN", "raison": "1-2 phrases", "prob_estimee": 0.0-1.0}}
  ]
}}

Règles :
- prob_estimee = ta meilleure estimation de la probabilité RÉELLE (pas le prix du marché)
- Sois conservateur : signale les pièges que les chiffres ne montrent pas
- Considère le contexte actuel (date, actualité récente) si pertinent
"""


def screening_top3(opportunities: list, console) -> list:
    """
    Envoie les top 3 opportunités à Claude pour un avis rapide.
    Retourne la liste des verdicts [{num, verdict, raison, prob_estimee}].
    """
    import json

    if not _mapem_available:
        console.print("[red]MAPEM non disponible — impossible d'appeler Claude.[/red]")
        return []

    try:
        import anthropic
    except ImportError:
        console.print("[red]Package 'anthropic' non installé.[/red]")
        return []

    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY non trouvée dans le Keychain[/red]")
        console.print("[dim]Lance 'setup keychain' pour configurer tes secrets.[/dim]")
        return []

    top = opportunities[:3]
    if not top:
        console.print("[yellow]Aucune opportunité à analyser.[/yellow]")
        return []

    # Construire la description des opportunités
    opp_text = ""
    for i, opp in enumerate(top, 1):
        cat = getattr(opp, "mapem_category", "?") or "?"
        safe_q = opp.market_question[:200]  # tronquer pour éviter prompt injection
        opp_text += (
            f"\n#{i}. {safe_q}\n"
            f"   Catégorie: {cat} | Stratégie: {opp.strategy}\n"
            f"   Prix actuel: ${opp.current_price:.3f} ({opp.current_price:.0%}) | "
            f"Côté: {opp.outcome}\n"
            f"   Estimé scanner: ${opp.estimated_value:.3f} | "
            f"Profit potentiel: {opp.profit_potential:.1%}\n"
            f"   Score scanner: {opp.confidence_score} | "
            f"Score MAPEM: {getattr(opp, 'mapem_score', '?')}\n"
            f"   Résolution: {opp.hours_left:.0f}h | "
            f"Volume 24h: ${opp.volume_24h:,.0f}\n"
        )

    prompt = SCREENING_PROMPT.format(opportunities=opp_text)

    console.print("[dim]Appel Claude API pour avis rapide (~0.03$)...[/dim]")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Nettoyer d'éventuels backticks markdown
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        data = json.loads(raw)
        verdicts = data.get("verdicts", [])

        # Afficher les résultats
        from rich.table import Table
        from rich.panel import Panel
        from rich import box as rich_box

        table = Table(
            title="[bold gold1]  Screening Top 3  [/bold gold1]",
            box=rich_box.ROUNDED,
            border_style="bright_black",
            header_style="bold bright_cyan",
            row_styles=["", "bright_black"],
            padding=(0, 1),
        )
        table.add_column("#", width=3, justify="center", style="bold bright_cyan")
        table.add_column("Verdict", width=12, justify="center")
        table.add_column("Prob.", justify="right", width=6)
        table.add_column("vs Prix", justify="right", width=7)
        table.add_column("Raison", max_width=50, style="grey62")

        for v in verdicts:
            num = v.get("num", "?")
            verdict = v.get("verdict", "?")
            raison = v.get("raison", "").replace("[", "\\[")
            prob = v.get("prob_estimee", 0)

            # Couleur du verdict avec badges
            if verdict == "GO":
                v_str = "[bold green on grey11] GO [/bold green on grey11]"
            elif verdict == "PIEGE":
                v_str = "[bold red on grey11] PIEGE [/bold red on grey11]"
            else:
                v_str = "[bold yellow on grey11] INCERTAIN [/bold yellow on grey11]"

            # Divergence vs prix du marché
            opp_idx = num - 1 if isinstance(num, int) and 0 < num <= len(top) else -1
            if opp_idx >= 0:
                market_price = top[opp_idx].current_price
                div = prob - market_price
                if div > 0.05:
                    div_str = f"[bold green]+{div:.0%}[/bold green]"
                elif div < -0.05:
                    div_str = f"[bold red]{div:.0%}[/bold red]"
                else:
                    div_str = f"[yellow]{div:+.0%}[/yellow]"
            else:
                div_str = "?"

            table.add_row(str(num), v_str, f"[bold]{prob:.0%}[/bold]", div_str, raison)

        console.print()
        console.print(table)

        # Summary
        n_go = sum(1 for v in verdicts if v.get("verdict") == "GO")
        n_piege = sum(1 for v in verdicts if v.get("verdict") == "PIEGE")
        if n_piege > 0:
            console.print(f"\n  [bold yellow]{n_piege} piege(s) detecte(s)[/bold yellow]")
        if n_go > 0:
            console.print(f"  [bold green]{n_go} opportunite(s) validee(s)[/bold green]")

        return verdicts

    except json.JSONDecodeError:
        console.print("[red]Erreur: réponse Claude non parsable.[/red]")
        return []
    except Exception as e:
        console.print(f"[red]Erreur screening: {e}[/red]")
        return []


# ---------------------------------------------------------------------------
# 2D-ter. Avis rapide Claude — Screening d'une seule opportunité
# ---------------------------------------------------------------------------

SCREENING_SINGLE_PROMPT = """Tu es un analyste de marchés de prédiction. Voici une opportunité détectée par un scanner automatique.

Donne ton avis détaillé :
- GO : l'opportunité semble solide, le prix est probablement sous-évalué
- PIEGE : quelque chose que le scanner ne voit pas (timing, contexte, ambiguïté de la question)
- INCERTAIN : pas assez d'info pour trancher

{opportunity}

Réponds UNIQUEMENT en JSON valide (pas de markdown) :
{{
  "verdict": "GO|PIEGE|INCERTAIN",
  "raison": "2-3 phrases expliquant ton analyse",
  "prob_estimee": 0.0-1.0
}}

Règles :
- prob_estimee = ta meilleure estimation de la probabilité RÉELLE (pas le prix du marché)
- Sois conservateur : signale les pièges que les chiffres ne montrent pas
- Considère le contexte actuel (date, actualité récente) si pertinent
"""


def screening_single(opp, console) -> dict:
    """
    Envoie une seule opportunité à Claude pour un avis détaillé.
    Retourne {verdict, raison, prob_estimee} ou {} en cas d'erreur.
    """
    import json

    if not _mapem_available:
        console.print("[red]MAPEM non disponible — impossible d'appeler Claude.[/red]")
        return {}

    try:
        import anthropic
    except ImportError:
        console.print("[red]Package 'anthropic' non installé.[/red]")
        return {}

    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red]ANTHROPIC_API_KEY non trouvée dans le Keychain[/red]")
        console.print("[dim]Lance 'setup keychain' pour configurer tes secrets.[/dim]")
        return {}

    cat = getattr(opp, "mapem_category", "?") or "?"
    # Tronquer la question à 200 chars pour éviter le prompt injection
    safe_question = opp.market_question[:200]
    opp_text = (
        f"Marché: {safe_question}\n"
        f"Catégorie: {cat} | Stratégie: {opp.strategy}\n"
        f"Prix actuel: ${opp.current_price:.3f} ({opp.current_price:.0%}) | "
        f"Côté: {opp.outcome}\n"
        f"Estimé scanner: ${opp.estimated_value:.3f} | "
        f"Profit potentiel: {opp.profit_potential:.1%}\n"
        f"Score scanner: {opp.confidence_score} | "
        f"Score MAPEM: {getattr(opp, 'mapem_score', '?')}\n"
        f"Résolution: {opp.hours_left:.0f}h | "
        f"Volume 24h: ${opp.volume_24h:,.0f}\n"
    )

    prompt = SCREENING_SINGLE_PROMPT.format(opportunity=opp_text)

    console.print("[dim]Appel Claude API pour avis (~0.01$)...[/dim]")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        data = json.loads(raw)
        verdict = data.get("verdict", "?")
        raison = data.get("raison", "").replace("[", "\\[")
        prob = data.get("prob_estimee", 0)

        # Affichage
        from rich.panel import Panel
        from rich import box as rich_box

        if verdict == "GO":
            v_color = "green"
            badge = "[bold green on grey11] GO [/bold green on grey11]"
        elif verdict == "PIEGE":
            v_color = "red"
            badge = "[bold red on grey11] PIEGE [/bold red on grey11]"
        else:
            v_color = "yellow"
            badge = "[bold yellow on grey11] INCERTAIN [/bold yellow on grey11]"

        div = prob - opp.current_price
        if div > 0.05:
            div_str = f"[bold green]+{div:.0%}[/bold green] [bright_black]vs prix[/bright_black]"
        elif div < -0.05:
            div_str = f"[bold red]{div:.0%}[/bold red] [bright_black]vs prix[/bright_black]"
        else:
            div_str = f"[yellow]{div:+.0%}[/yellow] [bright_black]vs prix[/bright_black]"

        safe_question = opp.market_question.replace("[", "\\[")
        console.print(Panel(
            f"  {badge}\n\n"
            f"  [bold white]{safe_question}[/bold white]\n\n"
            f"  [grey62]{raison}[/grey62]\n\n"
            f"  [grey62]Probabilite estimee[/grey62]  [bold]{prob:.0%}[/bold]  {div_str}",
            title=f"[bold {v_color}]  Avis MAPEM  [/bold {v_color}]",
            border_style=v_color,
            box=rich_box.ROUNDED,
            padding=(1, 2),
        ))

        return data

    except json.JSONDecodeError:
        console.print("[red]Erreur: réponse Claude non parsable.[/red]")
        return {}
    except Exception as e:
        console.print(f"[red]Erreur screening: {e}[/red]")
        return {}


# ---------------------------------------------------------------------------
# 2E. Logger de trades
# ---------------------------------------------------------------------------

def log_trade_to_mapem(opp, amount: float, response: dict):
    """Enregistre un trade dans la DB MAPEM pour le tracking."""
    if not _mapem_available:
        return

    try:
        agent = get_mapem_agent()

        # Créer l'événement
        event = MAPEMEvent(
            title=f"Polymarket: {opp.market_question[:100]}",
            summary=f"Trade {opp.outcome} @ ${opp.current_price:.3f} pour ${amount:.2f}",
            category=getattr(opp, "mapem_category", "SOCIETE_CULTURE") or "SOCIETE_CULTURE",
            severity=3,
            regions=["US"],
            horizon="days" if 0 < opp.hours_left < 72 else "weeks",
        )

        # Analyse minimale
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

        # Scénario bayésien
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

        # Signal
        signal = TradingSignal(
            ticker="POLYMARKET",
            direction="BUY",
            conviction=opp.confidence_score / 100.0,
            rationale=f"Scanner: {opp.strategy} | Score: {opp.confidence_score} | {opp.details}",
            urgency="immediate",
            suggested_weight=amount / 42.0,  # % du budget total
            stop_loss_pct=0.15,
            take_profit_pct=opp.profit_potential,
            mapem_score=getattr(opp, "mapem_score", 50),
        )

        # Ensure POLYMARKET ticker exists in asset_universe
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
    """Affiche un dashboard de performance avec les données MAPEM."""
    from rich.table import Table
    from rich.panel import Panel
    from rich import box as rich_box

    if not os.path.exists(MAPEM_DB_PATH):
        console.print("  [yellow]Pas encore de donnees MAPEM. Effectuez des trades d'abord.[/yellow]")
        return

    try:
        db = sqlite3.connect(MAPEM_DB_PATH)

        # --- Trades par catégorie ---
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
            table = Table(
                title="[bold gold1]  Trades par Categorie  [/bold gold1]",
                box=rich_box.ROUNDED,
                border_style="bright_black",
                header_style="bold bright_cyan",
                row_styles=["", "bright_black"],
                padding=(0, 1),
            )
            table.add_column("Categorie", width=18, style="bold")
            table.add_column("Trades", justify="right", width=7, style="bold bright_cyan")
            table.add_column("Conviction", justify="right", width=11)
            table.add_column("MAPEM", justify="right", width=8)

            total_trades = 0
            for code, n, conv, mapem in rows:
                mapem_color = "green" if mapem >= 60 else "yellow" if mapem >= 40 else "red"
                table.add_row(
                    code, str(n),
                    f"{conv:.2f}",
                    f"[{mapem_color}]{mapem:.1f}[/{mapem_color}]",
                )
                total_trades += n

            console.print()
            console.print(table)
            console.print(f"\n  [grey62]Total trades logges:[/grey62] [bold bright_cyan]{total_trades}[/bold bright_cyan]")
        else:
            console.print("  [yellow]Aucun trade Polymarket trouve dans la DB MAPEM.[/yellow]")

        # --- Calibration (Brier scores) si disponible ---
        brier_rows = db.execute("""
            SELECT ec.code,
                   COUNT(*) as n,
                   ROUND(AVG(fo.brier_score), 4) as avg_brier,
                   ROUND(AVG(fo.predicted_prob), 3) as avg_pred,
                   ROUND(AVG(fo.actual_occurred * 1.0), 3) as avg_actual
            FROM forecast_outcomes fo
            JOIN bayesian_forecasts bf ON fo.forecast_id = bf.forecast_id
            JOIN major_events me ON bf.event_id = me.event_id
            JOIN event_categories ec ON me.category_id = ec.category_id
            GROUP BY ec.code
            ORDER BY avg_brier ASC
        """).fetchall()

        if brier_rows:
            cal_table = Table(
                title="[bold gold1]  Calibration Brier  [/bold gold1]",
                box=rich_box.ROUNDED,
                border_style="bright_black",
                header_style="bold bright_cyan",
                row_styles=["", "bright_black"],
                padding=(0, 1),
            )
            cal_table.add_column("Categorie", width=18, style="bold")
            cal_table.add_column("N", justify="right", width=5)
            cal_table.add_column("Brier", justify="right", width=8)
            cal_table.add_column("Pred", justify="right", width=7)
            cal_table.add_column("Actual", justify="right", width=7)

            for code, n, brier, pred, actual in brier_rows:
                brier_color = "green" if brier < 0.15 else "yellow" if brier < 0.25 else "red"
                cal_table.add_row(
                    code, str(n),
                    f"[bold {brier_color}]{brier:.4f}[/bold {brier_color}]",
                    f"{pred:.3f}", f"{actual:.3f}",
                )

            console.print()
            console.print(cal_table)

        db.close()

    except Exception as e:
        console.print(f"  [red]Erreur dashboard: {e}[/red]")


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
