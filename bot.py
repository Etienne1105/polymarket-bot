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
from rich.prompt import Prompt, Confirm, FloatPrompt

from config import (
    MAX_PER_TRADE, MIN_CONFIDENCE_SCORE,
    SCAN_INTERVAL_SECONDS,
)
from scanner import scan_all, Opportunity
from trader import Trader

console = Console()

PAGE_SIZE = 8


# ─────────────────────────────────────────────────────────
# Affichage
# ─────────────────────────────────────────────────────────

def show_banner(balance=None):
    bal_str = f"${balance:.2f}" if balance is not None else "connexion requise"
    console.print(Panel(
        f"[bold cyan]📈  POLYMARKET TRADING BOT[/bold cyan]  v2.0\n"
        f"Solde: {bal_str} USDC  │  Max/trade: ${MAX_PER_TRADE:.2f}\n"
        "Mode: Semi-automatique — tu confirmes chaque trade",
        border_style="cyan",
    ))


def show_menu():
    console.print(Panel(
        "[bold cyan]Scan[/bold cyan]          →  Chercher des opportunités de profit\n"
        "[bold cyan]Scan 6h[/bold cyan]       →  Marchés qui se ferment dans les 6 heures\n"
        "[bold cyan]Buy 3[/bold cyan]         →  Acheter l'opportunité numéro 3\n"
        "[bold cyan]Info 2[/bold cyan]        →  Voir tous les détails de l'opportunité 2\n"
        "[bold cyan]Avis[/bold cyan]          →  Avis de Claude sur le top 3 (~0.03$)\n"
        "[bold cyan]Avis 4[/bold cyan]        →  Avis de Claude sur l'opportunité #4\n"
        "[bold cyan]Orders[/bold cyan]        →  Voir mes ordres en attente\n"
        "[bold cyan]Cancel[/bold cyan]        →  Annuler un ou tous mes ordres\n"
        "[bold cyan]?[/bold cyan]             →  Aide complète avec explications\n"
        "[bold cyan]Q[/bold cyan]             →  Quitter",
        title="🤖 Que veux-tu faire ?",
        border_style="cyan",
    ))


def display_opportunities(opportunities: list[Opportunity], page: int = 0):
    """Affiche les opportunités en format liste avec pagination.
    Retourne (visible_list, total_pages).
    """
    if not opportunities:
        console.print("[yellow]Aucune opportunité trouvée.[/yellow]")
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

    console.print(f"\n[bold]📊 {len(opportunities)} opportunités trouvées[/bold]  "
                  f"[dim](page {page + 1} / {total_pages})[/dim]")
    console.print("─" * 65)

    for i, opp in enumerate(visible, start + 1):
        display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score
        score_color = "green" if display_score >= 70 else "yellow" if display_score >= 50 else "red"
        profit_color = "green" if opp.profit_potential > 0.10 else "yellow"

        if 0 < opp.hours_left < 1:
            time_str = f"[bold green]⏱ {opp.hours_left * 60:.0f}min[/bold green]"
        elif 0 < opp.hours_left < 24:
            time_str = f"[green]⏱ {opp.hours_left:.0f}h[/green]"
        elif 0 < opp.hours_left < 168:
            time_str = f"⏱ {opp.hours_left / 24:.0f}j"
        else:
            time_str = ""

        cat_str = category_short(opp.mapem_category) if opp.mapem_category else "—"
        safe_outcome = opp.outcome.replace("[", "\\[")
        safe_question = opp.market_question.replace("[", "\\[")

        console.print(
            f" [bold]#{i:<3}[/bold] [{score_color}]●  {display_score}[/{score_color}]  "
            f"{cat_str}  │  {opp.strategy}  │  "
            f"{safe_outcome} @ ${opp.current_price:.2f}  │  "
            f"[{profit_color}]+{opp.profit_potential:.0%}[/{profit_color}]  │  "
            f"{time_str}"
        )
        console.print(f"      {safe_question}")
        console.print()

    console.print("─" * 65)
    nav_parts = []
    if total_pages > 1:
        if page > 0:
            nav_parts.append("[cyan]P[/cyan] ← page précédente")
        if page < total_pages - 1:
            nav_parts.append("[cyan]N[/cyan] → page suivante")
    nav_parts.append("[cyan]Buy N[/cyan] / [cyan]Avis N[/cyan] / [cyan]Info N[/cyan]")
    console.print("  " + "  │  ".join(nav_parts))

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
        label = f"marchés qui ferment dans les {max_hours}h"
    else:
        label = "tous les marchés"
    console.print(f"\n[bold cyan]🔍 Scanning ({label})...[/bold cyan]")
    try:
        opportunities = scan_all(max_hours=max_hours)
        if not opportunities and max_hours:
            console.print(f"[yellow]Aucun marché ne ferme dans les {max_hours} prochaines heures.[/yellow]")
            console.print("[dim]Essaie 'Scan 12h' ou 'Scan' pour tout voir.[/dim]")
        return opportunities
    except Exception as e:
        console.print(f"[red]Erreur scan: {e}[/red]")
        return []


def handle_info(opp: Opportunity):
    """Affiche le détail complet d'une opportunité + carnet d'ordres live."""
    try:
        from mapem_integration import category_short
        cat = category_short(opp.mapem_category) if opp.mapem_category else "—"
    except ImportError:
        cat = opp.mapem_category or "—"

    display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score

    desc = opp.market_description.strip() if opp.market_description else "[dim]Pas de description disponible[/dim]"
    safe_desc = desc.replace("[", "\\[") if opp.market_description else desc

    info = (
        f"[bold]{opp.market_question.replace('[', chr(92) + '[')}[/bold]\n\n"
        f"{safe_desc}\n\n"
        f"[bold cyan]📋 Détails du trade[/bold cyan]\n"
        f"  Stratégie:    {opp.strategy}\n"
        f"  Côté:         {opp.outcome} @ ${opp.current_price:.3f} ({opp.current_price:.0%})\n"
        f"  Estimé:       ${opp.estimated_value:.3f} ({opp.estimated_value:.0%})\n"
        f"  Profit:       {opp.profit_potential:.1%}\n"
        f"  E[P] sur $10: ${opp.expected_profit_usd:.2f}\n"
        f"  Volume 24h:   ${opp.volume_24h:,.0f}\n"
        f"  Résolution:   {opp.hours_left:.0f}h\n"
        f"  Catégorie:    {cat}\n\n"
        f"[bold cyan]📊 Scores[/bold cyan]\n"
        f"  Scanner:      {opp.confidence_score}/100\n"
        f"  MAPEM:        {opp.mapem_score if opp.mapem_score >= 0 else '—'}\n"
        f"  Composite:    {display_score}/100\n\n"
        f"[dim]{opp.details}[/dim]"
    )

    console.print(Panel(info, title="🔎 Détails de l'opportunité", border_style="cyan"))

    # Carnet d'ordres live
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

            console.print(
                f"\n[bold cyan]📖 Carnet d'ordres (live)[/bold cyan]\n"
                f"  Meilleur acheteur (bid):  ${best_bid:.3f}  ({bid_size:.0f} shares)\n"
                f"  Meilleur vendeur (ask):   ${best_ask:.3f}  ({ask_size:.0f} shares)\n"
                f"  Spread:                   ${spread:.3f} ({spread / best_ask:.1%} du ask)" if best_ask > 0 else ""
            )
    except Exception:
        pass


def _execute_buy_flow(trader: Trader, opp: Opportunity):
    """Flux d'achat commun : montant, confirmation, exécution."""
    amount = FloatPrompt.ask(f"💰 Montant à investir (max ${MAX_PER_TRADE})", default=MAX_PER_TRADE)
    amount = min(amount, MAX_PER_TRADE)

    trader.propose_trade(opp, amount)

    order_type = Prompt.ask("Type d'ordre", choices=["market", "limit"], default="market")

    if not Confirm.ask("[bold]Confirmer ce trade ?[/bold]", default=False):
        console.print("[yellow]Trade annulé.[/yellow]")
        return

    if not trader.connected:
        console.print("[yellow]Connexion au CLOB...[/yellow]")
        if not trader.connect():
            return

    if order_type == "market":
        trader.execute_buy(opp, amount)
    else:
        price = FloatPrompt.ask("Prix limite", default=opp.current_price)
        trader.execute_limit_buy(opp, amount, price)


def handle_avis(trader: Trader, opportunities: list[Opportunity], idx: int = None):
    """Screening par Claude — batch top 3 ou opportunité spécifique."""
    if not opportunities:
        console.print("[yellow]Fais un Scan d'abord.[/yellow]")
        return

    if idx is not None:
        # Avis sur une opportunité spécifique
        if idx < 1 or idx > len(opportunities):
            console.print(f"[red]Numéro invalide. Choisis entre 1 et {len(opportunities)}.[/red]")
            return
        opp = opportunities[idx - 1]
        try:
            from mapem_integration import screening_single
            screening_single(opp, console)
        except ImportError:
            console.print("[red]Module MAPEM non disponible.[/red]")
        except Exception as e:
            console.print(f"[red]Erreur avis: {e}[/red]")
        return

    # Batch top 3
    try:
        from mapem_integration import screening_top3
        verdicts = screening_top3(opportunities, console)
    except ImportError:
        console.print("[red]Module MAPEM non disponible.[/red]")
        return
    except Exception as e:
        console.print(f"[red]Erreur avis: {e}[/red]")
        return

    if not verdicts:
        return

    console.print("\n[dim]Tape 'Buy N' pour acheter une opportunité.[/dim]")


def handle_mapem(opp: Opportunity):
    """Analyse approfondie MAPEM d'une opportunité via Claude API."""
    console.print(f"\n[bold cyan]🧠 Analyse MAPEM de:[/bold cyan] {opp.market_question}")
    console.print("[dim]Appel Claude API en cours (~0.02$)...[/dim]")

    try:
        from mapem_integration import PolymarketMAPEMAnalyzer, compute_composite
        analyzer = PolymarketMAPEMAnalyzer()
        category = opp.mapem_category or "SOCIETE_CULTURE"
        result = analyzer.deep_analyze(opp, category)

        res_table = Table(title="🧠 Analyse MAPEM", show_header=False, border_style="magenta")
        res_table.add_column("", style="bold", width=20)
        res_table.add_column("", max_width=60)

        posterior = result["posterior_prob"]
        price = opp.current_price
        divergence = posterior - price

        res_table.add_row("Prix marché", f"${price:.3f} ({price:.0%})")
        res_table.add_row("Prob. MAPEM", f"{posterior:.3f} ({posterior:.0%})")

        if divergence > 0.05:
            res_table.add_row("Signal", f"[bold green]SOUS-ÉVALUÉ (+{divergence:.1%})[/bold green]")
        elif divergence < -0.05:
            res_table.add_row("Signal", f"[bold red]SUR-ÉVALUÉ ({divergence:.1%})[/bold red]")
        else:
            res_table.add_row("Signal", f"[yellow]PRIX JUSTE ({divergence:+.1%})[/yellow]")

        res_table.add_row("Score MAPEM", f"{result['mapem_score']}/100")
        if result.get("analysis_summary"):
            res_table.add_row("Résumé", str(result["analysis_summary"])[:200])

        console.print(res_table)

        opp.mapem_score = result["mapem_score"]
        opp.composite_score = compute_composite(opp.confidence_score, opp.mapem_score)
        console.print(f"\n[bold]Score composite mis à jour: {opp.composite_score}/100[/bold]")

    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
    except Exception as e:
        console.print(f"[red]Erreur analyse MAPEM: {e}[/red]")


def handle_orders(trader: Trader):
    """Affiche les ordres ouverts."""
    if not trader.connected:
        console.print("[yellow]Connexion...[/yellow]")
        if not trader.connect():
            return

    orders = trader.get_open_orders()
    if not orders:
        console.print("[yellow]Aucun ordre en attente.[/yellow]")
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
        console.print("[yellow]Connexion...[/yellow]")
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
        f"🔄 Mode AUTO activé — Scan toutes les {SCAN_INTERVAL_SECONDS}s\n"
        f"Seuil minimum: score >= {MIN_CONFIDENCE_SCORE}\n"
        "Ctrl+C pour arrêter",
        title="Auto Mode",
        border_style="yellow",
    ))

    try:
        while True:
            opportunities = handle_scan()
            if opportunities:
                display_opportunities(opportunities)
            good_opps = [o for o in opportunities if o.confidence_score >= MIN_CONFIDENCE_SCORE]

            if good_opps:
                console.print(f"\n[bold green]>>> {len(good_opps)} opportunités au-dessus du seuil ![/bold green]")
                if Confirm.ask("Veux-tu en acheter une ?", default=False):
                    idx_str = Prompt.ask("Numéro")
                    try:
                        idx = int(idx_str)
                        if 1 <= idx <= len(good_opps):
                            _execute_buy_flow(trader, good_opps[idx - 1])
                    except ValueError:
                        pass

            console.print(f"\n[dim]Prochain scan dans {SCAN_INTERVAL_SECONDS}s... (Ctrl+C pour arrêter)[/dim]")
            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        console.print("\n[yellow]Mode auto arrêté.[/yellow]")


def handle_test():
    """Test read-only de l'API."""
    console.print("\n[cyan]🔌 Test de connexion read-only...[/cyan]")
    try:
        from scanner import fetch_active_markets, get_midpoint, parse_prices, parse_token_ids
        import requests
        from config import GAMMA_API

        resp = requests.get(f"{GAMMA_API}/markets", params={"limit": 3}, timeout=10)
        resp.raise_for_status()
        markets = resp.json()
        console.print(f"[green]✓ Gamma API OK — {len(markets)} marchés récupérés[/green]")

        for m in markets:
            question = m.get("question", "?")[:60]
            prices = parse_prices(m)
            token_ids = parse_token_ids(m)
            prices_str = ", ".join(f"{p:.3f}" for p in prices) if prices else "N/A"
            console.print(f"  • {question}")
            console.print(f"    Prix: [{prices_str}]")

            if token_ids:
                try:
                    mid = get_midpoint(token_ids[0])
                    console.print(f"    CLOB midpoint: ${mid:.3f}")
                except Exception:
                    console.print("    [dim]CLOB midpoint: N/A[/dim]")

        console.print("\n[green bold]✓ Tout fonctionne ! Tu es prêt à trader.[/green bold]")

    except Exception as e:
        console.print(f"[red]✗ Erreur: {e}[/red]")


def handle_dashboard():
    """Affiche le dashboard de performance MAPEM."""
    try:
        from mapem_integration import show_performance_dashboard
        show_performance_dashboard(console)
    except ImportError:
        console.print("[red]Module MAPEM non disponible.[/red]")
    except Exception as e:
        console.print(f"[red]Erreur dashboard: {e}[/red]")


def handle_help():
    """Aide complète en langage simple."""
    help_text = (
        "[bold cyan]📚 AIDE COMPLÈTE[/bold cyan]\n\n"

        "[bold]Scan[/bold]\n"
        "  Tape [cyan]Scan[/cyan] pour chercher des opportunités de profit sur tous\n"
        "  les marchés Polymarket actifs. Le bot analyse ~100 marchés et te\n"
        "  montre les meilleurs classés par score de confiance.\n\n"

        "[bold]Scan 6h[/bold]  (ou 3h, 12h, 24h...)\n"
        "  Tape [cyan]Scan 6h[/cyan] pour voir uniquement les marchés qui se ferment\n"
        "  dans les 6 prochaines heures. Utile pour trouver des gains rapides.\n"
        "  Tu peux choisir n'importe quel nombre d'heures.\n\n"

        "[bold]Buy 3[/bold]\n"
        "  Tape [cyan]Buy 3[/cyan] pour acheter l'opportunité numéro 3 de ton dernier\n"
        "  scan. Le bot te demandera combien tu veux investir, te montrera\n"
        "  les détails, puis te demandera de confirmer. Rien ne se passe\n"
        "  sans ta confirmation.\n\n"

        "[bold]Info 2[/bold]\n"
        "  Tape [cyan]Info 2[/cyan] pour voir tous les détails de l'opportunité #2 :\n"
        "  description du marché, scores, et le carnet d'ordres en direct\n"
        "  (combien de gens veulent acheter/vendre et à quel prix).\n\n"

        "[bold]Avis[/bold]  ou  [bold]Avis 4[/bold]\n"
        "  Tape [cyan]Avis[/cyan] pour que Claude analyse les 3 meilleures opportunités\n"
        "  et te dise si c'est un bon pari ou un piège (~0.03$).\n"
        "  Tape [cyan]Avis 4[/cyan] pour analyser une opportunité spécifique (~0.01$).\n\n"

        "[bold]Orders[/bold]\n"
        "  Affiche tes ordres en attente. Un ordre en attente, c'est un\n"
        "  achat 'limite' qui n'a pas encore trouvé de vendeur à ton prix.\n"
        "  Tant qu'il est en attente, ton argent est bloqué.\n\n"

        "[bold]Cancel[/bold]\n"
        "  Annule un ou tous tes ordres en attente pour libérer ton argent.\n\n"

        "[bold]N / P[/bold]\n"
        "  Quand il y a plusieurs pages de résultats :\n"
        "  [cyan]N[/cyan] = page suivante  │  [cyan]P[/cyan] = page précédente\n\n"

        "[bold]Q[/bold]\n"
        "  Quitter le bot.\n\n"

        "[bold yellow]⚠️  Rappel : tu peux PERDRE 100% de ta mise.\n"
        "Les scores du bot sont des indicateurs, pas des garanties.[/bold yellow]"
    )
    console.print(Panel(help_text, border_style="cyan", padding=(1, 2)))


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
            raw = Prompt.ask("▶")
            cmd, arg = parse_command(raw, has_scan=bool(opportunities))

            if cmd == "quit":
                console.print("[cyan]👋 Bye ![/cyan]")
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
                    console.print("[yellow]Fais un Scan d'abord.[/yellow]")
                elif current_page < total_pages - 1:
                    current_page += 1
                    display_opportunities(opportunities, current_page)
                else:
                    console.print("[dim]Dernière page.[/dim]")

            elif cmd == "prev_page":
                if not opportunities:
                    console.print("[yellow]Fais un Scan d'abord.[/yellow]")
                elif current_page > 0:
                    current_page -= 1
                    display_opportunities(opportunities, current_page)
                else:
                    console.print("[dim]Première page.[/dim]")

            elif cmd == "buy":
                if not opportunities:
                    console.print("[yellow]Fais un Scan d'abord.[/yellow]")
                elif arg < 1 or arg > len(opportunities):
                    console.print(f"[red]Numéro invalide. Choisis entre 1 et {len(opportunities)}.[/red]")
                else:
                    _execute_buy_flow(trader, opportunities[arg - 1])

            elif cmd == "info":
                if not opportunities:
                    console.print("[yellow]Fais un Scan d'abord.[/yellow]")
                elif arg < 1 or arg > len(opportunities):
                    console.print(f"[red]Numéro invalide. Choisis entre 1 et {len(opportunities)}.[/red]")
                else:
                    handle_info(opportunities[arg - 1])

            elif cmd == "avis":
                handle_avis(trader, opportunities, idx=arg)

            elif cmd == "mapem":
                if not opportunities:
                    console.print("[yellow]Fais un Scan d'abord.[/yellow]")
                elif arg is None or arg < 1 or arg > len(opportunities):
                    console.print(f"[red]Utilise 'Mapem N' avec un numéro valide (1-{len(opportunities)}).[/red]")
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

            else:
                console.print(f"[dim]Commande non reconnue. Tape [cyan]?[/cyan] pour voir les options.[/dim]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Ctrl+C — retour au menu[/yellow]")
        except Exception as e:
            console.print(f"[red]Erreur: {e}[/red]")


if __name__ == "__main__":
    main()
