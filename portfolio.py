"""
Portfolio 💰 — Suivi des positions, PnL, stop-loss et take-profit
=================================================================
Récupère les positions via CLOB API, calcule le PnL en temps réel,
et déclenche des alertes stop-loss / take-profit.
"""

import logging
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import STOP_LOSS_PCT, TAKE_PROFIT_PCT, GAMMA_API
from models import Position

logger = logging.getLogger(__name__)

console = Console()


class Portfolio:
    """Gestionnaire de portfolio avec suivi PnL et alertes."""

    def __init__(self, trader):
        self._trader = trader
        self._positions: list[Position] = []
        self._alerts: list[str] = []

    # ------------------------------------------------------------------
    # Récupération des positions
    # ------------------------------------------------------------------

    def refresh_positions(self) -> list[Position]:
        """Rafraîchit les positions depuis l'API."""
        if not self._trader.connected:
            console.print("[yellow]Non connecté. Lance 'connect' d'abord.[/yellow]")
            return []

        try:
            # Utiliser les ordres ouverts comme proxy pour les positions
            # La vraie API de positions nécessite le Data API
            import requests
            from keychain import get_secret

            funder = get_secret("FUNDER_ADDRESS")
            if not funder:
                console.print("[yellow]FUNDER_ADDRESS manquante.[/yellow]")
                return []

            # Essayer l'API Data pour les positions
            resp = requests.get(
                f"https://data-api.polymarket.com/positions",
                params={"user": funder.lower(), "sizeThreshold": "0.1"},
                timeout=15,
            )
            resp.raise_for_status()
            raw_positions = resp.json()

            positions = []
            for p in raw_positions:
                size = float(p.get("size", 0))
                if size <= 0:
                    continue

                avg_price = float(p.get("avgPrice", 0))
                cur_price = float(p.get("curPrice", avg_price))

                pnl = (cur_price - avg_price) * size
                pnl_pct = (cur_price - avg_price) / avg_price if avg_price > 0 else 0

                positions.append(Position(
                    market_question=p.get("title", p.get("question", "?")),
                    token_id=p.get("asset", p.get("token_id", "")),
                    outcome=p.get("outcome", "?"),
                    size=size,
                    avg_price=avg_price,
                    current_price=cur_price,
                    condition_id=p.get("conditionId", ""),
                    asset_id=p.get("asset", ""),
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    market_slug=p.get("slug", ""),
                    neg_risk=p.get("negRisk", False),
                ))

            self._positions = positions
            return positions

        except Exception as e:
            logger.warning(f"Portfolio: erreur refresh — {e}")
            # Fallback : retourner les positions cachées
            return self._positions

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------

    def display_portfolio(self):
        """Affiche le portfolio avec PnL."""
        positions = self.refresh_positions()

        if not positions:
            console.print("[yellow]Aucune position ouverte.[/yellow]")
            return

        table = Table(title="💰 Rupee Pouch — Positions", border_style="green")
        table.add_column("#", width=3)
        table.add_column("Marché", max_width=40)
        table.add_column("Côté", width=5)
        table.add_column("Shares", justify="right", width=8)
        table.add_column("Prix moy.", justify="right", width=9)
        table.add_column("Prix act.", justify="right", width=9)
        table.add_column("PnL", justify="right", width=10)
        table.add_column("PnL %", justify="right", width=7)

        total_pnl = 0
        total_value = 0

        for i, pos in enumerate(positions, 1):
            pnl_color = "green" if pos.pnl >= 0 else "red"
            safe_q = pos.market_question[:38].replace("[", "\\[")

            table.add_row(
                str(i),
                safe_q,
                pos.outcome[:4],
                f"{pos.size:.1f}",
                f"${pos.avg_price:.3f}",
                f"${pos.current_price:.3f}",
                f"[{pnl_color}]${pos.pnl:+.2f}[/{pnl_color}]",
                f"[{pnl_color}]{pos.pnl_pct:+.1%}[/{pnl_color}]",
            )

            total_pnl += pos.pnl
            total_value += pos.current_price * pos.size

        console.print(table)

        pnl_color = "green" if total_pnl >= 0 else "red"
        console.print(f"\n  Valeur totale: [bold]${total_value:.2f}[/bold]  |  "
                      f"PnL total: [{pnl_color}][bold]${total_pnl:+.2f}[/{pnl_color}][/bold]")

        # Vérifier les alertes
        alerts = self.check_alerts()
        if alerts:
            console.print()
            for alert in alerts:
                console.print(alert)

    # ------------------------------------------------------------------
    # Alertes stop-loss / take-profit
    # ------------------------------------------------------------------

    def check_alerts(self) -> list[str]:
        """Vérifie les stop-loss et take-profit sur toutes les positions."""
        alerts = []

        for i, pos in enumerate(self._positions, 1):
            if pos.avg_price <= 0:
                continue

            # Stop-loss : perte > STOP_LOSS_PCT
            if pos.pnl_pct <= -STOP_LOSS_PCT:
                alerts.append(
                    f"[bold red]🚨 STOP-LOSS #{i}[/bold red] — "
                    f"{pos.market_question[:40]} — "
                    f"PnL: {pos.pnl_pct:+.1%} (seuil: -{STOP_LOSS_PCT:.0%})"
                )

            # Take-profit : gain > TAKE_PROFIT_PCT
            elif pos.pnl_pct >= TAKE_PROFIT_PCT:
                alerts.append(
                    f"[bold green]💰 TAKE-PROFIT #{i}[/bold green] — "
                    f"{pos.market_question[:40]} — "
                    f"PnL: {pos.pnl_pct:+.1%} (seuil: +{TAKE_PROFIT_PCT:.0%})"
                )

        self._alerts = alerts
        return alerts

    # ------------------------------------------------------------------
    # Vente d'une position
    # ------------------------------------------------------------------

    def propose_sell(self, idx: int):
        """Propose la vente d'une position (1-based index)."""
        if not self._positions:
            self.refresh_positions()

        if idx < 1 or idx > len(self._positions):
            console.print(f"[red]Numéro invalide. Choisis entre 1 et {len(self._positions)}.[/red]")
            return None

        pos = self._positions[idx - 1]

        # Marché résolu — shares sans valeur
        if pos.current_price <= 0:
            console.print(Panel(
                f"[bold]{pos.market_question.replace('[', chr(92) + '[')}[/bold]\n\n"
                f"  Prix actuel: [red]$0.000[/red]\n"
                f"  Ce marché est résolu. Tes shares n'ont plus de valeur.\n"
                f"  PnL final: [red]${pos.pnl:+.2f}[/red]",
                title="💀 Position morte",
                border_style="red",
            ))
            return None

        console.print(Panel(
            f"[bold]{pos.market_question.replace('[', chr(92) + '[')}[/bold]\n\n"
            f"  Côté:        {pos.outcome}\n"
            f"  Shares:      {pos.size:.1f}\n"
            f"  Prix achat:  ${pos.avg_price:.3f}\n"
            f"  Prix actuel: ${pos.current_price:.3f}\n"
            f"  PnL:         {'[green]' if pos.pnl >= 0 else '[red]'}${pos.pnl:+.2f} ({pos.pnl_pct:+.1%})"
            f"{'[/green]' if pos.pnl >= 0 else '[/red]'}",
            title="📦 Vente proposée",
            border_style="yellow",
        ))

        return pos

    @property
    def positions(self) -> list[Position]:
        return self._positions


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_portfolio_instance: Portfolio | None = None


def get_portfolio(trader) -> Portfolio:
    """Retourne l'instance singleton du Portfolio."""
    global _portfolio_instance
    if _portfolio_instance is None:
        _portfolio_instance = Portfolio(trader)
    return _portfolio_instance
