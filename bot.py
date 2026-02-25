#!/usr/bin/env python3
"""
Bot Polymarket — Menu interactif semi-automatique
"""

import sys
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, FloatPrompt

from config import (
    MAX_PER_TRADE, MIN_CONFIDENCE_SCORE,
    SCAN_INTERVAL_SECONDS,
)
from scanner import scan_all, Opportunity
from trader import Trader

console = Console()


def show_banner(balance=None):
    bal_str = f"${balance:.2f}" if balance is not None else "connexion requise"
    console.print(Panel(
        "[bold cyan]POLYMARKET TRADING BOT[/bold cyan]\n"
        f"Solde: {bal_str} USDC | Max/trade: ${MAX_PER_TRADE:.2f}\n"
        "Mode: Semi-automatique (tu approuves chaque trade)",
        title="v1.0",
        border_style="cyan",
    ))


def show_menu():
    console.print("\n[bold]Que veux-tu faire ?[/bold]")
    console.print("  [cyan]1[/cyan] - SCAN      → Scanner toutes les opportunités")
    console.print("  [cyan]t[/cyan] - TONIGHT   → Scanner seulement ce qui résout ce soir (<16h)")
    console.print("  [cyan]i[/cyan] - INFO      → Voir le détail d'une opportunité")
    console.print("  [cyan]2[/cyan] - BUY       → Acheter (à partir du dernier scan)")
    console.print("  [cyan]a[/cyan] - AVIS      → Screening rapide du top 3 par Claude (~0.03$)")
    console.print("  [cyan]m[/cyan] - MAPEM     → Analyse approfondie d'une opportunité (Claude API)")
    console.print("  [cyan]d[/cyan] - DASHBOARD → Performance et calibration MAPEM")
    console.print("  [cyan]3[/cyan] - ORDERS    → Voir les ordres ouverts")
    console.print("  [cyan]4[/cyan] - CANCEL    → Annuler un/tous les ordres")
    console.print("  [cyan]5[/cyan] - AUTO      → Mode surveillance automatique")
    console.print("  [cyan]6[/cyan] - TEST      → Tester la connexion API (read-only)")
    console.print("  [cyan]h[/cyan] - HELP      → Aide et explications")
    console.print("  [cyan]q[/cyan] - QUIT      → Quitter")
    return Prompt.ask("\nChoix", choices=["1", "t", "i", "2", "3", "4", "5", "6", "a", "m", "d", "h", "q"], default="1")


def display_opportunities(opportunities: list[Opportunity]):
    """Affiche les opportunités dans un tableau"""
    if not opportunities:
        console.print("[yellow]Aucune opportunité trouvée.[/yellow]")
        return

    table = Table(title=f"Top Opportunités ({len(opportunities)} trouvées)")
    table.add_column("#", style="bold", width=3)
    table.add_column("Score", justify="center", width=5)
    table.add_column("Cat", width=4)
    table.add_column("M", justify="center", width=3)
    table.add_column("Stratégie", width=14)
    table.add_column("Marché", max_width=40)
    table.add_column("Side", width=5)
    table.add_column("Prix", justify="right", width=6)
    table.add_column("Estimé", justify="right", width=6)
    table.add_column("Profit%", justify="right", width=7)
    table.add_column("E[P]$10", justify="right", width=7)
    table.add_column("Résout", justify="right", width=7)

    # Import conditionnel pour les abréviations de catégorie
    try:
        from mapem_integration import category_short
    except ImportError:
        category_short = lambda c: c[:4].upper() if c else ""

    for i, opp in enumerate(opportunities[:15], 1):
        # Utiliser composite_score si disponible, sinon confidence_score
        display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score
        score_color = "green" if display_score >= 70 else "yellow" if display_score >= 50 else "red"
        profit_color = "green" if opp.profit_potential > 0.10 else "yellow"

        if 0 < opp.hours_left < 1:
            time_str = f"[bold green]{opp.hours_left * 60:.0f}min[/bold green]"
        elif 0 < opp.hours_left < 24:
            time_str = f"[green]{opp.hours_left:.0f}h[/green]"
        elif 0 < opp.hours_left < 168:
            time_str = f"{opp.hours_left / 24:.0f}j"
        else:
            time_str = "[dim]—[/dim]"

        # Échapper les données externes pour éviter l'injection Rich markup
        safe_question = opp.market_question[:40].replace("[", "\\[")
        safe_outcome = opp.outcome.replace("[", "\\[")

        # Catégorie et score MAPEM
        cat_str = category_short(opp.mapem_category) if opp.mapem_category else "[dim]—[/dim]"
        mapem_str = str(opp.mapem_score) if opp.mapem_score >= 0 else "[dim]—[/dim]"

        table.add_row(
            str(i),
            f"[{score_color}]{display_score}[/{score_color}]",
            cat_str,
            mapem_str,
            opp.strategy,
            safe_question,
            safe_outcome,
            f"${opp.current_price:.2f}",
            f"${opp.estimated_value:.2f}",
            f"[{profit_color}]{opp.profit_potential:.1%}[/{profit_color}]",
            f"${opp.expected_profit_usd:.2f}",
            time_str,
        )

    console.print(table)


def handle_scan(tonight_only=False):
    """Scan et retourne les opportunités"""
    label = "ce soir" if tonight_only else "tous les marchés"
    console.print(f"\n[bold cyan]Scanning ({label})...[/bold cyan]")
    try:
        opportunities = scan_all(tonight_only=tonight_only)
        display_opportunities(opportunities)
        return opportunities
    except Exception as e:
        console.print(f"[red]Erreur scan: {e}[/red]")
        return []


def handle_info(opportunities: list[Opportunity]):
    """Affiche le détail complet d'une opportunité."""
    if not opportunities:
        console.print("[yellow]Fais un SCAN d'abord (option 1)[/yellow]")
        return

    display_opportunities(opportunities)
    visible = opportunities[:15]
    idx_str = Prompt.ask("Numéro de l'opportunité à détailler (ou 'b' pour retour)", default="b")
    if idx_str.lower() == "b":
        return

    try:
        idx = int(idx_str) - 1
        if idx < 0 or idx >= len(visible):
            console.print("[red]Numéro invalide[/red]")
            return
    except ValueError:
        console.print("[red]Entre un numéro valide[/red]")
        return

    opp = visible[idx]

    from rich.panel import Panel

    # Catégorie
    try:
        from mapem_integration import category_short
        cat = category_short(opp.mapem_category) if opp.mapem_category else "—"
    except ImportError:
        cat = opp.mapem_category or "—"

    display_score = opp.composite_score if opp.composite_score >= 0 else opp.confidence_score

    # Description du marché
    desc = opp.market_description.strip() if opp.market_description else "[dim]Pas de description disponible[/dim]"
    safe_desc = desc.replace("[", "\\[") if opp.market_description else desc

    info = (
        f"[bold]{opp.market_question.replace('[', chr(92) + '[')}[/bold]\n\n"
        f"{safe_desc}\n\n"
        f"[bold cyan]Détails du trade[/bold cyan]\n"
        f"  Stratégie:    {opp.strategy}\n"
        f"  Côté:         {opp.outcome} @ ${opp.current_price:.3f} ({opp.current_price:.0%})\n"
        f"  Estimé:       ${opp.estimated_value:.3f} ({opp.estimated_value:.0%})\n"
        f"  Profit:       {opp.profit_potential:.1%}\n"
        f"  E[P] sur $10: ${opp.expected_profit_usd:.2f}\n"
        f"  Volume 24h:   ${opp.volume_24h:,.0f}\n"
        f"  Résolution:   {opp.hours_left:.0f}h\n"
        f"  Catégorie:    {cat}\n\n"
        f"[bold cyan]Scores[/bold cyan]\n"
        f"  Scanner:      {opp.confidence_score}/100\n"
        f"  MAPEM:        {opp.mapem_score if opp.mapem_score >= 0 else '—'}\n"
        f"  Composite:    {display_score}/100\n\n"
        f"[dim]{opp.details}[/dim]"
    )

    console.print(Panel(info, title=f"Opportunité #{idx + 1}", border_style="cyan"))


def _execute_buy_flow(trader: Trader, opp: Opportunity):
    """Flux d'achat commun : montant, confirmation, exécution."""
    amount = FloatPrompt.ask(f"Montant à investir (max ${MAX_PER_TRADE})", default=MAX_PER_TRADE)
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


def handle_buy(trader: Trader, opportunities: list[Opportunity]):
    """Propose un achat à partir du scan"""
    if not opportunities:
        console.print("[yellow]Fais un SCAN d'abord (option 1)[/yellow]")
        return

    display_opportunities(opportunities)
    visible = opportunities[:15]
    idx_str = Prompt.ask("Numéro de l'opportunité à acheter (ou 'b' pour retour)", default="b")
    if idx_str.lower() == "b":
        return

    try:
        idx = int(idx_str) - 1
        if idx < 0 or idx >= len(visible):
            console.print("[red]Numéro invalide[/red]")
            return
    except ValueError:
        console.print("[red]Entre un numéro valide[/red]")
        return

    _execute_buy_flow(trader, visible[idx])


def handle_orders(trader: Trader):
    """Affiche les ordres ouverts"""
    if not trader.connected:
        console.print("[yellow]Connexion...[/yellow]")
        if not trader.connect():
            return

    orders = trader.get_open_orders()
    if not orders:
        console.print("[yellow]Aucun ordre ouvert.[/yellow]")
        return

    table = Table(title="Ordres Ouverts")
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
    """Annule des ordres"""
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
    """Mode surveillance automatique"""
    console.print(Panel(
        f"Mode AUTO activé — Scan toutes les {SCAN_INTERVAL_SECONDS}s\n"
        f"Seuil minimum: score >= {MIN_CONFIDENCE_SCORE}\n"
        "Ctrl+C pour arrêter",
        title="Auto Mode",
        border_style="yellow",
    ))

    try:
        while True:
            opportunities = handle_scan()
            good_opps = [o for o in opportunities if o.confidence_score >= MIN_CONFIDENCE_SCORE]

            if good_opps:
                console.print(f"\n[bold green]>>> {len(good_opps)} opportunités au-dessus du seuil ![/bold green]")
                if Confirm.ask("Veux-tu en acheter une ?", default=False):
                    handle_buy(trader, good_opps)

            console.print(f"\n[dim]Prochain scan dans {SCAN_INTERVAL_SECONDS}s... (Ctrl+C pour arrêter)[/dim]")
            time.sleep(SCAN_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        console.print("\n[yellow]Mode auto arrêté.[/yellow]")


def handle_help():
    """Aide interactive — explique chaque fonction et concept"""
    console.print(Panel(
        "[bold cyan]AIDE DU BOT POLYMARKET[/bold cyan]",
        border_style="cyan",
    ))

    topics = {
        "1": "Comment fonctionne le bot",
        "2": "Comment fonctionne Polymarket",
        "3": "SCAN — Scanner les opportunités",
        "4": "BUY — Acheter une position",
        "5": "ORDERS — Voir mes ordres",
        "6": "CANCEL — Annuler des ordres",
        "7": "AUTO — Mode surveillance",
        "8": "Comprendre le tableau du scan",
        "9": "Ordre market vs limite",
        "10": "Les stratégies du scanner",
        "11": "Les risques",
        "12": "Glossaire (termes importants)",
    }

    for k, v in topics.items():
        console.print(f"  [cyan]{k}[/cyan] - {v}")
    console.print("  [cyan]b[/cyan] - Retour au menu")

    choice = Prompt.ask("\nSujet", choices=list(topics.keys()) + ["b"], default="1")

    if choice == "b":
        return

    help_texts = {
        "1": (
            "[bold]Comment fonctionne le bot[/bold]\n\n"
            "Le bot se connecte à Polymarket via leur API officielle.\n"
            "Il analyse les marchés actifs pour trouver des opportunités\n"
            "de profit, puis te les propose. Tu décides si tu veux acheter\n"
            "ou non — rien ne se passe sans ta confirmation.\n\n"
            "Étapes typiques :\n"
            "  1. SCAN → le bot cherche les opportunités\n"
            "  2. Tu regardes les résultats\n"
            "  3. BUY → tu choisis une opportunité\n"
            "  4. Tu confirmes le montant et le trade\n"
            "  5. Tu attends que le marché se résolve\n"
            "  6. Si tu as raison → tes shares valent $1 chaque\n"
            "     Si tu as tort → tes shares valent $0"
        ),
        "2": (
            "[bold]Comment fonctionne Polymarket[/bold]\n\n"
            "Polymarket est un marché de prédiction. Les gens parient\n"
            "sur des événements réels (sport, politique, crypto, météo...).\n\n"
            "Chaque marché a une question (ex: 'Les Cavaliers vont-ils gagner ?')\n"
            "avec deux résultats : [green]Yes[/green] et [red]No[/red].\n\n"
            "Les prix vont de $0.00 à $1.00 :\n"
            "  • Yes à $0.70 = le marché pense qu'il y a 70% de chances\n"
            "  • No à $0.30 = l'inverse (30% de chances que Yes se réalise)\n"
            "  • Yes + No = toujours environ $1.00\n\n"
            "Quand le marché se résout :\n"
            "  • Le côté gagnant vaut [green]$1.00[/green] par share\n"
            "  • Le côté perdant vaut [red]$0.00[/red] par share\n\n"
            "Exemple : Tu achètes Yes à $0.60, ça se réalise → tu gagnes $0.40/share\n"
            "          Tu achètes Yes à $0.60, ça ne se réalise pas → tu perds $0.60/share"
        ),
        "3": (
            "[bold]SCAN — Scanner les opportunités[/bold]\n\n"
            "Le scan analyse ~100 marchés actifs et cherche des opportunités\n"
            "avec 3 stratégies différentes (tape 10 pour les détails).\n\n"
            "Il affiche un tableau trié par score de confiance.\n"
            "Plus le score est haut, plus le bot pense que c'est intéressant.\n\n"
            "Le scan ne place AUCUN ordre — c'est juste de l'analyse."
        ),
        "4": (
            "[bold]BUY — Acheter une position[/bold]\n\n"
            "Après un SCAN, tu peux acheter une des opportunités trouvées.\n\n"
            "Le bot te montre :\n"
            "  • Le marché et le côté (Yes/No)\n"
            "  • Le prix actuel et le prix estimé\n"
            "  • Le profit potentiel si tu gagnes\n"
            "  • La perte maximum (= ton montant misé)\n\n"
            "Tu choisis :\n"
            "  • Le montant (max $10 par défaut)\n"
            "  • Market ou Limit (tape 9 pour la différence)\n"
            "  • Confirmer oui/non\n\n"
            "[bold yellow]RIEN ne se passe sans ta confirmation finale.[/bold yellow]"
        ),
        "5": (
            "[bold]ORDERS — Voir mes ordres[/bold]\n\n"
            "Affiche tous tes ordres ouverts (pas encore exécutés).\n"
            "Surtout utile si tu as placé des ordres limite\n"
            "qui attendent d'être remplis.\n\n"
            "Un ordre 'market' s'exécute immédiatement,\n"
            "donc il n'apparaîtra pas ici."
        ),
        "6": (
            "[bold]CANCEL — Annuler des ordres[/bold]\n\n"
            "Permet d'annuler :\n"
            "  • Un seul ordre (en donnant son ID)\n"
            "  • Tous tes ordres d'un coup\n\n"
            "Utile si tu as placé un ordre limite qui ne se remplit pas\n"
            "et que tu veux récupérer tes fonds."
        ),
        "7": (
            "[bold]AUTO — Mode surveillance[/bold]\n\n"
            "Le bot fait un SCAN automatiquement toutes les 60 secondes.\n"
            "Quand il trouve une opportunité au-dessus du seuil de confiance,\n"
            "il te prévient et te demande si tu veux acheter.\n\n"
            "Ctrl+C pour arrêter et revenir au menu.\n\n"
            "C'est utile pour surveiller les marchés sans devoir\n"
            "manuellement relancer le scan à chaque fois."
        ),
        "8": (
            "[bold]Comprendre le tableau du scan[/bold]\n\n"
            "Colonnes du tableau :\n\n"
            "  [cyan]#[/cyan]         → Numéro (pour choisir dans BUY)\n"
            "  [cyan]Score[/cyan]     → Confiance du bot (0-100)\n"
            "                 [green]Vert (70+)[/green] = bon | [yellow]Jaune (50-69)[/yellow] = moyen | [red]Rouge (<50)[/red] = faible\n"
            "  [cyan]Stratégie[/cyan] → Quelle méthode a trouvé cette opportunité\n"
            "  [cyan]Marché[/cyan]    → La question du marché\n"
            "  [cyan]Side[/cyan]      → Yes ou No (le côté recommandé)\n"
            "  [cyan]Prix[/cyan]      → Prix actuel du share\n"
            "  [cyan]Estimé[/cyan]    → Valeur estimée par le bot\n"
            "  [cyan]Profit%[/cyan]   → Pourcentage de profit potentiel\n"
            "  [cyan]E[P] $10[/cyan]  → Profit espéré si tu mises $10"
        ),
        "9": (
            "[bold]Ordre market vs limite[/bold]\n\n"
            "[cyan]Market (recommandé pour débuter)[/cyan]\n"
            "  • S'exécute immédiatement au meilleur prix disponible\n"
            "  • Tu es sûr d'acheter, mais le prix peut bouger légèrement\n"
            "  • Le bot met un slippage max de 2% pour te protéger\n\n"
            "[cyan]Limit[/cyan]\n"
            "  • Tu fixes le prix exact que tu veux payer\n"
            "  • Si personne ne vend à ce prix, l'ordre reste en attente\n"
            "  • Utile pour acheter à un prix précis\n"
            "  • Tu peux l'annuler avec CANCEL si ça ne se remplit pas"
        ),
        "10": (
            "[bold]Les 3 stratégies du scanner[/bold]\n\n"
            "[cyan]near_resolution[/cyan] — Marchés proches de la fin\n"
            "  Cherche les marchés qui se terminent dans <48h où le\n"
            "  résultat semble quasi-certain (prix > 85%).\n"
            "  Ex: Un match déjà en cours où une équipe mène largement.\n\n"
            "[cyan]wide_spread[/cyan] — Écarts de prix exploitables\n"
            "  Cherche les marchés où l'écart entre acheteurs et vendeurs\n"
            "  est anormalement large. On peut acheter bas et vendre haut.\n\n"
            "[cyan]momentum[/cyan] — Volume et tendance\n"
            "  Cherche les marchés avec beaucoup d'activité (volume élevé)\n"
            "  et un prix qui bouge dans une direction. On suit la tendance."
        ),
        "11": (
            "[bold yellow]Les risques[/bold yellow]\n\n"
            "• Tu peux [red]PERDRE 100%[/red] de ta mise si le marché résout contre toi\n"
            "• Les estimations du bot ne sont PAS des garanties\n"
            "• Le score de confiance est un indicateur, pas une certitude\n"
            "• Les marchés sportifs peuvent avoir des surprises (upsets)\n"
            "• Les frais de gas sur Polygon sont minimes mais existent\n"
            "• Ne mise jamais plus que ce que tu peux te permettre de perdre\n\n"
            "[bold]Règles de sécurité du bot :[/bold]\n"
            "  • Max $10 par trade (configurable dans config.py)\n"
            "  • Max 5 positions ouvertes simultanément\n"
            "  • Toujours demander confirmation avant d'acheter"
        ),
        "12": (
            "[bold]Glossaire[/bold]\n\n"
            "[cyan]Share[/cyan]      — Une unité de pari. Vaut $1 si tu gagnes, $0 si tu perds.\n"
            "[cyan]Yes/No[/cyan]     — Les deux côtés d'un marché. Yes = ça arrive, No = ça n'arrive pas.\n"
            "[cyan]Bid[/cyan]        — Prix que les acheteurs veulent payer (offre d'achat).\n"
            "[cyan]Ask[/cyan]        — Prix que les vendeurs demandent (offre de vente).\n"
            "[cyan]Spread[/cyan]     — L'écart entre le Bid et le Ask.\n"
            "[cyan]Midpoint[/cyan]   — Le prix moyen entre Bid et Ask.\n"
            "[cyan]Volume[/cyan]     — Le montant total échangé sur un marché.\n"
            "[cyan]Slippage[/cyan]   — La différence entre le prix attendu et le prix réel d'exécution.\n"
            "[cyan]GTC[/cyan]        — Good-Til-Cancelled : ordre qui reste actif jusqu'à annulation.\n"
            "[cyan]FOK[/cyan]        — Fill-Or-Kill : s'exécute en entier immédiatement ou s'annule.\n"
            "[cyan]Résolution[/cyan] — Quand le résultat du marché est connu et que les shares sont payées.\n"
            "[cyan]USDC[/cyan]       — La monnaie utilisée sur Polymarket (1 USDC = 1 USD).\n"
            "[cyan]Polygon[/cyan]    — La blockchain sur laquelle Polymarket fonctionne.\n"
            "[cyan]Gas[/cyan]        — Frais de transaction sur la blockchain (très faibles sur Polygon)."
        ),
    }

    text = help_texts.get(choice, "Sujet non trouvé.")
    console.print(Panel(text, border_style="cyan", padding=(1, 2)))

    Prompt.ask("\n[dim]Appuie sur Enter pour revenir au menu[/dim]")


def handle_test():
    """Test read-only de l'API"""
    console.print("\n[cyan]Test de connexion read-only...[/cyan]")
    try:
        from scanner import fetch_active_markets, get_midpoint, parse_prices, parse_token_ids
        import requests
        from config import GAMMA_API

        # Test Gamma API
        resp = requests.get(f"{GAMMA_API}/markets", params={"limit": 3}, timeout=10)
        resp.raise_for_status()
        markets = resp.json()
        console.print(f"[green]Gamma API OK — {len(markets)} marchés récupérés[/green]")

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

        console.print("\n[green bold]Tout fonctionne ! Tu es prêt à trader.[/green bold]")

    except Exception as e:
        console.print(f"[red]Erreur: {e}[/red]")


def handle_avis(trader: Trader, opportunities: list[Opportunity]):
    """Screening rapide du top 3 par Claude, puis proposition d'achat."""
    if not opportunities:
        console.print("[yellow]Fais un SCAN d'abord (option 1)[/yellow]")
        return

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

    # Proposer l'achat parmi le top 3
    top3 = opportunities[:3]
    idx_str = Prompt.ask(
        "\nNuméro de l'opportunité à acheter (1-3) ou 'b' pour retour",
        default="b",
    )
    if idx_str.lower() == "b":
        return

    try:
        idx = int(idx_str) - 1
        if idx < 0 or idx >= len(top3):
            console.print("[red]Numéro invalide (1-3)[/red]")
            return
    except ValueError:
        console.print("[red]Entre un numéro valide[/red]")
        return

    _execute_buy_flow(trader, top3[idx])


def handle_mapem(opportunities: list[Opportunity]):
    """Analyse approfondie MAPEM d'une opportunité via Claude API."""
    if not opportunities:
        console.print("[yellow]Fais un SCAN d'abord (option 1)[/yellow]")
        return

    display_opportunities(opportunities)
    idx_str = Prompt.ask("Numéro de l'opportunité à analyser (ou 'b' pour retour)", default="b")
    if idx_str.lower() == "b":
        return

    try:
        idx = int(idx_str) - 1
        if idx < 0 or idx >= len(opportunities):
            console.print("[red]Numéro invalide[/red]")
            return
    except ValueError:
        console.print("[red]Entre un numéro valide[/red]")
        return

    opp = opportunities[idx]
    console.print(f"\n[bold cyan]Analyse MAPEM de:[/bold cyan] {opp.market_question}")
    console.print("[dim]Appel Claude API en cours (~0.02$)...[/dim]")

    try:
        from mapem_integration import PolymarketMAPEMAnalyzer
        analyzer = PolymarketMAPEMAnalyzer()
        category = opp.mapem_category or "SOCIETE_CULTURE"
        result = analyzer.deep_analyze(opp, category)

        # Afficher les résultats
        from rich.panel import Panel
        from rich.table import Table

        res_table = Table(title="Analyse MAPEM", show_header=False, border_style="magenta")
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

        # Mettre à jour le score MAPEM de l'opportunité
        opp.mapem_score = result["mapem_score"]
        from mapem_integration import compute_composite
        opp.composite_score = compute_composite(opp.confidence_score, opp.mapem_score)
        console.print(f"\n[bold]Score composite mis à jour: {opp.composite_score}/100[/bold]")

    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
    except Exception as e:
        console.print(f"[red]Erreur analyse MAPEM: {e}[/red]")


def handle_dashboard():
    """Affiche le dashboard de performance MAPEM."""
    try:
        from mapem_integration import show_performance_dashboard
        show_performance_dashboard(console)
    except ImportError:
        console.print("[red]Module MAPEM non disponible.[/red]")
    except Exception as e:
        console.print(f"[red]Erreur dashboard: {e}[/red]")


def main():
    trader = Trader()
    # Connexion automatique au démarrage pour afficher le solde
    trader.connect()
    balance = trader.get_usdc_balance() if trader.connected else None
    show_banner(balance)

    opportunities = []

    while True:
        try:
            choice = show_menu()

            if choice == "1":
                opportunities = handle_scan()
            elif choice == "t":
                opportunities = handle_scan(tonight_only=True)
            elif choice == "i":
                handle_info(opportunities)
            elif choice == "2":
                handle_buy(trader, opportunities)
            elif choice == "a":
                handle_avis(trader, opportunities)
            elif choice == "m":
                handle_mapem(opportunities)
            elif choice == "d":
                handle_dashboard()
            elif choice == "3":
                handle_orders(trader)
            elif choice == "4":
                handle_cancel(trader)
            elif choice == "5":
                handle_auto(trader)
            elif choice == "6":
                handle_test()
            elif choice == "h":
                handle_help()
            elif choice == "q":
                console.print("[cyan]Bye ![/cyan]")
                sys.exit(0)

        except KeyboardInterrupt:
            console.print("\n[yellow]Ctrl+C — retour au menu[/yellow]")
        except Exception as e:
            console.print(f"[red]Erreur: {e}[/red]")


if __name__ == "__main__":
    main()
