#!/usr/bin/env python3
"""
Bot Polymarket v2.0 — Interface conversationnelle semi-automatique
"""

import re
import sys
import time
import math
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich.prompt import Prompt, Confirm, FloatPrompt
from rich import box

from config import (
    MAX_PER_TRADE, MIN_CONFIDENCE_SCORE,
    SCAN_INTERVAL_SECONDS,
)
from scanner import scan_all, Opportunity
from trader import Trader

console = Console()

PAGE_SIZE = 8

# ─────────────────────────────────────────────────────────
# Palette de couleurs
# ─────────────────────────────────────────────────────────
C_ACCENT = "bright_cyan"
C_ACCENT2 = "deep_sky_blue1"
C_GOLD = "gold1"
C_SUCCESS = "green"
C_DANGER = "red"
C_WARN = "yellow"
C_DIM = "bright_black"
C_MUTED = "grey62"

# Mapping stratégie → couleur + label
STRATEGY_STYLE = {
    "near_resolution": ("bold bright_yellow on grey11", " NEAR-RES "),
    "spread_arb":      ("bold bright_cyan on grey11",   " ARB "),
    "wide_spread":     ("bold bright_magenta on grey11", " SPREAD "),
    "momentum":        ("bold bright_green on grey11",   " MOMENTUM "),
}


def _score_bar(value: int, width: int = 10) -> str:
    """Render a compact visual score bar: ████░░░░░░ 72"""
    filled = round(value / 100 * width)
    empty = width - filled
    if value >= 70:
        color = C_SUCCESS
    elif value >= 50:
        color = C_WARN
    else:
        color = C_DANGER
    bar = f"[{color}]{'█' * filled}[/{color}][{C_DIM}]{'░' * empty}[/{C_DIM}]"
    return f"{bar} [{color}]{value}[/{color}]"


def _strategy_badge(strategy: str) -> str:
    """Render a colored strategy badge."""
    style, label = STRATEGY_STYLE.get(strategy, ("bold white on grey11", f" {strategy.upper()} "))
    return f"[{style}]{label}[/{style}]"


# ─────────────────────────────────────────────────────────
# Affichage
# ─────────────────────────────────────────────────────────

def show_banner(balance=None):
    bal_str = f"[bold {C_GOLD}]${balance:.2f}[/bold {C_GOLD}]" if balance is not None else f"[{C_WARN}]connexion requise[/{C_WARN}]"

    logo = (
        f"[bold {C_ACCENT}]"
        "  ██████╗  ██████╗ ██╗  ██╗   ██╗███╗   ███╗ █████╗ ██████╗ ██╗  ██╗███████╗████████╗\n"
        "  ██╔══██╗██╔═══██╗██║  ╚██╗ ██╔╝████╗ ████║██╔══██╗██╔══██╗██║ ██╔╝██╔════╝╚══██╔══╝\n"
        f"[/bold {C_ACCENT}]"
        f"[bold {C_ACCENT2}]"
        "  ██████╔╝██║   ██║██║   ╚████╔╝ ██╔████╔██║███████║██████╔╝█████╔╝ █████╗     ██║   \n"
        "  ██╔═══╝ ██║   ██║██║    ╚██╔╝  ██║╚██╔╝██║██╔══██║██╔══██╗██╔═██╗ ██╔══╝     ██║   \n"
        f"[/bold {C_ACCENT2}]"
        f"[bold {C_ACCENT}]"
        "  ██║     ╚██████╔╝███████╗██║   ██║ ╚═╝ ██║██║  ██║██║  ██║██║  ██╗███████╗   ██║   \n"
        "  ╚═╝      ╚═════╝ ╚══════╝╚═╝   ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝   ╚═╝   \n"
        f"[/bold {C_ACCENT}]"
    )

    status_line = (
        f"  [{C_MUTED}]Solde[/{C_MUTED}] {bal_str} [{C_MUTED}]USDC[/{C_MUTED}]"
        f"  [{C_DIM}]│[/{C_DIM}]  "
        f"[{C_MUTED}]Max/trade[/{C_MUTED}] [{C_ACCENT}]${MAX_PER_TRADE:.2f}[/{C_ACCENT}]"
        f"  [{C_DIM}]│[/{C_DIM}]  "
        f"[{C_MUTED}]Mode[/{C_MUTED}] [{C_ACCENT}]Semi-auto[/{C_ACCENT}]"
    )

    console.print()
    console.print(Panel(
        f"{logo}\n{status_line}",
        border_style=C_ACCENT,
        box=box.DOUBLE,
        subtitle=f"[{C_DIM}]v2.0 — Trading Bot[/{C_DIM}]",
        subtitle_align="right",
        padding=(0, 1),
    ))


def show_menu():
    scan_cmds = (
        f"  [{C_ACCENT}]Scan[/{C_ACCENT}]          [{C_DIM}]Chercher des opportunités[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Scan 6h[/{C_ACCENT}]       [{C_DIM}]Marchés < 6 heures[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Scan soir[/{C_ACCENT}]     [{C_DIM}]Marchés du soir (16h)[/{C_DIM}]"
    )

    trade_cmds = (
        f"  [{C_ACCENT}]Buy N[/{C_ACCENT}]         [{C_DIM}]Acheter l'opportunité #N[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Info N[/{C_ACCENT}]        [{C_DIM}]Détails + carnet d'ordres[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Avis[/{C_ACCENT}]          [{C_DIM}]Screening Claude top 3[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Avis N[/{C_ACCENT}]        [{C_DIM}]Screening Claude sur #N[/{C_DIM}]"
    )

    manage_cmds = (
        f"  [{C_ACCENT}]Orders[/{C_ACCENT}]        [{C_DIM}]Ordres en attente[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Cancel[/{C_ACCENT}]        [{C_DIM}]Annuler des ordres[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Dashboard[/{C_ACCENT}]     [{C_DIM}]Performance MAPEM[/{C_DIM}]\n"
        f"  [{C_ACCENT}]Setup[/{C_ACCENT}]         [{C_DIM}]Keychain macOS[/{C_DIM}]"
    )

    menu_content = (
        f"[bold {C_GOLD}]  SCAN[/bold {C_GOLD}]\n"
        f"{scan_cmds}\n\n"
        f"[bold {C_GOLD}]  TRADE[/bold {C_GOLD}]\n"
        f"{trade_cmds}\n\n"
        f"[bold {C_GOLD}]  GESTION[/bold {C_GOLD}]\n"
        f"{manage_cmds}\n\n"
        f"  [{C_ACCENT}]?[/{C_ACCENT}] [{C_DIM}]Aide[/{C_DIM}]"
        f"    [{C_ACCENT}]Q[/{C_ACCENT}] [{C_DIM}]Quitter[/{C_DIM}]"
    )

    console.print(Panel(
        menu_content,
        title=f"[bold {C_GOLD}]  Commandes  [/bold {C_GOLD}]",
        border_style=C_DIM,
        box=box.ROUNDED,
        padding=(1, 2),
    ))


def display_opportunities(opportunities: list[Opportunity], page: int = 0):
    """Affiche les opportunités en format liste avec pagination.
    Retourne (visible_list, total_pages).
    """
    if not opportunities:
        console.print(f"\n  [{C_WARN}]Aucune opportunite trouvee.[/{C_WARN}]")
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

    # Header
    page_indicator = ""
    if total_pages > 1:
        dots = ""
        for p in range(total_pages):
            if p == page:
                dots += f"[{C_ACCENT}]●[/{C_ACCENT}]"
            else:
                dots += f"[{C_DIM}]○[/{C_DIM}]"
            if p < total_pages - 1:
                dots += " "
        page_indicator = f"  {dots}"

    console.print(f"\n  [bold {C_ACCENT}]{len(opportunities)}[/bold {C_ACCENT}] [{C_MUTED}]opportunites[/{C_MUTED}]{page_indicator}")
    console.print(f"  [{C_DIM}]{'─' * 72}[/{C_DIM}]")

    for i, opp in enumerate(visible, start + 1):
        display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score
        profit_color = C_SUCCESS if opp.profit_potential > 0.10 else C_WARN

        # Time indicator with urgency coloring
        if 0 < opp.hours_left < 1:
            time_str = f"[bold {C_DANGER}]{opp.hours_left * 60:.0f}min[/bold {C_DANGER}]"
        elif 0 < opp.hours_left < 6:
            time_str = f"[bold {C_WARN}]{opp.hours_left:.0f}h[/bold {C_WARN}]"
        elif 0 < opp.hours_left < 24:
            time_str = f"[{C_SUCCESS}]{opp.hours_left:.0f}h[/{C_SUCCESS}]"
        elif 0 < opp.hours_left < 168:
            time_str = f"[{C_MUTED}]{opp.hours_left / 24:.0f}j[/{C_MUTED}]"
        else:
            time_str = f"[{C_DIM}]—[/{C_DIM}]"

        cat_str = f"[{C_MUTED}]{category_short(opp.mapem_category)}[/{C_MUTED}]" if opp.mapem_category else ""
        safe_outcome = opp.outcome.replace("[", "\\[")
        safe_question = opp.market_question.replace("[", "\\[")

        # Line 1: Number + Score bar + Strategy badge + Time
        badge = _strategy_badge(opp.strategy)
        line1 = (
            f"  [bold {C_ACCENT}]#{i:<3}[/bold {C_ACCENT}]"
            f" {_score_bar(display_score, 8)}"
            f"  {badge}"
            f"  {cat_str}"
            f"  [{C_DIM}]│[/{C_DIM}] {time_str}"
        )
        console.print(line1)

        # Line 2: Market question
        console.print(f"       [{C_MUTED}]{safe_question}[/{C_MUTED}]")

        # Line 3: Outcome + Price + Profit
        line3 = (
            f"       [bold]{safe_outcome}[/bold] [{C_DIM}]@[/{C_DIM}] "
            f"[bold {C_ACCENT2}]${opp.current_price:.2f}[/bold {C_ACCENT2}]"
            f"  [{C_DIM}]→[/{C_DIM}]  "
            f"[bold {profit_color}]+{opp.profit_potential:.0%}[/bold {profit_color}]"
            f"  [{C_DIM}]│[/{C_DIM}]  "
            f"[{C_MUTED}]vol ${opp.volume_24h:,.0f}[/{C_MUTED}]"
        )
        console.print(line3)
        console.print()

    # Footer navigation
    console.print(f"  [{C_DIM}]{'─' * 72}[/{C_DIM}]")
    nav_parts = []
    if total_pages > 1:
        if page > 0:
            nav_parts.append(f"[{C_ACCENT}]P[/{C_ACCENT}] [{C_DIM}]precedente[/{C_DIM}]")
        if page < total_pages - 1:
            nav_parts.append(f"[{C_ACCENT}]N[/{C_ACCENT}] [{C_DIM}]suivante[/{C_DIM}]")
    nav_parts.append(f"[{C_ACCENT}]Buy N[/{C_ACCENT}] [{C_DIM}]/[/{C_DIM}] [{C_ACCENT}]Info N[/{C_ACCENT}] [{C_DIM}]/[/{C_DIM}] [{C_ACCENT}]Avis N[/{C_ACCENT}]")
    console.print(f"  {'  [{0}]│[/{0}]  '.format(C_DIM).join(nav_parts)}")

    return visible, total_pages


# ─────────────────────────────────────────────────────────
# Parser de commandes
# ─────────────────────────────────────────────────────────

def parse_command(text: str, has_scan: bool):
    """Parse l'entrée utilisateur et retourne (cmd, arg).
    arg est un int (index 1-based) ou None.
    """
    text = text.strip()
    if not text:
        return ("unknown", None)

    # Limiter la longueur pour éviter les inputs aberrants
    if len(text) > 200:
        return ("unknown", None)

    low = text.lower()

    # Quit
    if low in ("q", "quit", "exit", "quitter"):
        return ("quit", None)

    # Help
    if low in ("?", "help", "aide", "h"):
        return ("help", None)

    # Pagination
    if low in ("n", "next", "suite"):
        return ("next_page", None)
    if low in ("p", "prev", "retour", "précédent"):
        return ("prev_page", None)

    # Scan avec heures : "scan 3h", "scan 12h"
    m = re.match(r'^scan\s+(\d+)\s*h?$', low)
    if m:
        return ("scan_hours", int(m.group(1)))

    # Scan soir
    if low in ("scan soir", "soir", "t", "tonight"):
        return ("scan_hours", 16)

    # Scan
    if low in ("scan", "1", "s"):
        return ("scan", None)

    # Buy N  (index 1-based, rejette 0)
    m = re.match(r'^(?:buy|acheter)\s+([1-9]\d*)$', low)
    if m:
        return ("buy", int(m.group(1)))

    # Info N  (index 1-based, rejette 0)
    m = re.match(r'^(?:info|détail|detail|i)\s+([1-9]\d*)$', low)
    if m:
        return ("info", int(m.group(1)))

    # Avis N  (index 1-based, rejette 0)
    m = re.match(r'^(?:avis|a|claude)\s+([1-9]\d*)$', low)
    if m:
        return ("avis", int(m.group(1)))

    # Avis (batch top 3)
    if low in ("avis", "a", "claude"):
        return ("avis", None)

    # Mapem N  (index 1-based, rejette 0)
    m = re.match(r'^(?:mapem|m)\s+([1-9]\d*)$', low)
    if m:
        return ("mapem", int(m.group(1)))

    # Orders
    if low in ("orders", "ordres", "order"):
        return ("orders", None)

    # Cancel
    if low in ("cancel", "annuler"):
        return ("cancel", None)

    # Auto
    if low in ("auto",):
        return ("auto", None)

    # Test
    if low in ("test",):
        return ("test", None)

    # Dashboard
    if low in ("dashboard", "d", "dash"):
        return ("dashboard", None)

    # Setup keychain
    if low in ("setup", "setup keychain", "setup sécurité", "setup securite", "keychain"):
        return ("setup_keychain", None)

    # Nombre seul → buy N si scan actif
    if low.isdigit():
        num = int(low)
        if has_scan and num > 0:
            return ("buy", num)
        return ("unknown", None)

    return ("unknown", None)


# ─────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────

def handle_scan(max_hours=None):
    """Scan et retourne les opportunités."""
    if max_hours:
        label = f"marches < {max_hours}h"
    else:
        label = "tous les marches"
    console.print(f"\n  [{C_ACCENT}]Scanning[/{C_ACCENT}] [{C_DIM}]{label}...[/{C_DIM}]")
    try:
        opportunities = scan_all(max_hours=max_hours)
        if not opportunities and max_hours:
            console.print(f"\n  [{C_WARN}]Aucun marche ne ferme dans les {max_hours} prochaines heures.[/{C_WARN}]")
            console.print(f"  [{C_DIM}]Essaie Scan 12h ou Scan pour tout voir.[/{C_DIM}]")
        return opportunities
    except Exception as e:
        console.print(f"  [{C_DANGER}]Erreur scan: {e}[/{C_DANGER}]")
        return []


def handle_info(opp: Opportunity):
    """Affiche le détail complet d'une opportunité + carnet d'ordres live."""
    try:
        from mapem_integration import category_short
        cat = category_short(opp.mapem_category) if opp.mapem_category else "—"
    except ImportError:
        cat = opp.mapem_category or "—"

    display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score
    profit_color = C_SUCCESS if opp.profit_potential > 0.10 else C_WARN
    safe_question = opp.market_question.replace("[", "\\[")

    desc = opp.market_description.strip() if opp.market_description else ""
    safe_desc = desc.replace("[", "\\[") if desc else ""

    # Build info panel with structured sections
    sections = []

    # Title
    sections.append(f"[bold white]{safe_question}[/bold white]")
    if safe_desc:
        sections.append(f"\n[{C_MUTED}]{safe_desc}[/{C_MUTED}]")

    # Trade details as a mini table
    sections.append(f"\n[bold {C_GOLD}]  TRADE[/bold {C_GOLD}]")
    badge = _strategy_badge(opp.strategy)
    sections.append(f"  [{C_MUTED}]Strategie[/{C_MUTED}]     {badge}")
    sections.append(
        f"  [{C_MUTED}]Cote[/{C_MUTED}]          [bold]{opp.outcome.replace('[', chr(92) + '[')}[/bold] "
        f"[{C_DIM}]@[/{C_DIM}] [bold {C_ACCENT2}]${opp.current_price:.3f}[/bold {C_ACCENT2}] "
        f"[{C_DIM}]({opp.current_price:.0%})[/{C_DIM}]"
    )
    sections.append(
        f"  [{C_MUTED}]Estime[/{C_MUTED}]        "
        f"[bold]${opp.estimated_value:.3f}[/bold] [{C_DIM}]({opp.estimated_value:.0%})[/{C_DIM}]"
    )
    sections.append(f"  [{C_MUTED}]Profit[/{C_MUTED}]        [bold {profit_color}]+{opp.profit_potential:.1%}[/bold {profit_color}]")
    ep = opp.expected_profit_usd
    ep_color = C_SUCCESS if ep > 0 else C_DANGER
    sections.append(f"  [{C_MUTED}]E\\[P] sur $10[/{C_MUTED}]  [{ep_color}]${ep:+.2f}[/{ep_color}]")
    sections.append(f"  [{C_MUTED}]Volume 24h[/{C_MUTED}]    [bold]${opp.volume_24h:,.0f}[/bold]")
    sections.append(f"  [{C_MUTED}]Resolution[/{C_MUTED}]    {opp.hours_left:.0f}h")
    sections.append(f"  [{C_MUTED}]Categorie[/{C_MUTED}]     {cat}")

    # Scores section
    sections.append(f"\n[bold {C_GOLD}]  SCORES[/bold {C_GOLD}]")
    sections.append(f"  [{C_MUTED}]Scanner[/{C_MUTED}]       {_score_bar(opp.confidence_score, 12)}")
    if opp.mapem_score >= 0:
        sections.append(f"  [{C_MUTED}]MAPEM[/{C_MUTED}]         {_score_bar(opp.mapem_score, 12)}")
    sections.append(f"  [{C_MUTED}]Composite[/{C_MUTED}]     {_score_bar(display_score, 12)}")

    # Details
    sections.append(f"\n  [{C_DIM}]{opp.details}[/{C_DIM}]")

    console.print(Panel(
        "\n".join(sections),
        title=f"[bold {C_ACCENT}]  Details  [/bold {C_ACCENT}]",
        border_style=C_ACCENT,
        box=box.ROUNDED,
        padding=(1, 2),
    ))

    # Order book
    try:
        from scanner import get_order_book
        book = get_order_book(opp.token_id)
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if bids or asks:
            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 0
            bid_size = float(bids[0].get("size", 0)) if bids else 0
            ask_size = float(asks[0].get("size", 0)) if asks else 0
            spread = (best_ask - best_bid) if best_ask > best_bid else 0

            # Visual order book
            max_size = max(bid_size, ask_size, 1)
            bid_bar_len = int(bid_size / max_size * 20)
            ask_bar_len = int(ask_size / max_size * 20)

            book_content = (
                f"  [{C_SUCCESS}]BID[/{C_SUCCESS}]  ${best_bid:.3f}  "
                f"[{C_SUCCESS}]{'█' * bid_bar_len}[/{C_SUCCESS}][{C_DIM}]{'░' * (20 - bid_bar_len)}[/{C_DIM}]"
                f"  [{C_MUTED}]{bid_size:.0f} shares[/{C_MUTED}]\n"
                f"  [{C_DANGER}]ASK[/{C_DANGER}]  ${best_ask:.3f}  "
                f"[{C_DANGER}]{'█' * ask_bar_len}[/{C_DANGER}][{C_DIM}]{'░' * (20 - ask_bar_len)}[/{C_DIM}]"
                f"  [{C_MUTED}]{ask_size:.0f} shares[/{C_MUTED}]"
            )
            if best_ask > 0:
                spread_pct = spread / best_ask
                spread_color = C_SUCCESS if spread_pct < 0.03 else C_WARN if spread_pct < 0.10 else C_DANGER
                book_content += (
                    f"\n\n  [{C_MUTED}]Spread[/{C_MUTED}]  "
                    f"[{spread_color}]${spread:.3f}[/{spread_color}] "
                    f"[{C_DIM}]({spread_pct:.1%})[/{C_DIM}]"
                )

            console.print(Panel(
                book_content,
                title=f"[{C_ACCENT}]  Carnet d'ordres  [{C_DIM}]live[/{C_DIM}]  [/{C_ACCENT}]",
                border_style=C_DIM,
                box=box.ROUNDED,
                padding=(1, 1),
            ))
    except Exception:
        pass


def _execute_buy_flow(trader: Trader, opp: Opportunity):
    """Flux d'achat commun : montant, confirmation, exécution."""
    console.print()
    amount = FloatPrompt.ask(f"  [{C_ACCENT}]Montant[/{C_ACCENT}] [{C_DIM}]max ${MAX_PER_TRADE}[/{C_DIM}]", default=MAX_PER_TRADE)
    amount = min(amount, MAX_PER_TRADE)

    trader.propose_trade(opp, amount)

    order_type = Prompt.ask(f"  [{C_ACCENT}]Type d'ordre[/{C_ACCENT}]", choices=["market", "limit"], default="market")

    if not Confirm.ask(f"  [bold {C_WARN}]Confirmer ce trade ?[/bold {C_WARN}]", default=False):
        console.print(f"  [{C_WARN}]Trade annule.[/{C_WARN}]")
        return

    if not trader.connected:
        console.print(f"  [{C_DIM}]Connexion au CLOB...[/{C_DIM}]")
        if not trader.connect():
            return

    if order_type == "market":
        trader.execute_buy(opp, amount)
    else:
        price = FloatPrompt.ask(f"  [{C_ACCENT}]Prix limite[/{C_ACCENT}]", default=opp.current_price)
        trader.execute_limit_buy(opp, amount, price)


def handle_avis(trader: Trader, opportunities: list[Opportunity], idx: int = None):
    """Screening par Claude — batch top 3 ou opportunité spécifique."""
    if not opportunities:
        console.print(f"\n  [{C_WARN}]Fais un Scan d'abord.[/{C_WARN}]")
        return

    if idx is not None:
        if idx < 1 or idx > len(opportunities):
            console.print(f"  [{C_DANGER}]Numero invalide. Choisis entre 1 et {len(opportunities)}.[/{C_DANGER}]")
            return
        opp = opportunities[idx - 1]
        try:
            from mapem_integration import screening_single
            screening_single(opp, console)
        except ImportError:
            console.print(f"  [{C_DANGER}]Module MAPEM non disponible.[/{C_DANGER}]")
        except Exception as e:
            console.print(f"  [{C_DANGER}]Erreur avis: {e}[/{C_DANGER}]")
        return

    try:
        from mapem_integration import screening_top3
        verdicts = screening_top3(opportunities, console)
    except ImportError:
        console.print(f"  [{C_DANGER}]Module MAPEM non disponible.[/{C_DANGER}]")
        return
    except Exception as e:
        console.print(f"  [{C_DANGER}]Erreur avis: {e}[/{C_DANGER}]")
        return

    if not verdicts:
        return

    console.print(f"\n  [{C_DIM}]Tape Buy N pour acheter une opportunite.[/{C_DIM}]")


def handle_mapem(opp: Opportunity):
    """Analyse approfondie MAPEM d'une opportunité via Claude API."""
    safe_q = opp.market_question.replace("[", "\\[")
    console.print(f"\n  [{C_ACCENT}]Analyse MAPEM[/{C_ACCENT}] [{C_DIM}]{safe_q}[/{C_DIM}]")
    console.print(f"  [{C_DIM}]Appel Claude API en cours (~0.02$)...[/{C_DIM}]")

    try:
        from mapem_integration import PolymarketMAPEMAnalyzer, compute_composite
        analyzer = PolymarketMAPEMAnalyzer()
        category = opp.mapem_category or "SOCIETE_CULTURE"
        result = analyzer.deep_analyze(opp, category)

        posterior = result["posterior_prob"]
        price = opp.current_price
        divergence = posterior - price

        if divergence > 0.05:
            signal_str = f"[bold {C_SUCCESS}]SOUS-EVALUE (+{divergence:.1%})[/bold {C_SUCCESS}]"
        elif divergence < -0.05:
            signal_str = f"[bold {C_DANGER}]SUR-EVALUE ({divergence:.1%})[/bold {C_DANGER}]"
        else:
            signal_str = f"[{C_WARN}]PRIX JUSTE ({divergence:+.1%})[/{C_WARN}]"

        content = (
            f"  [{C_MUTED}]Prix marche[/{C_MUTED}]    [bold {C_ACCENT2}]${price:.3f}[/bold {C_ACCENT2}] [{C_DIM}]({price:.0%})[/{C_DIM}]\n"
            f"  [{C_MUTED}]Prob. MAPEM[/{C_MUTED}]    [bold]{posterior:.3f}[/bold] [{C_DIM}]({posterior:.0%})[/{C_DIM}]\n"
            f"  [{C_MUTED}]Signal[/{C_MUTED}]         {signal_str}\n"
            f"  [{C_MUTED}]Score MAPEM[/{C_MUTED}]    {_score_bar(result['mapem_score'], 12)}"
        )

        if result.get("analysis_summary"):
            summary = str(result["analysis_summary"])[:200].replace("[", "\\[")
            content += f"\n\n  [{C_MUTED}]{summary}[/{C_MUTED}]"

        console.print(Panel(
            content,
            title=f"[bold magenta]  Analyse MAPEM  [/bold magenta]",
            border_style="magenta",
            box=box.ROUNDED,
            padding=(1, 1),
        ))

        opp.mapem_score = result["mapem_score"]
        opp.composite_score = compute_composite(opp.confidence_score, opp.mapem_score)
        console.print(f"\n  [{C_MUTED}]Composite mis a jour:[/{C_MUTED}] {_score_bar(opp.composite_score, 12)}")

    except RuntimeError as e:
        console.print(f"  [{C_DANGER}]{e}[/{C_DANGER}]")
    except Exception as e:
        console.print(f"  [{C_DANGER}]Erreur analyse MAPEM: {e}[/{C_DANGER}]")


def handle_orders(trader: Trader):
    """Affiche les ordres ouverts."""
    if not trader.connected:
        console.print(f"  [{C_DIM}]Connexion...[/{C_DIM}]")
        if not trader.connect():
            return

    orders = trader.get_open_orders()
    if not orders:
        console.print(f"\n  [{C_MUTED}]Aucun ordre en attente.[/{C_MUTED}]")
        return

    table = Table(
        title=f"[bold {C_GOLD}]  Ordres en attente  [/bold {C_GOLD}]",
        box=box.ROUNDED,
        border_style=C_DIM,
        header_style=f"bold {C_ACCENT}",
        row_styles=["", f"{C_DIM}"],
        padding=(0, 1),
    )
    table.add_column("#", width=3, justify="center", style=f"bold {C_ACCENT}")
    table.add_column("ID", max_width=16, style=C_MUTED)
    table.add_column("Side", width=6, justify="center")
    table.add_column("Prix", justify="right", style=f"bold {C_ACCENT2}")
    table.add_column("Size", justify="right")
    table.add_column("Status", justify="center")

    for i, o in enumerate(orders, 1):
        oid = o.get("id", "?")
        side = o.get("side", "?")
        side_str = f"[bold {C_SUCCESS}]{side}[/bold {C_SUCCESS}]" if side == "BUY" else f"[bold {C_DANGER}]{side}[/bold {C_DANGER}]"
        status = o.get("status", "?")
        status_str = f"[{C_SUCCESS}]{status}[/{C_SUCCESS}]" if status == "LIVE" else status

        table.add_row(
            str(i),
            f"...{oid[-8:]}",
            side_str,
            f"${float(o.get('price', 0)):.3f}",
            str(o.get("original_size", o.get("size", "?"))),
            status_str,
        )

    console.print()
    console.print(table)


def handle_cancel(trader: Trader):
    """Annule des ordres."""
    if not trader.connected:
        console.print(f"  [{C_DIM}]Connexion...[/{C_DIM}]")
        if not trader.connect():
            return

    choice = Prompt.ask(f"  [{C_ACCENT}]Annuler[/{C_ACCENT}] [{C_DIM}][a]un ou [t]ous[/{C_DIM}]", choices=["a", "t"], default="a")
    if choice == "t":
        if Confirm.ask(f"  [bold {C_DANGER}]Annuler TOUS les ordres ?[/bold {C_DANGER}]", default=False):
            trader.cancel_all_orders()
    else:
        order_id = Prompt.ask(f"  [{C_ACCENT}]Order ID[/{C_ACCENT}]")
        trader.cancel_order(order_id)


def handle_auto(trader: Trader):
    """Mode surveillance automatique."""
    console.print(Panel(
        f"  [{C_ACCENT}]Mode AUTO active[/{C_ACCENT}]\n\n"
        f"  [{C_MUTED}]Intervalle[/{C_MUTED}]   {SCAN_INTERVAL_SECONDS}s\n"
        f"  [{C_MUTED}]Seuil[/{C_MUTED}]        score >= {MIN_CONFIDENCE_SCORE}\n"
        f"  [{C_MUTED}]Arret[/{C_MUTED}]        Ctrl+C",
        title=f"[bold {C_WARN}]  Auto  [/bold {C_WARN}]",
        border_style=C_WARN,
        box=box.ROUNDED,
        padding=(1, 2),
    ))

    try:
        while True:
            opportunities = handle_scan()
            if opportunities:
                display_opportunities(opportunities)
            good_opps = [o for o in opportunities if o.confidence_score >= MIN_CONFIDENCE_SCORE]

            if good_opps:
                console.print(f"\n  [bold {C_SUCCESS}]{len(good_opps)} opportunite(s) au-dessus du seuil[/bold {C_SUCCESS}]")
                if Confirm.ask(f"  [{C_ACCENT}]Acheter une ?[/{C_ACCENT}]", default=False):
                    idx_str = Prompt.ask(f"  [{C_ACCENT}]Numero[/{C_ACCENT}]")
                    try:
                        idx = int(idx_str)
                        if 1 <= idx <= len(good_opps):
                            _execute_buy_flow(trader, good_opps[idx - 1])
                    except ValueError:
                        pass

            console.print(f"\n  [{C_DIM}]Prochain scan dans {SCAN_INTERVAL_SECONDS}s... (Ctrl+C pour arreter)[/{C_DIM}]")
            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        console.print(f"\n  [{C_WARN}]Mode auto arrete.[/{C_WARN}]")


def handle_test():
    """Test read-only de l'API."""
    console.print(f"\n  [{C_ACCENT}]Test de connexion...[/{C_ACCENT}]")
    try:
        from scanner import fetch_active_markets, get_midpoint, parse_prices, parse_token_ids
        import requests
        from config import GAMMA_API

        resp = requests.get(f"{GAMMA_API}/markets", params={"limit": 3}, timeout=10)
        resp.raise_for_status()
        markets = resp.json()
        console.print(f"  [{C_SUCCESS}]Gamma API[/{C_SUCCESS}] [{C_DIM}]{len(markets)} marches[/{C_DIM}]")

        for m in markets:
            question = m.get("question", "?")[:60].replace("[", "\\[")
            prices = parse_prices(m)
            token_ids = parse_token_ids(m)
            prices_str = ", ".join(f"{p:.3f}" for p in prices) if prices else "N/A"
            console.print(f"\n    [{C_MUTED}]{question}[/{C_MUTED}]")
            console.print(f"    [{C_DIM}]Prix[/{C_DIM}] [{C_ACCENT2}]{prices_str}[/{C_ACCENT2}]")

            if token_ids:
                try:
                    mid = get_midpoint(token_ids[0])
                    console.print(f"    [{C_DIM}]CLOB midpoint[/{C_DIM}] [{C_ACCENT2}]${mid:.3f}[/{C_ACCENT2}]")
                except Exception:
                    console.print(f"    [{C_DIM}]CLOB midpoint  N/A[/{C_DIM}]")

        console.print(f"\n  [bold {C_SUCCESS}]Tout fonctionne. Pret a trader.[/bold {C_SUCCESS}]")

    except Exception as e:
        console.print(f"  [{C_DANGER}]Erreur: {e}[/{C_DANGER}]")


def handle_dashboard():
    """Affiche le dashboard de performance MAPEM."""
    try:
        from mapem_integration import show_performance_dashboard
        show_performance_dashboard(console)
    except ImportError:
        console.print(f"  [{C_DANGER}]Module MAPEM non disponible.[/{C_DANGER}]")
    except Exception as e:
        console.print(f"  [{C_DANGER}]Erreur dashboard: {e}[/{C_DANGER}]")


def handle_setup_keychain():
    """Lance la migration des secrets vers le Keychain macOS."""
    try:
        from keychain import setup_keychain
        setup_keychain()
    except Exception as e:
        console.print(f"  [{C_DANGER}]Erreur setup: {e}[/{C_DANGER}]")


def handle_help():
    """Aide complète en langage simple."""

    def _cmd(name, desc):
        return f"  [{C_ACCENT}]{name:<14}[/{C_ACCENT}] [{C_MUTED}]{desc}[/{C_MUTED}]"

    help_sections = []

    # Scanner section
    help_sections.append(f"[bold {C_GOLD}]  SCANNER[/bold {C_GOLD}]")
    help_sections.append(_cmd("Scan", "Cherche des opportunites sur ~100 marches actifs."))
    help_sections.append(_cmd("", "Affiche les meilleurs, classes par score de confiance."))
    help_sections.append("")
    help_sections.append(_cmd("Scan 6h", "Marches qui ferment dans les 6 prochaines heures."))
    help_sections.append(_cmd("", "Utile pour des gains rapides. 3h, 12h, 24h... au choix."))

    # Trading section
    help_sections.append(f"\n[bold {C_GOLD}]  TRADING[/bold {C_GOLD}]")
    help_sections.append(_cmd("Buy N", "Acheter l'opportunite #N. Le bot demande le montant,"))
    help_sections.append(_cmd("", "montre les details, puis demande confirmation."))
    help_sections.append("")
    help_sections.append(_cmd("Info N", "Details complets de l'opportunite #N : description,"))
    help_sections.append(_cmd("", "scores, et carnet d'ordres en direct."))
    help_sections.append("")
    help_sections.append(_cmd("Avis", "Claude analyse le top 3 (~0.03$). Verdict :"))
    help_sections.append(_cmd("", "GO / PIEGE / INCERTAIN pour chaque opportunite."))
    help_sections.append(_cmd("Avis N", "Claude analyse l'opportunite #N (~0.01$)."))

    # Orders section
    help_sections.append(f"\n[bold {C_GOLD}]  ORDRES[/bold {C_GOLD}]")
    help_sections.append(_cmd("Orders", "Ordres en attente. Un ordre limite qui n'a pas"))
    help_sections.append(_cmd("", "trouve de vendeur bloque ton argent."))
    help_sections.append(_cmd("Cancel", "Annule un ou tous tes ordres."))

    # Utility section
    help_sections.append(f"\n[bold {C_GOLD}]  UTILITAIRES[/bold {C_GOLD}]")
    help_sections.append(_cmd("Setup", "Migre tes secrets vers le trousseau macOS."))
    help_sections.append(_cmd("Dashboard", "Performance historique par categorie MAPEM."))
    help_sections.append(_cmd("N / P", "Navigation entre pages de resultats."))
    help_sections.append(_cmd("Q", "Quitter."))

    # Warning
    help_sections.append(f"\n  [{C_DIM}]{'─' * 56}[/{C_DIM}]")
    help_sections.append(f"  [bold {C_WARN}]Tu peux PERDRE 100% de ta mise.[/bold {C_WARN}]")
    help_sections.append(f"  [{C_MUTED}]Les scores sont des indicateurs, pas des garanties.[/{C_MUTED}]")

    console.print(Panel(
        "\n".join(help_sections),
        title=f"[bold {C_GOLD}]  Aide  [/bold {C_GOLD}]",
        border_style=C_DIM,
        box=box.ROUNDED,
        padding=(1, 2),
    ))


# ─────────────────────────────────────────────────────────
# Boucle principale
# ─────────────────────────────────────────────────────────

def main():
    trader = Trader()
    trader.connect()
    balance = trader.get_usdc_balance() if trader.connected else None
    show_banner(balance)

    opportunities = []
    current_page = 0
    total_pages = 0

    while True:
        try:
            show_menu()
            raw = Prompt.ask(f"  [{C_ACCENT}]>[/{C_ACCENT}]")
            cmd, arg = parse_command(raw, has_scan=bool(opportunities))

            if cmd == "quit":
                console.print(f"\n  [{C_ACCENT}]A bientot.[/{C_ACCENT}]\n")
                sys.exit(0)

            elif cmd == "help":
                handle_help()

            elif cmd == "scan":
                opportunities = handle_scan()
                current_page = 0
                if opportunities:
                    _, total_pages = display_opportunities(opportunities, current_page)

            elif cmd == "scan_hours":
                opportunities = handle_scan(max_hours=arg)
                current_page = 0
                if opportunities:
                    _, total_pages = display_opportunities(opportunities, current_page)

            elif cmd == "next_page":
                if not opportunities:
                    console.print(f"  [{C_WARN}]Fais un Scan d'abord.[/{C_WARN}]")
                elif current_page < total_pages - 1:
                    current_page += 1
                    display_opportunities(opportunities, current_page)
                else:
                    console.print(f"  [{C_DIM}]Derniere page.[/{C_DIM}]")

            elif cmd == "prev_page":
                if not opportunities:
                    console.print(f"  [{C_WARN}]Fais un Scan d'abord.[/{C_WARN}]")
                elif current_page > 0:
                    current_page -= 1
                    display_opportunities(opportunities, current_page)
                else:
                    console.print(f"  [{C_DIM}]Premiere page.[/{C_DIM}]")

            elif cmd == "buy":
                if not opportunities:
                    console.print(f"  [{C_WARN}]Fais un Scan d'abord.[/{C_WARN}]")
                elif arg < 1 or arg > len(opportunities):
                    console.print(f"  [{C_DANGER}]Numero invalide. Choisis entre 1 et {len(opportunities)}.[/{C_DANGER}]")
                else:
                    _execute_buy_flow(trader, opportunities[arg - 1])

            elif cmd == "info":
                if not opportunities:
                    console.print(f"  [{C_WARN}]Fais un Scan d'abord.[/{C_WARN}]")
                elif arg < 1 or arg > len(opportunities):
                    console.print(f"  [{C_DANGER}]Numero invalide. Choisis entre 1 et {len(opportunities)}.[/{C_DANGER}]")
                else:
                    handle_info(opportunities[arg - 1])

            elif cmd == "avis":
                handle_avis(trader, opportunities, idx=arg)

            elif cmd == "mapem":
                if not opportunities:
                    console.print(f"  [{C_WARN}]Fais un Scan d'abord.[/{C_WARN}]")
                elif arg is None or arg < 1 or arg > len(opportunities):
                    console.print(f"  [{C_DANGER}]Utilise Mapem N avec un numero valide (1-{len(opportunities)}).[/{C_DANGER}]")
                else:
                    handle_mapem(opportunities[arg - 1])

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

            elif cmd == "setup_keychain":
                handle_setup_keychain()

            else:
                console.print(f"  [{C_DIM}]Commande inconnue. Tape[/{C_DIM}] [{C_ACCENT}]?[/{C_ACCENT}] [{C_DIM}]pour l'aide.[/{C_DIM}]")

        except KeyboardInterrupt:
            console.print(f"\n  [{C_WARN}]Ctrl+C — retour au menu[/{C_WARN}]")
        except Exception as e:
            console.print(f"  [{C_DANGER}]Erreur: {e}[/{C_DANGER}]")


if __name__ == "__main__":
    main()
