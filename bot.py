#!/usr/bin/env python3
"""
RupeeHunter v3.0 🗡️ — Bot Polymarket semi-automatique
"""

import re
import sys
import time
import math
import random
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm, FloatPrompt

from config import (
    MAX_PER_TRADE, MIN_CONFIDENCE_SCORE,
    SCAN_INTERVAL_SECONDS, HUMAN_BOOST_AMOUNT, HUMAN_FLAG_AMOUNT,
)
from models import Opportunity, MarketView, CategoryInfo, market_view_to_opportunity
from scanner import scan_all
from trader import Trader

console = Console()
PAGE_SIZE = 8


# ─────────────────────────────────────────────────────────
# 🧚 Navi — Personnalité
# ─────────────────────────────────────────────────────────

NAVI_LINES = {
    "scan_found": [
        "Hey! Listen! {n} trésors dans le donjon !",
        "Da da da DAAAA! 🎵 {n} coffres à ouvrir !",
        "The Lens of Truth reveals... {n} opportunités !",
        "Lonk squint... {n} trucs louches repérés ! 👀",
    ],
    "scan_empty": [
        "It's a secret to everybody... (rien trouvé)",
        "Le coffre était vide 📦 Réessaie ?",
        "Lonk a cherché partout. Nada. 🤷",
        "Le donjon est vide. Zelda a tout pris.",
    ],
    "buy_confirm": [
        "Coffre ouvert ! DA DA DA DAAAA! 💎",
        "You got: RUPEES! *tient l'item au-dessus de sa tête* 🏆",
        "+${amount:.2f} investies. Que Hylia te protège. 🙏",
    ],
    "buy_cancel": [
        "Le bouclier avant l'épée, toujours. 🛡️",
        "Sage décision. Même Link réfléchit parfois.",
        "Trade annulé. La sagesse, Triforce la plus sous-cotée.",
    ],
    "error": [
        "GAME OVER... jk, c'est juste une erreur 😅",
        "Lonk est tombé dans un trou. Mais il se relève !",
        "Oops. Navi blame le lag. 🐛",
    ],
    "boost": [
        "Power-up activé ! ⬆️ Ton instinct parle.",
        "Score boosté ! Tu connais ce donjon mieux que Navi. 💪",
    ],
    "flag": [
        "DANGER! Navi sent le piège ! 🚩",
        "Watch out! C'est un Like Like déguisé ! 🚩",
    ],
    "quit": [
        "Save & Quit? 🌙 À plus, RupeeHunter !",
        "May the Triforce be with you. 💎✨",
        "Lonk range son épée. Bonne nuit, héros. 🗡️",
    ],
    "search_found": [
        "Hey! {n} résultats trouvés ! 🔎",
        "{n} marchés repérés ! Lonk approuve. 👀",
        "Carte mise à jour ! {n} points d'intérêt. 🗺️",
    ],
    "search_empty": [
        "Aucun résultat... Le mot de passe était faux ? 🤔",
        "Nada. Essaie un autre sort — euh, terme. 🧙",
    ],
    "idle": [
        "... ... ... *Navi s'endort* 💤",
        "*tourne en cercles au-dessus de ta tête* 🧚",
        "Hey! Tu scannes ou tu rêves ? 😴",
        "Lonk attend patiemment... *tape du pied*",
        "*fait des ricochets sur l'eau*",
    ],
    "unknown_cmd": [
        "Hein ? Tape [cyan]?[/cyan] pour l'aide.",
        "Commande inconnue. Navi est confuse. [cyan]?[/cyan]",
        "C'est pas une mélodie d'Ocarina ça. [cyan]?[/cyan] 🎵",
    ],
}


def navi_say(msg: str):
    """Navi parle (message custom)."""
    console.print(f"[bold magenta]🧚 Navi:[/bold magenta] {msg}")


def navi_quip(context: str, **kwargs) -> str:
    """Pick une ligne aléatoire de Navi et l'affiche."""
    lines = NAVI_LINES.get(context, ["..."])
    line = random.choice(lines).format(**kwargs)
    navi_say(line)
    return line


# ─────────────────────────────────────────────────────────
# Affichage
# ─────────────────────────────────────────────────────────

def show_banner(balance=None):
    bal_str = f"${balance:.2f}" if balance is not None else "connexion requise"
    console.print(Panel(
        f"[bold green]🗡️  RUPEEHUNTER[/bold green]  v3.0\n"
        f"💎 Rupee Pouch: {bal_str} USDC  ·  Max/trade: ${MAX_PER_TRADE:.2f}\n"
        "Mode: Semi-auto — tu confirmes chaque trade",
        border_style="green",
    ))


def show_menu():
    console.print(Panel(
        "[bold green]Scan[/bold green]          →  🔍 Lens of Truth\n"
        "[bold green]Scan 6h[/bold green]       →  Marchés qui ferment bientôt\n"
        "[bold green]Explore[/bold green]       →  🔭 Naviguer par catégorie\n"
        "[bold green]Search X[/bold green]      →  🔎 Recherche libre\n"
        "[bold green]Hot[/bold green]           →  🔥 Plus actifs\n"
        "[bold green]New[/bold green]           →  ✨ Plus récents\n"
        "· · · · · · · · · · · · · · · · · · · · · · · · ·\n"
        "[bold cyan]Buy N[/bold cyan]         →  Acheter #N\n"
        "[bold cyan]Sell N[/bold cyan]        →  Vendre position #N\n"
        "[bold cyan]Info N[/bold cyan]        →  Détails #N\n"
        "[bold cyan]Avis[/bold cyan]          →  🧚 Navi analyse le top 5\n"
        "[bold cyan]Avis N[/bold cyan]        →  🧚 Navi analyse #N\n"
        "· · · · · · · · · · · · · · · · · · · · · · · · ·\n"
        "[bold yellow]Note N texte[/bold yellow]  →  📝 Ta note\n"
        "[bold yellow]Boost N[/bold yellow]       →  ⬆️  Confiant\n"
        "[bold yellow]Flag N[/bold yellow]        →  🚩 Piège\n"
        "· · · · · · · · · · · · · · · · · · · · · · · · ·\n"
        "[bold magenta]Portfolio[/bold magenta]     →  💰 Rupee Pouch\n"
        "[bold magenta]Dashboard[/bold magenta]     →  📊 Sheikah Slate\n"
        "[bold magenta]Accuracy[/bold magenta]      →  📈 Stats\n"
        "[bold magenta]Streak[/bold magenta]        →  🔥 Série\n"
        "[bold magenta]History[/bold magenta]       →  📜 Trades récents\n"
        "[bold magenta]Orders[/bold magenta]        →  📋 Ordres\n"
        "· · · · · · · · · · · · · · · · · · · · · · · · ·\n"
        "[dim]?  Aide  ·  Q  Quitter[/dim]",
        title="🧚 Hey! Listen!",
        border_style="green",
    ))


def display_opportunities(opportunities: list[Opportunity], page: int = 0):
    """Affiche les opportunités avec pagination."""
    if not opportunities:
        return [], 0

    total_pages = max(1, math.ceil(len(opportunities) / PAGE_SIZE))
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    visible = opportunities[start:end]

    try:
        from mapem_integration import category_short
    except ImportError:
        category_short = lambda c: c[:4].upper() if c else ""

    console.print()
    for i, opp in enumerate(visible, start + 1):
        display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score
        score_color = "green" if display_score >= 70 else "yellow" if display_score >= 50 else "red"
        profit_color = "green" if opp.profit_potential > 0.10 else "yellow"

        if 0 < opp.hours_left < 1:
            time_str = f"⏱ {opp.hours_left * 60:.0f}min"
        elif 0 < opp.hours_left < 24:
            time_str = f"⏱ {opp.hours_left:.0f}h"
        elif 0 < opp.hours_left < 168:
            time_str = f"⏱ {opp.hours_left / 24:.0f}j"
        else:
            time_str = ""

        cat_str = category_short(opp.mapem_category) if opp.mapem_category else ""

        parts = [f"[{score_color}]●{display_score}[/{score_color}]"]
        if cat_str:
            parts.append(cat_str)
        parts.append(opp.strategy)
        parts.append(f"{opp.outcome.replace('[', chr(92) + '[')} @ ${opp.current_price:.2f}")
        parts.append(f"[{profit_color}]+{opp.profit_potential:.0%}[/{profit_color}]")
        if time_str:
            parts.append(time_str)

        if opp.navi_verdict == "GO":
            parts.append("[green]🧚[/green]")
        elif opp.navi_verdict == "PIEGE":
            parts.append("[red]🚩[/red]")
        if opp.human_score > 0:
            parts.append("[yellow]⬆[/yellow]")
        elif opp.human_score < 0:
            parts.append("[red]⬇[/red]")

        safe_question = opp.market_question.replace("[", "\\[")
        console.print(f" [bold]#{i:<3}[/bold] {' · '.join(parts)}")
        console.print(f"      [dim]{safe_question}[/dim]")

    console.print()
    nav = []
    if total_pages > 1:
        nav.append(f"[dim]p.{page + 1}/{total_pages}[/dim]")
        if page > 0:
            nav.append("[cyan]P[/cyan] précédent")
        if page < total_pages - 1:
            nav.append("[cyan]N[/cyan] suivant")
    nav.append("[dim]Tape un numéro pour les détails, ou[/dim] [cyan]buy N[/cyan] · [cyan]avis N[/cyan]")
    console.print("  " + "  ·  ".join(nav))

    return visible, total_pages


def display_market_views(markets, title="Marchés"):
    """Affiche une liste de MarketView avec actions."""
    if not markets:
        return

    console.print(f"\n[bold]🔭 {title}[/bold] [dim]({len(markets)})[/dim]")
    for i, m in enumerate(markets, 1):
        prices_str = ""
        if m.prices and len(m.prices) >= 2:
            prices_str = f"Yes ${m.prices[0]:.2f} / No ${m.prices[1]:.2f}"
        elif m.prices:
            prices_str = f"${m.prices[0]:.2f}"

        vol_str = f"Vol ${m.volume:,.0f}" if m.volume else ""
        safe_q = m.question.replace("[", "\\[")

        parts = []
        if prices_str:
            parts.append(prices_str)
        if vol_str:
            parts.append(vol_str)
        if m.tags:
            parts.append(f"[dim]{', '.join(m.tags[:2])}[/dim]")

        console.print(f" [bold]#{i:<3}[/bold] {safe_q}")
        if parts:
            console.print(f"      {' · '.join(parts)}")

    console.print()
    console.print("  [dim]Tape un numéro pour les détails, ou[/dim] [cyan]buy N[/cyan] · [cyan]avis N[/cyan]")


# ─────────────────────────────────────────────────────────
# Parser de commandes
# ─────────────────────────────────────────────────────────

def parse_command(text: str, has_results: bool, context: str = "none"):
    """Parse l'entrée utilisateur et retourne (cmd, arg).

    context : le dernier écran actif (scan, explore, search, hot, new, portfolio, none).
    Un nombre seul est routé selon le contexte :
      - explore → explore N (navigation catégories/events)
      - scan/search/hot/new → info N (détails de l'item)
      - none → unknown
    """
    text = text.strip()
    if not text:
        return ("noop", None)
    if len(text) > 500:
        return ("unknown", None)

    low = text.lower()

    if low in ("q", "quit", "exit", "quitter"):
        return ("quit", None)

    if low in ("?", "help", "aide", "h"):
        return ("help", None)
    if low in ("menu",):
        return ("menu", None)

    if low in ("n", "next", "suite"):
        return ("next_page", None)
    if low in ("p", "prev", "retour", "précédent"):
        return ("prev_page", None)

    m = re.match(r'^scan\s+(\d+)\s*h?$', low)
    if m:
        return ("scan_hours", int(m.group(1)))

    if low in ("scan soir", "soir", "t", "tonight"):
        return ("scan_hours", 16)

    if low in ("scan", "s", "lens"):
        return ("scan", None)

    m = re.match(r'^(?:explore|explorer|tags?)\s+(.+)$', low)
    if m:
        return ("explore", m.group(1).strip())
    if low in ("explore", "explorer", "tags"):
        return ("explore", None)

    m = re.match(r'^(?:search|cherche|find)\s+(.+)$', low)
    if m:
        return ("search", m.group(1).strip())

    if low in ("hot", "trending", "🔥"):
        return ("hot", None)

    if low in ("new", "nouveau", "recent", "✨"):
        return ("new", None)

    m = re.match(r'^(?:buy|acheter)\s+([1-9]\d*)$', low)
    if m:
        return ("buy", int(m.group(1)))

    m = re.match(r'^(?:sell|vendre|vend)\s+([1-9]\d*)$', low)
    if m:
        return ("sell", int(m.group(1)))

    m = re.match(r'^(?:info|détail|detail|i)\s+([1-9]\d*)$', low)
    if m:
        return ("info", int(m.group(1)))

    m = re.match(r'^(?:avis|a|claude|navi)\s+([1-9]\d*)$', low)
    if m:
        return ("avis", int(m.group(1)))

    if low in ("avis", "a", "claude", "navi"):
        return ("avis", None)

    m = re.match(r'^(?:note)\s+([1-9]\d*)\s+(.+)$', low)
    if m:
        return ("note", (int(m.group(1)), text[len(m.group(0)) - len(m.group(2)):].strip()))

    m = re.match(r'^(?:boost|up)\s+([1-9]\d*)$', low)
    if m:
        return ("boost", int(m.group(1)))

    m = re.match(r'^(?:flag|down|piege|piège)\s+([1-9]\d*)$', low)
    if m:
        return ("flag", int(m.group(1)))

    if low in ("portfolio", "pf", "positions", "pouch", "rupee"):
        return ("portfolio", None)

    m = re.match(r'^(?:mapem|m)\s+([1-9]\d*)$', low)
    if m:
        return ("mapem", int(m.group(1)))

    if low in ("orders", "ordres", "order"):
        return ("orders", None)

    if low in ("cancel", "annuler"):
        return ("cancel", None)

    if low in ("auto",):
        return ("auto", None)

    if low in ("test",):
        return ("test", None)

    if low in ("dashboard", "d", "dash", "sheikah", "slate"):
        return ("dashboard", None)

    if low in ("accuracy", "acc", "perf", "stats"):
        return ("accuracy", None)

    if low in ("streak", "série", "serie"):
        return ("streak", None)

    if low in ("history", "hist", "historique"):
        return ("history", None)

    if low in ("setup", "setup keychain", "setup sécurité", "setup securite", "keychain"):
        return ("setup_keychain", None)

    # Nombre seul → routage contextuel
    if low.isdigit():
        num = int(low)
        if num < 1:
            return ("unknown", None)
        if context == "explore":
            return ("explore", str(num))
        if has_results:
            return ("info", num)
        return ("unknown", None)

    return ("unknown", None)


# ─────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────

def handle_scan(max_hours=None, tag_id=None):
    """Scan et retourne les opportunités."""
    label = "tous les marchés"
    if max_hours:
        label = f"marchés ≤{max_hours}h"
    elif tag_id:
        label = f"catégorie {tag_id}"

    try:
        with console.status(f"[bold magenta]Lens of Truth... ({label})[/bold magenta]"):
            return scan_all(max_hours=max_hours, tag_id=tag_id)
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")
        return []


def handle_info(opp: Opportunity):
    """Affiche le détail complet d'une opportunité."""
    try:
        from mapem_integration import category_short
        cat = category_short(opp.mapem_category) if opp.mapem_category else "—"
    except ImportError:
        cat = opp.mapem_category or "—"

    display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score

    desc = opp.market_description.strip() if opp.market_description else "[dim]Pas de description[/dim]"
    safe_desc = desc.replace("[", "\\[") if opp.market_description else desc

    navi_line = ""
    if opp.navi_verdict:
        navi_color = {"GO": "green", "PIEGE": "red"}.get(opp.navi_verdict, "yellow")
        navi_line = (
            f"\n[bold cyan]🧚 Avis Navi[/bold cyan]\n"
            f"  Verdict:       [{navi_color}][bold]{opp.navi_verdict}[/bold][/{navi_color}]\n"
            f"  Prob. estimée: {opp.navi_prob:.0%}\n"
            f"  {opp.navi_analysis}\n"
        )

    human_line = ""
    if opp.human_score != 0:
        h_color = "green" if opp.human_score > 0 else "red"
        human_line = f"\n  [bold]Expertise humaine:[/bold]  [{h_color}]{opp.human_score:+d}[/{h_color}]"
        if opp.human_notes:
            human_line += f"\n  📝 {opp.human_notes[:200]}"
        human_line += "\n"

    info = (
        f"[bold]{opp.market_question.replace('[', chr(92) + '[')}[/bold]\n\n"
        f"{safe_desc}\n\n"
        f"  Stratégie:     {opp.strategy}\n"
        f"  Côté:          {opp.outcome} @ ${opp.current_price:.3f} ({opp.current_price:.0%})\n"
        f"  Estimé:        ${opp.estimated_value:.3f} ({opp.estimated_value:.0%})\n"
        f"  Profit:        {opp.profit_potential:.1%}\n"
        f"  E[P] sur $10:  ${opp.expected_profit_usd:.2f}\n"
        f"  Volume 24h:    ${opp.volume_24h:,.0f}\n"
        f"  Résolution:    {opp.hours_left:.0f}h\n"
        f"  Catégorie:     {cat}\n"
        f"  Score:         {display_score}/100"
        f"{human_line}"
        f"{navi_line}\n"
        f"[dim]{opp.details}[/dim]"
    )

    console.print(Panel(info, title="🔎 Détails", border_style="cyan"))

    book = None
    try:
        from scanner import get_order_book
        with console.status("[bold magenta]Carnet d'ordres...[/bold magenta]"):
            book = get_order_book(opp.token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if bids or asks:
            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 0
            bid_size = float(bids[0].get("size", 0)) if bids else 0
            ask_size = float(asks[0].get("size", 0)) if asks else 0
            spread = (best_ask - best_bid) if best_ask > best_bid else 0

            ob_text = (
                f"  Best bid:  ${best_bid:.3f}  ({bid_size:.0f} shares)\n"
                f"  Best ask:  ${best_ask:.3f}  ({ask_size:.0f} shares)"
            )
            if best_ask > 0:
                ob_text += f"\n  Spread:    ${spread:.3f} ({spread / best_ask:.1%})"
            console.print(ob_text)
    except Exception:
        pass

    # Proposer l'analyse Navi
    console.print(f"\n[dim]  [cyan]a[/cyan] = analyse rapide  ·  [cyan]d[/cyan] = deep analysis  ·  autre = retour[/dim]")
    choice = Prompt.ask("", default="")
    low = choice.strip().lower()
    if low in ("a", "avis", "analyser"):
        try:
            from mapem_integration import screening_single
            with console.status("[bold magenta]Hey! Listen! Navi réfléchit...[/bold magenta]"):
                screening_single(opp, console)
        except Exception as e:
            console.print(f"[red]Erreur analyse: {e}[/red]")
    elif low in ("d", "deep"):
        _handle_deep_analysis(opp, book)


def _summarize_order_book(bids: list, asks: list) -> str:
    """Condense le carnet d'ordres en ~8 lignes pour le prompt Navi."""
    lines = []
    depth = 10

    top_bids = bids[:5]
    top_asks = asks[:5]

    if top_bids:
        lines.append("TOP BIDS:")
        for b in top_bids:
            lines.append(f"  ${float(b['price']):.3f}  x{float(b.get('size', 0)):,.0f}")
    if top_asks:
        lines.append("TOP ASKS:")
        for a in top_asks:
            lines.append(f"  ${float(a['price']):.3f}  x{float(a.get('size', 0)):,.0f}")

    bid_liq = sum(float(b.get("size", 0)) for b in bids[:depth])
    ask_liq = sum(float(a.get("size", 0)) for a in asks[:depth])
    total = bid_liq + ask_liq

    if top_bids and top_asks:
        best_bid = float(top_bids[0]["price"])
        best_ask = float(top_asks[0]["price"])
        spread = best_ask - best_bid
        lines.append(f"Spread: ${spread:.3f} ({spread / best_ask:.1%})" if best_ask > 0 else f"Spread: ${spread:.3f}")

    lines.append(f"Liquidité 10 niveaux: {bid_liq:,.0f} bid / {ask_liq:,.0f} ask")

    if total > 0:
        ratio = bid_liq / total
        imbalance = "acheteurs" if ratio > 0.55 else "vendeurs" if ratio < 0.45 else "équilibré"
        lines.append(f"Ratio bid/ask: {ratio:.0%}/{1 - ratio:.0%} — pression {imbalance}")

    # Détection de murs (niveau > 30% du côté)
    for side_name, side_data, side_total in [("bid", bids[:depth], bid_liq), ("ask", asks[:depth], ask_liq)]:
        if side_total > 0:
            for level in side_data:
                size = float(level.get("size", 0))
                if size > side_total * 0.30:
                    lines.append(f"MUR {side_name.upper()}: ${float(level['price']):.3f} ({size:,.0f} = {size / side_total:.0%} du côté)")
                    break

    return "\n".join(lines)


def _handle_deep_analysis(opp: Opportunity, book: dict | None):
    """Lance la deep analysis Navi et affiche les résultats."""
    try:
        from navi import get_navi
        navi = get_navi()

        if not navi.available:
            console.print("[yellow]Navi indisponible.[/yellow]")
            return

        ob_summary = ""
        if book:
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            if bids or asks:
                ob_summary = _summarize_order_book(bids, asks)

        cat = opp.mapem_category or "?"
        quota = navi.quota_status()
        console.print(f"[dim]Deep analysis en cours (gratuit via Max) "
                      f"[{quota['remaining']}/{quota['limit']}]...[/dim]")

        with console.status("[bold magenta]Deep analysis en cours...[/bold magenta]"):
            result = navi.deep_analyze_single(
                question=opp.market_question,
                price=opp.current_price,
                category=cat,
                strategy=opp.strategy,
                outcome=opp.outcome,
                hours_left=opp.hours_left,
                volume=opp.volume_24h,
                description=opp.market_description,
                composite_score=opp.composite_score,
                human_notes=opp.human_notes,
                order_book_summary=ob_summary,
            )

        if not result:
            console.print("[yellow]Navi n'a pas pu analyser ce marché.[/yellow]")
            return

        # Mettre à jour l'opportunité
        opp.navi_verdict = result.get("verdict", opp.navi_verdict)
        opp.navi_prob = result.get("prob_estimee", opp.navi_prob)
        opp.navi_analysis = result.get("contexte", opp.navi_analysis)

        _display_deep_analysis(opp, result)

    except Exception as e:
        console.print(f"[red]Erreur deep analysis: {e}[/red]")


def _display_deep_analysis(opp: Opportunity, result: dict):
    """Affiche les 5 panels Rich de la deep analysis."""
    verdict = result.get("verdict", "INCERTAIN")
    confiance = result.get("confiance", 3)
    prob = result.get("prob_estimee", 0)
    contexte = result.get("contexte", "").replace("[", "\\[")
    ob_analysis = result.get("order_book", "").replace("[", "\\[")
    risques = result.get("risques", [])
    entree = result.get("entree", {})

    v_colors = {"GO": "green", "PIEGE": "red", "INCERTAIN": "yellow"}
    v_color = v_colors.get(verdict, "yellow")

    # Gauge confiance
    filled = confiance
    empty = 5 - filled
    gauge = f"[bold {v_color}]{'█' * filled}[/bold {v_color}][dim]{'░' * empty}[/dim] {confiance}/5"

    # Prob vs marché
    div = prob - opp.current_price
    if div > 0.05:
        div_str = f"[green]+{div:.0%}[/green] vs marché ({opp.current_price:.0%})"
    elif div < -0.05:
        div_str = f"[red]{div:.0%}[/red] vs marché ({opp.current_price:.0%})"
    else:
        div_str = f"[yellow]{div:+.0%}[/yellow] vs marché ({opp.current_price:.0%})"

    safe_q = opp.market_question.replace("[", "\\[")

    # Panel 1 — DEEP ANALYSIS
    console.print(Panel(
        f"[bold {v_color}]{verdict}[/bold {v_color}]  —  {safe_q}\n\n"
        f"  Confiance:  {gauge}\n"
        f"  Prob. estimée: [bold]{prob:.0%}[/bold]  ({div_str})",
        title="🧚 DEEP ANALYSIS",
        border_style=v_color,
    ))

    # Panel 2 — Contexte
    if contexte:
        console.print(Panel(
            contexte,
            title="📋 Contexte",
            border_style="cyan",
        ))

    # Panel 3 — Carnet d'ordres
    if ob_analysis:
        console.print(Panel(
            ob_analysis,
            title="📊 Carnet d'ordres",
            border_style="blue",
        ))

    # Panel 4 — Risques
    if risques:
        risk_lines = "\n".join(f"  • {r}" for r in risques if r)
        console.print(Panel(
            risk_lines.replace("[", "\\["),
            title="⚠️  Risques",
            border_style="yellow",
        ))

    # Panel 5 — Stratégie d'entrée
    if entree:
        action = entree.get("action", "WAIT")
        a_colors = {"BUY": "green", "WAIT": "yellow", "PASS": "red"}
        a_color = a_colors.get(action, "yellow")

        prix_cible = entree.get("prix_cible", 0)
        sizing = entree.get("sizing", "PETIT")
        timing = entree.get("timing", "").replace("[", "\\[")
        raison = entree.get("raison", "").replace("[", "\\[")

        entry_text = (
            f"  Action:      [bold {a_color}]{action}[/bold {a_color}]\n"
            f"  Prix cible:  ${prix_cible:.3f}\n"
            f"  Sizing:      {sizing}"
        )
        if timing:
            entry_text += f"\n  Timing:      {timing}"
        if raison:
            entry_text += f"\n  Raison:      {raison}"

        console.print(Panel(
            entry_text,
            title="🎯 Stratégie d'entrée",
            border_style=a_color,
        ))


def _execute_buy_flow(trader: Trader, opp: Opportunity):
    """Flux d'achat avec logging dans le learner."""
    amount = FloatPrompt.ask(
        f"💰 Combien de rupees ? (max ${MAX_PER_TRADE})", default=MAX_PER_TRADE)
    amount = min(amount, MAX_PER_TRADE)

    trader.propose_trade(opp, amount)

    order_type = Prompt.ask("Type d'ordre", choices=["market", "limit"], default="market")

    limit_price = None
    if order_type == "limit":
        limit_price = FloatPrompt.ask("Prix limite", default=opp.current_price)

    if not Confirm.ask("[bold]Confirmer ce trade ?[/bold]", default=False):
        navi_quip("buy_cancel")
        return

    if not trader.connected:
        with console.status("[bold magenta]Connexion au CLOB...[/bold magenta]"):
            if not trader.connect():
                return

    with console.status("[bold magenta]Opening treasure chest...[/bold magenta]"):
        if order_type == "market":
            resp = trader.execute_buy(opp, amount)
        else:
            resp = trader.execute_limit_buy(opp, amount, limit_price)

    if resp and resp.get("success"):
        try:
            from learner import get_learner
            size = amount / opp.current_price if opp.current_price > 0 else 0
            get_learner().record_buy(opp, amount, size)
        except (ImportError, Exception):
            pass
        navi_quip("buy_confirm", amount=amount)


def handle_avis(opportunities: list[Opportunity], idx: int = None):
    """Screening via Navi."""
    if not opportunities:
        navi_say("Fais un [cyan]Scan[/cyan] ou [cyan]Search[/cyan] d'abord !")
        return

    if idx is not None:
        if idx < 1 or idx > len(opportunities):
            console.print(f"[red]Numéro invalide (1-{len(opportunities)}).[/red]")
            return
        opp = opportunities[idx - 1]
        try:
            from mapem_integration import screening_single
            with console.status("[bold magenta]Hey! Listen! Navi réfléchit...[/bold magenta]"):
                screening_single(opp, console)
        except ImportError:
            navi_say("Module MAPEM non disponible.")
        except Exception as e:
            navi_quip("error")
            console.print(f"[dim]{e}[/dim]")
        return

    try:
        from mapem_integration import screening_top
        with console.status("[bold magenta]Hey! Listen! Navi analyse le top 5...[/bold magenta]"):
            screening_top(opportunities, console, count=5)
    except ImportError:
        navi_say("Module MAPEM non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_note(opportunities: list[Opportunity], idx: int, note_text: str):
    """Ajoute une note d'expertise humaine."""
    if not opportunities:
        navi_say("Fais un [cyan]Scan[/cyan] d'abord !")
        return
    if idx < 1 or idx > len(opportunities):
        console.print(f"[red]Numéro invalide (1-{len(opportunities)}).[/red]")
        return

    opp = opportunities[idx - 1]
    opp.human_notes = note_text[:500]

    try:
        from navi import get_navi
        navi = get_navi()
        if navi.available:
            with console.status("[bold magenta]Navi re-score avec ton expertise...[/bold magenta]"):
                result = navi.rescore_with_note(
                    question=opp.market_question,
                    price=opp.current_price,
                    category=opp.mapem_category or "SOCIETE_CULTURE",
                    human_note=note_text,
                )
            if result:
                impact = result.get("human_impact", 0)
                opp.human_score += impact
                opp.navi_verdict = result.get("verdict", opp.navi_verdict)
                opp.navi_analysis = result.get("raison", opp.navi_analysis)
                opp.navi_prob = result.get("prob_estimee", opp.navi_prob)

                from mapem_integration import compute_composite_v3
                opp.composite_score = compute_composite_v3(
                    opp.confidence_score, opp.mapem_score, opp.human_score)

                color = "green" if impact >= 0 else "red"
                navi_say(f"Note intégrée ! Impact: [{color}]{impact:+d}[/{color}] "
                         f"→ Composite: {opp.composite_score}/100")
                return
    except (ImportError, Exception):
        pass

    navi_say(f"Note enregistrée pour #{idx}. 'boost' ou 'flag' pour ajuster le score.")


def handle_boost(opportunities: list[Opportunity], idx: int):
    """Boost le score humain."""
    if not opportunities:
        navi_say("Fais un [cyan]Scan[/cyan] d'abord !")
        return
    if idx < 1 or idx > len(opportunities):
        console.print(f"[red]Numéro invalide (1-{len(opportunities)}).[/red]")
        return

    opp = opportunities[idx - 1]
    opp.human_score = min(100, opp.human_score + HUMAN_BOOST_AMOUNT)

    try:
        from mapem_integration import compute_composite_v3
        opp.composite_score = compute_composite_v3(
            opp.confidence_score, opp.mapem_score, opp.human_score)
    except ImportError:
        pass

    navi_quip("boost")
    console.print(f"  Score humain: [green]{opp.human_score:+d}[/green] "
                  f"→ Composite: {opp.composite_score}/100")


def handle_flag(opportunities: list[Opportunity], idx: int):
    """Flag une opportunité comme piège."""
    if not opportunities:
        navi_say("Fais un [cyan]Scan[/cyan] d'abord !")
        return
    if idx < 1 or idx > len(opportunities):
        console.print(f"[red]Numéro invalide (1-{len(opportunities)}).[/red]")
        return

    opp = opportunities[idx - 1]
    opp.human_score = max(-100, opp.human_score + HUMAN_FLAG_AMOUNT)

    try:
        from mapem_integration import compute_composite_v3
        opp.composite_score = compute_composite_v3(
            opp.confidence_score, opp.mapem_score, opp.human_score)
    except ImportError:
        pass

    navi_quip("flag")
    console.print(f"  Score humain: [red]{opp.human_score:+d}[/red] "
                  f"→ Composite: {opp.composite_score}/100")


def _filter_live_markets(markets):
    """Enlève les marchés résolus (prix 0.00/1.00)."""
    return [m for m in markets if m.prices and any(0.01 <= p <= 0.99 for p in m.prices)]


# Navigation explore : Categories -> Sous-categories -> Events -> Markets
_explore_categories: list[CategoryInfo] = []  # liste affichee (top-level ou sub)
_explore_events: list = []
_explore_level: str = "none"  # "categories", "subcategories", "events", "none"
_explore_parent_cat: CategoryInfo | None = None  # categorie parente active


def _display_categories(categories: list[CategoryInfo], title: str = "Catégories Polymarket"):
    """Affiche la liste des categories."""
    console.print(f"\n[bold]🗂️  {title}[/bold] [dim]({len(categories)})[/dim]")
    for i, cat in enumerate(categories, 1):
        console.print(f"  [bold]#{i:<3}[/bold] [cyan]{cat.label}[/cyan]")
    console.print(f"\n[dim]Tape un numéro ou un nom de catégorie pour entrer.[/dim]")


def _display_subcategories(subcats: list[CategoryInfo], parent: CategoryInfo):
    """Affiche les sous-categories avec option 'Tous'."""
    console.print(f"\n[bold]🗂️  {parent.label}[/bold] [dim]({len(subcats)} sous-catégories)[/dim]")
    console.print(f"  [bold]#{'0':<3}[/bold] [yellow]Tous les {parent.label}[/yellow]")
    for i, cat in enumerate(subcats, 1):
        console.print(f"  [bold]#{i:<3}[/bold] [cyan]{cat.label}[/cyan]")
    console.print(f"\n[dim]Tape un numéro, ou 0 pour tout voir.[/dim]")


def _display_events(events: list, title: str = "Événements"):
    """Affiche la liste des events avec numéros."""
    console.print(f"\n[bold]📋 {title}[/bold] [dim]({len(events)})[/dim]")
    for i, ev in enumerate(events, 1):
        live = len(_filter_live_markets(ev.markets))
        console.print(f"  [bold]#{i:<3}[/bold] [cyan]{ev.title}[/cyan] ({live} actifs, Vol ${ev.volume:,.0f})")
    console.print(f"\n[dim]Tape un numéro pour voir les marchés d'un événement.[/dim]")


def _enter_category(explorer, cat: CategoryInfo) -> list:
    """Entre dans une categorie. Si elle a des sous-cats, les affiche. Sinon, fetch events."""
    global _explore_categories, _explore_events, _explore_level, _explore_parent_cat

    subcats = explorer.get_subcategories(cat.id)
    if subcats:
        _explore_categories = subcats
        _explore_level = "subcategories"
        _explore_parent_cat = cat
        _explore_events = []
        _display_subcategories(subcats, cat)
        return []

    # Pas de sous-categories → fetch events directement
    return _fetch_and_display_events(explorer, cat.slug, cat.label)


def _fetch_and_display_events(explorer, slug: str, label: str) -> list:
    """Fetch events d'un slug et les affiche."""
    global _explore_events, _explore_level
    with console.status(f"[bold magenta]{label}...[/bold magenta]"):
        events = explorer.get_events_by_category(slug, limit=20)
    if events:
        _explore_events = events
        _explore_level = "events"
        navi_say(f"[cyan]{label}[/cyan] — {len(events)} événements")
        _display_events(events, title=label)
    else:
        navi_say(f"Aucun événement actif dans {label}.")
    return []


def _fetch_all_subcategory_markets(explorer, subcats: list[CategoryInfo], parent: CategoryInfo) -> list:
    """Fetch tous les marches vivants de toutes les sous-categories en parallele."""
    from concurrent.futures import ThreadPoolExecutor

    with console.status(f"[bold magenta]Chargement de tous les {parent.label}...[/bold magenta]"):
        def fetch_one(cat):
            return (cat, explorer.get_events_by_category(cat.slug, limit=10))
        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(fetch_one, subcats))

    all_markets = []
    for _cat, events in results:
        for ev in events:
            all_markets.extend(ev.markets)

    live = _filter_live_markets(all_markets)
    # Dedup par condition_id (un marche peut apparaitre dans plusieurs sous-cats)
    seen = set()
    unique = []
    for m in live:
        if m.condition_id not in seen:
            seen.add(m.condition_id)
            unique.append(m)

    unique.sort(key=lambda x: x.volume, reverse=True)
    markets = unique

    if markets:
        display_market_views(markets, title=f"Tous les {parent.label}")
        navi_say(f"{len(unique)} marchés actifs dans {parent.label} (top 20 par volume)")
    else:
        navi_say(f"Aucun marché actif dans {parent.label}.")
    return markets


def _enter_event(ev) -> list:
    """Entre dans un event → affiche ses marches vivants."""
    live = _filter_live_markets(ev.markets)
    navi_say(f"[cyan]{ev.title}[/cyan] — {len(live)} marchés actifs")
    if live:
        display_market_views(live, title=ev.title)
        return live
    else:
        navi_say("Aucun marché actif dans cet événement.")
    return []


def handle_explore(query: str = None):
    """Explore Polymarket : Categories -> Sous-categories -> Events -> Markets."""
    global _explore_categories, _explore_events, _explore_level, _explore_parent_cat
    try:
        from explorer import get_explorer
        explorer = get_explorer()

        if query:
            parts = query.split(None, 1)
            first = parts[0]

            # --- "explore N" (chiffre seul) ---
            if first.isdigit() and len(parts) == 1:
                idx = int(first)

                # Depuis events → entrer dans event #N
                if _explore_level == "events" and _explore_events:
                    if 1 <= idx <= len(_explore_events):
                        return _enter_event(_explore_events[idx - 1])
                    console.print(f"[red]Numéro invalide (1-{len(_explore_events)}).[/red]")
                    return []

                # Depuis sous-categories → 0 = tous (groupes), N = sous-cat
                if _explore_level == "subcategories" and _explore_categories:
                    if idx == 0 and _explore_parent_cat:
                        return _fetch_all_subcategory_markets(explorer, _explore_categories, _explore_parent_cat)
                    if 1 <= idx <= len(_explore_categories):
                        subcat = _explore_categories[idx - 1]
                        return _fetch_and_display_events(explorer, subcat.slug, subcat.label)
                    console.print(f"[red]Numéro invalide (0-{len(_explore_categories)}).[/red]")
                    return []

                # Depuis categories top-level → entrer dans cat #N
                if _explore_level == "categories" and _explore_categories:
                    if 1 <= idx <= len(_explore_categories):
                        return _enter_category(explorer, _explore_categories[idx - 1])
                    console.print(f"[red]Numéro invalide (1-{len(_explore_categories)}).[/red]")
                    return []

                navi_say("Tape [cyan]explore[/cyan] d'abord pour voir les catégories.")
                return []

            # --- "explore sports 2" (categorie + numero) ---
            if len(parts) == 2 and parts[1].isdigit():
                cat_name = parts[0]
                sub_idx = int(parts[1])
                cat = _find_category(explorer, cat_name)
                if cat:
                    # Entrer dans la categorie puis choisir le #N
                    subcats = explorer.get_subcategories(cat.id)
                    if subcats:
                        _explore_categories = subcats
                        _explore_level = "subcategories"
                        _explore_parent_cat = cat
                        if sub_idx == 0:
                            return _fetch_all_subcategory_markets(explorer, subcats, cat)
                        if 1 <= sub_idx <= len(subcats):
                            sc = subcats[sub_idx - 1]
                            return _fetch_and_display_events(explorer, sc.slug, sc.label)
                        console.print(f"[red]Numéro invalide (0-{len(subcats)}).[/red]")
                    else:
                        # Pas de sous-cats → le chiffre est un event index
                        with console.status(f"[bold magenta]{cat.label}...[/bold magenta]"):
                            events = explorer.get_events_by_category(cat.slug, limit=20)
                        if events:
                            _explore_events = events
                            _explore_level = "events"
                            if 1 <= sub_idx <= len(events):
                                return _enter_event(events[sub_idx - 1])
                            console.print(f"[red]Numéro invalide (1-{len(events)}).[/red]")
                        else:
                            navi_say(f"Aucun événement actif dans {cat.label}.")
                else:
                    navi_say(f"Catégorie '{cat_name}' non trouvée.")
                return []

            # --- "explore sports" (mot-cle) ---
            cat = _find_category(explorer, query)
            if cat:
                return _enter_category(explorer, cat)

            # Fallback : chercher dans les events
            with console.status(f"[bold magenta]Explore '{query}'...[/bold magenta]"):
                events = explorer.search_events(query, limit=10)

            if events:
                _explore_events = events
                _explore_level = "events"
                if len(events) == 1:
                    return _enter_event(events[0])
                navi_say(f"{len(events)} événements pour '{query}' :")
                _display_events(events, title=f"Résultats — '{query}'")
            else:
                # Fallback : recherche dans les marches
                with console.status(f"[bold magenta]Recherche '{query}'...[/bold magenta]"):
                    markets = _filter_live_markets(explorer.search(query, limit=20))
                if markets:
                    display_market_views(markets, title=f"Résultats — '{query}'")
                    return markets
                else:
                    navi_say(f"Rien trouvé pour '{query}'.")
        else:
            # "explore" sans argument → afficher les categories top-level
            with console.status("[bold magenta]Chargement des catégories...[/bold magenta]"):
                categories = explorer.get_categories(top_level_only=True)
            if categories:
                _explore_categories = categories
                _explore_level = "categories"
                _explore_events = []
                _explore_parent_cat = None
                _display_categories(categories)
            else:
                navi_say("Impossible de charger les catégories.")

    except ImportError:
        navi_say("Module explorer non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")

    return []


def _find_category(explorer, name: str) -> CategoryInfo | None:
    """Cherche une categorie par nom/slug dans toutes les categories (top + sub)."""
    all_cats = explorer.get_categories(top_level_only=False)
    name_low = name.lower()
    # Match exact
    for cat in all_cats:
        if name_low == cat.slug.lower() or name_low == cat.label.lower():
            return cat
    # Match partiel
    for cat in all_cats:
        if name_low in cat.slug.lower() or name_low in cat.label.lower():
            return cat
    return None


def handle_search(query: str):
    """Recherche libre. Retourne list[MarketView]."""
    try:
        from explorer import get_explorer
        explorer = get_explorer()
        with console.status(f'[bold magenta]Cherche "{query}"...[/bold magenta]'):
            markets = _filter_live_markets(explorer.search(query))
        if markets:
            display_market_views(markets, title=f"Résultats — '{query}'")
        return markets or []
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")
        return []


def handle_hot():
    """Marchés les plus actifs. Retourne list[MarketView]."""
    try:
        from explorer import get_explorer
        explorer = get_explorer()
        with console.status("[bold magenta]Marchés les plus chauds...[/bold magenta]"):
            markets = _filter_live_markets(explorer.get_hot())
        if markets:
            display_market_views(markets, title="Hot 🔥")
        return markets or []
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")
        return []


def handle_new():
    """Marchés les plus récents. Retourne list[MarketView]."""
    try:
        from explorer import get_explorer
        explorer = get_explorer()
        with console.status("[bold magenta]Dernières nouveautés...[/bold magenta]"):
            markets = _filter_live_markets(explorer.get_new())
        if markets:
            display_market_views(markets, title="Nouveaux ✨")
        return markets or []
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")
        return []


def handle_portfolio(trader: Trader):
    """Affiche le portfolio."""
    try:
        from portfolio import get_portfolio
        pf = get_portfolio(trader)
        pf.display_portfolio()
    except ImportError:
        navi_say("Module portfolio non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_sell(trader: Trader, idx: int):
    """Flux de vente d'une position."""
    try:
        from portfolio import get_portfolio
        pf = get_portfolio(trader)
        pos = pf.propose_sell(idx)
        if not pos:
            return

        price = FloatPrompt.ask("Prix de vente", default=pos.current_price)
        size = FloatPrompt.ask("Shares à vendre", default=pos.size)

        if not Confirm.ask("[bold]Confirmer la vente ?[/bold]", default=False):
            navi_quip("buy_cancel")
            return

        if not trader.connected:
            with console.status("[bold magenta]Connexion...[/bold magenta]"):
                if not trader.connect():
                    return

        with console.status("[bold magenta]Vente en cours...[/bold magenta]"):
            trader.execute_sell_position(
                token_id=pos.token_id,
                size=size,
                price=price,
                tick_size=pos.tick_size,
                neg_risk=pos.neg_risk,
                market_question=pos.market_question,
            )

    except ImportError:
        navi_say("Module portfolio non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_orders(trader: Trader):
    """Affiche les ordres ouverts."""
    if not trader.connected:
        with console.status("[bold magenta]Connexion...[/bold magenta]"):
            if not trader.connect():
                return

    with console.status("[bold magenta]Chargement des ordres...[/bold magenta]"):
        orders = trader.get_open_orders()

    if not orders:
        navi_say("Aucun ordre en attente.")
        return

    table = Table(title="📋 Ordres en attente")
    table.add_column("#", width=3)
    table.add_column("ID", max_width=16)
    table.add_column("Side", width=5)
    table.add_column("Prix", justify="right")
    table.add_column("Size", justify="right")
    table.add_column("Status")

    for i, o in enumerate(orders, 1):
        oid = o.get("id", "?")
        table.add_row(
            str(i),
            oid[:16] + "...",
            o.get("side", "?"),
            f"${float(o.get('price', 0)):.3f}",
            str(o.get("original_size", o.get("size", "?"))),
            o.get("status", "?"),
        )

    console.print(table)


def handle_cancel(trader: Trader):
    """Annule des ordres."""
    if not trader.connected:
        with console.status("[bold magenta]Connexion...[/bold magenta]"):
            if not trader.connect():
                return

    choice = Prompt.ask("Annuler [a]un ordre ou [t]ous ?", choices=["a", "t"], default="a")
    if choice == "t":
        if Confirm.ask("Annuler TOUS les ordres ?", default=False):
            trader.cancel_all_orders()
    else:
        order_id = Prompt.ask("Order ID à annuler")
        trader.cancel_order(order_id)


def handle_auto(trader: Trader):
    """Mode surveillance automatique."""
    console.print(Panel(
        f"🔄 Mode AUTO — Scan toutes les {SCAN_INTERVAL_SECONDS}s\n"
        f"Seuil: score >= {MIN_CONFIDENCE_SCORE}  ·  Ctrl+C pour stop",
        title="Auto Mode",
        border_style="yellow",
    ))

    try:
        while True:
            opportunities = handle_scan()
            if opportunities:
                display_opportunities(opportunities)
            good = [o for o in opportunities if o.confidence_score >= MIN_CONFIDENCE_SCORE]

            if good:
                navi_quip("scan_found", n=len(good))
                if Confirm.ask("Acheter ?", default=False):
                    idx_str = Prompt.ask("Numéro")
                    try:
                        idx = int(idx_str)
                        if 1 <= idx <= len(good):
                            _execute_buy_flow(trader, good[idx - 1])
                    except ValueError:
                        pass

            console.print(f"\n[dim]Prochain scan dans {SCAN_INTERVAL_SECONDS}s...[/dim]")
            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        console.print("\n[yellow]Auto mode arrêté.[/yellow]")


def handle_test():
    """Test read-only de l'API."""
    try:
        from scanner import get_midpoint, parse_prices, parse_token_ids
        import requests
        from config import GAMMA_API

        with console.status("[bold magenta]Test de connexion...[/bold magenta]"):
            resp = requests.get(f"{GAMMA_API}/markets", params={"limit": 3}, timeout=10)
            resp.raise_for_status()
            markets_data = resp.json()

        console.print(f"[green]✓ Gamma API — {len(markets_data)} marchés[/green]")

        for m_data in markets_data:
            question = m_data.get("question", "?")[:60]
            prices = parse_prices(m_data)
            token_ids = parse_token_ids(m_data)
            prices_str = ", ".join(f"{p:.3f}" for p in prices) if prices else "N/A"
            console.print(f"  · {question}")
            console.print(f"    Prix: [{prices_str}]")

            if token_ids:
                try:
                    mid = get_midpoint(token_ids[0])
                    console.print(f"    CLOB midpoint: ${mid:.3f}")
                except Exception:
                    console.print("    [dim]CLOB midpoint: N/A[/dim]")

        try:
            from navi import get_navi
            nav = get_navi()
            if nav.available:
                quota = nav.quota_status()
                console.print(f"[green]✓ Navi — {quota['remaining']}/{quota['limit']} appels[/green]")
            else:
                console.print("[yellow]⚠ Navi indisponible[/yellow]")
        except Exception:
            console.print("[yellow]⚠ Navi non testable[/yellow]")

        navi_say("Tout roule ! Prêt à chasser. 💎")

    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_dashboard():
    """Sheikah Slate."""
    try:
        from mapem_integration import show_performance_dashboard
        show_performance_dashboard(console)
    except ImportError:
        navi_say("Module MAPEM non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_accuracy():
    """Stats par catégorie/stratégie."""
    try:
        from learner import get_learner
        from mapem_integration import category_short

        learner = get_learner()

        cat_stats = learner.accuracy_by_category()
        if cat_stats:
            table = Table(title="📈 Par catégorie", border_style="cyan")
            table.add_column("Cat.", width=6)
            table.add_column("Trades", justify="right", width=7)
            table.add_column("Résolus", justify="right", width=8)
            table.add_column("Win %", justify="right", width=7)
            table.add_column("PnL", justify="right", width=8)

            for cat, data in cat_stats.items():
                wr = data.get("win_rate", 0)
                pnl = data.get("total_pnl", 0)
                wr_color = "green" if wr >= 0.5 else "red" if wr < 0.4 else "yellow"
                pnl_color = "green" if pnl >= 0 else "red"
                table.add_row(
                    category_short(cat),
                    str(data.get("count", 0)),
                    str(data.get("resolved", 0)),
                    f"[{wr_color}]{wr:.0%}[/{wr_color}]",
                    f"[{pnl_color}]${pnl:+.2f}[/{pnl_color}]",
                )
            console.print(table)
        else:
            navi_say("Pas encore assez de trades pour des stats.")

        strat_stats = learner.accuracy_by_strategy()
        if strat_stats:
            table = Table(title="📈 Par stratégie", border_style="cyan")
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

    except ImportError:
        navi_say("Module learner non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_streak():
    """Série en cours."""
    try:
        from learner import get_learner
        streak_type, count = get_learner().get_streak()

        if streak_type == "none" or count == 0:
            navi_say("Pas encore de série. Fais des trades !")
        elif streak_type == "win":
            navi_say(f"🔥 [bold green]{count} victoire(s)[/bold green] d'affilée !")
        else:
            navi_say(f"😤 [bold red]{count} défaite(s)[/bold red] d'affilée. Prends du recul.")

    except ImportError:
        navi_say("Module learner non disponible.")


def handle_history():
    """Trades récents."""
    try:
        from learner import get_learner
        trades = get_learner().get_recent_trades(10)

        if not trades:
            navi_say("Aucun trade enregistré.")
            return

        table = Table(title="📜 Trades récents", border_style="cyan")
        table.add_column("#", width=3)
        table.add_column("Date", width=12)
        table.add_column("Marché", max_width=30)
        table.add_column("Side", width=5)
        table.add_column("Prix", justify="right", width=7)
        table.add_column("$", justify="right", width=7)
        table.add_column("PnL", justify="right", width=8)

        for i, t in enumerate(trades, 1):
            ts = t.get("timestamp", "")[:10]
            q = t.get("market_question", "?")[:28].replace("[", "\\[")
            side = t.get("side", "?")
            price = t.get("price", 0)
            amount = t.get("amount", 0)
            pnl = t.get("profit_loss", 0)
            resolved = t.get("resolved", False)

            pnl_str = "[dim]en cours[/dim]"
            if resolved:
                pnl_color = "green" if pnl > 0 else "red" if pnl < 0 else "dim"
                pnl_str = f"[{pnl_color}]${pnl:+.2f}[/{pnl_color}]"

            side_color = "green" if side == "BUY" else "red"
            table.add_row(
                str(i), ts, q,
                f"[{side_color}]{side}[/{side_color}]",
                f"${price:.3f}", f"${amount:.2f}", pnl_str,
            )

        console.print(table)

    except ImportError:
        navi_say("Module learner non disponible.")
    except Exception as e:
        navi_quip("error")
        console.print(f"[dim]{e}[/dim]")


def handle_setup_keychain():
    """Migration Keychain."""
    try:
        from keychain import setup_keychain
        setup_keychain()
    except Exception as e:
        console.print(f"[red]Erreur: {e}[/red]")


def handle_help():
    """Aide complète avec explications détaillées."""
    help_text = (
        "[bold green]🗡️ AIDE — RUPEEHUNTER v3.0[/bold green]\n\n"

        "[bold]🔍 Scanner (Lens of Truth)[/bold]\n"
        "  [cyan]Scan[/cyan] — Cherche des opportunités sur ~200 marchés\n"
        "  [cyan]Scan 6h[/cyan] — Uniquement les marchés qui ferment dans les 6h\n"
        "  [cyan]Scan soir[/cyan] — Marchés qui ferment dans les 16h (alias: t, tonight)\n\n"

        "[bold]🔭 Explorer[/bold]\n"
        "  [cyan]Explore[/cyan] — Voir toutes les catégories (crypto, politics...)\n"
        "  [cyan]Explore crypto[/cyan] — Marchés d'une catégorie spécifique\n"
        "  [cyan]Search trump[/cyan] — Recherche libre par mot-clé\n"
        "  [cyan]Hot[/cyan] — Marchés les plus actifs (gros volume)\n"
        "  [cyan]New[/cyan] — Marchés les plus récents\n\n"

        "[bold]💰 Trading[/bold]\n"
        "  [cyan]Buy 3[/cyan] — Acheter l'opportunité #3 (marche après Scan, Search, Hot, New !)\n"
        "  [cyan]Sell 2[/cyan] — Vendre la position #2 de ton portfolio\n"
        "  [cyan]Info 2[/cyan] — Détails complets : prix, volume, carnet d'ordres\n"
        "  [cyan]Orders[/cyan] — Voir tes ordres en attente\n"
        "  [cyan]Cancel[/cyan] — Annuler un ou tous les ordres\n\n"

        "[bold]🧚 Navi (gratuit via Claude Max)[/bold]\n"
        "  [cyan]Avis[/cyan] — Navi analyse le top 5 en batch\n"
        "  [cyan]Avis 4[/cyan] — Navi analyse une opportunité spécifique\n"
        "  Navi donne un verdict (GO / PIEGE / INCERTAIN) + sa probabilité estimée\n\n"

        "[bold]📝 Expertise humaine[/bold]\n"
        "  [cyan]Note 3 je connais ce dossier[/cyan] — Ajoute ta note, Navi re-score\n"
        "  [cyan]Boost 3[/cyan] — +15 au score humain (raccourci 'je suis confiant')\n"
        "  [cyan]Flag 3[/cyan] — -20 au score humain (raccourci 'c'est un piège')\n"
        "  Le score final = 35% scanner + 65% MAPEM + ton ajustement humain\n\n"

        "[bold]📊 Performance (Sheikah Slate)[/bold]\n"
        "  [cyan]Portfolio[/cyan] / [cyan]PF[/cyan] — Tes positions actuelles + PnL en temps réel\n"
        "  [cyan]Dashboard[/cyan] — Vue d'ensemble de ta performance globale\n"
        "  [cyan]Accuracy[/cyan] — Win rate par catégorie et par stratégie\n"
        "  [cyan]Streak[/cyan] — Ta série de victoires/défaites en cours\n"
        "  [cyan]History[/cyan] — Tes 10 derniers trades\n\n"

        "[bold]Navigation[/bold]\n"
        "  [cyan]N[/cyan] / [cyan]P[/cyan] — Page suivante/précédente (après Scan)\n"
        "  [cyan]?[/cyan] — Cette aide  ·  [cyan]Menu[/cyan] — Menu rapide\n"
        "  [cyan]Q[/cyan] — Quitter\n\n"

        "[bold yellow]⚠️  Tu peux PERDRE 100% de ta mise.\n"
        "Les scores sont des indicateurs, pas des garanties.[/bold yellow]"
    )
    console.print(Panel(help_text, border_style="green", padding=(1, 2)))


# ─────────────────────────────────────────────────────────
# Bridge scan ↔ search
# ─────────────────────────────────────────────────────────

def _resolve_opportunity(idx: int, opportunities: list, market_results: list,
                         active_list: str):
    """Résout un numéro en Opportunity, peu importe la source active."""
    if active_list == "scan":
        if not opportunities:
            navi_say("Fais un [cyan]Scan[/cyan] d'abord !")
            return None
        if idx < 1 or idx > len(opportunities):
            console.print(f"[red]Numéro invalide (1-{len(opportunities)}).[/red]")
            return None
        return opportunities[idx - 1]

    elif active_list in ("search", "explore", "hot", "new"):
        if not market_results:
            navi_say("Aucun résultat actif.")
            return None
        if idx < 1 or idx > len(market_results):
            limit = len(market_results)
            console.print(f"[red]Numéro invalide (1-{limit}).[/red]")
            return None
        return market_view_to_opportunity(market_results[idx - 1])

    else:
        navi_say("Fais un [cyan]Scan[/cyan] ou [cyan]Search[/cyan] d'abord !")
        return None


# ─────────────────────────────────────────────────────────
# Prompt contextuel
# ─────────────────────────────────────────────────────────

def get_prompt(active_list: str, count: int) -> str:
    """Retourne le prompt minimal contextuel."""
    if active_list == "scan" and count > 0:
        return f"[magenta]🧚[/magenta] [dim]{count} trésors · Buy/Avis/Info N · ? aide[/dim]"
    elif active_list in ("search", "explore", "hot", "new") and count > 0:
        return f"[magenta]🧚[/magenta] [dim]{count} trouvés · Buy/Info N[/dim]"
    elif active_list == "portfolio":
        return "[magenta]🧚[/magenta] [dim]Sell N · ? aide[/dim]"
    return "[magenta]🧚[/magenta]"


# ─────────────────────────────────────────────────────────
# Boucle principale
# ─────────────────────────────────────────────────────────

def main():
    trader = Trader()
    with console.status("[bold magenta]Connexion au royaume d'Hyrule...[/bold magenta]"):
        trader.connect()
    balance = trader.get_usdc_balance() if trader.connected else None

    show_banner(balance)
    show_menu()

    opportunities: list[Opportunity] = []
    market_results: list[MarketView] = []
    active_list = "none"
    current_page = 0
    total_pages = 0

    while True:
        try:
            # Idle quip (15% chance, seulement quand rien d'actif)
            if active_list == "none" and random.random() < 0.15:
                console.print(f"[dim]{random.choice(NAVI_LINES['idle'])}[/dim]")

            # Prompt contextuel
            if active_list == "scan":
                count = len(opportunities)
            elif active_list in ("search", "explore", "hot", "new"):
                count = len(market_results)
            else:
                count = 0

            prompt_text = get_prompt(active_list, count)
            raw = Prompt.ask(prompt_text)
            cmd, arg = parse_command(raw, has_results=bool(opportunities or market_results), context=active_list)

            if cmd == "noop":
                continue

            elif cmd == "quit":
                navi_quip("quit")
                sys.exit(0)

            elif cmd == "help":
                handle_help()

            elif cmd == "menu":
                show_menu()

            elif cmd == "scan":
                opportunities = handle_scan()
                active_list = "scan"
                current_page = 0
                if opportunities:
                    _, total_pages = display_opportunities(opportunities, current_page)
                    navi_quip("scan_found", n=len(opportunities))
                else:
                    navi_quip("scan_empty")

            elif cmd == "scan_hours":
                opportunities = handle_scan(max_hours=arg)
                active_list = "scan"
                current_page = 0
                if opportunities:
                    _, total_pages = display_opportunities(opportunities, current_page)
                    navi_quip("scan_found", n=len(opportunities))
                else:
                    navi_say(f"Aucun marché ≤{arg}h. Essaie 'Scan 12h' ou 'Scan'.")

            elif cmd == "explore":
                result = handle_explore(arg)
                if result:
                    market_results = result
                    active_list = "explore"

            elif cmd == "search":
                result = handle_search(arg)
                if result:
                    market_results = result
                    active_list = "search"
                    navi_quip("search_found", n=len(result))
                else:
                    navi_quip("search_empty")

            elif cmd == "hot":
                result = handle_hot()
                if result:
                    market_results = result
                    active_list = "hot"
                    navi_quip("search_found", n=len(result))

            elif cmd == "new":
                result = handle_new()
                if result:
                    market_results = result
                    active_list = "new"
                    navi_quip("search_found", n=len(result))

            elif cmd == "next_page":
                if active_list == "scan" and opportunities:
                    if current_page < total_pages - 1:
                        current_page += 1
                        display_opportunities(opportunities, current_page)
                    else:
                        console.print("[dim]Dernière page.[/dim]")
                else:
                    navi_say("Pagination dispo après un [cyan]Scan[/cyan].")

            elif cmd == "prev_page":
                if active_list == "scan" and opportunities:
                    if current_page > 0:
                        current_page -= 1
                        display_opportunities(opportunities, current_page)
                    else:
                        console.print("[dim]Première page.[/dim]")
                else:
                    navi_say("Pagination dispo après un [cyan]Scan[/cyan].")

            elif cmd == "buy":
                opp = _resolve_opportunity(arg, opportunities, market_results, active_list)
                if opp:
                    _execute_buy_flow(trader, opp)

            elif cmd == "sell":
                handle_sell(trader, arg)

            elif cmd == "info":
                opp = _resolve_opportunity(arg, opportunities, market_results, active_list)
                if opp:
                    handle_info(opp)

            elif cmd == "avis":
                if active_list in ("search", "explore", "hot", "new") and market_results:
                    temp_opps = [market_view_to_opportunity(mv)
                                 for mv in market_results]
                    handle_avis(temp_opps, idx=arg)
                else:
                    handle_avis(opportunities, idx=arg)

            elif cmd == "note":
                if isinstance(arg, tuple) and len(arg) == 2:
                    handle_note(opportunities, arg[0], arg[1])

            elif cmd == "boost":
                handle_boost(opportunities, arg)

            elif cmd == "flag":
                handle_flag(opportunities, arg)

            elif cmd == "portfolio":
                handle_portfolio(trader)
                active_list = "portfolio"

            elif cmd == "mapem":
                if active_list in ("search", "explore", "hot", "new") and market_results:
                    temp_opps = [market_view_to_opportunity(mv)
                                 for mv in market_results]
                    handle_avis(temp_opps, idx=arg)
                else:
                    handle_avis(opportunities, idx=arg)

            elif cmd == "orders":
                handle_orders(trader)

            elif cmd == "cancel":
                handle_cancel(trader)

            elif cmd == "auto":
                handle_auto(trader)

            elif cmd == "test":
                handle_test()

            elif cmd == "dashboard":
                handle_dashboard()

            elif cmd == "accuracy":
                handle_accuracy()

            elif cmd == "streak":
                handle_streak()

            elif cmd == "history":
                handle_history()

            elif cmd == "setup_keychain":
                handle_setup_keychain()

            else:
                navi_quip("unknown_cmd")

        except KeyboardInterrupt:
            console.print("\n[dim]Ctrl+C — retour[/dim]")
        except Exception as e:
            navi_quip("error")
            console.print(f"[dim]{e}[/dim]")


if __name__ == "__main__":
    main()
