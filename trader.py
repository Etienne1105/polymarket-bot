"""
Trader Polymarket — Exécution des trades via CLOB API
"""

import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OpenOrderParams, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY, SELL
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import CLOB_HOST, CHAIN_ID, MAX_PER_TRADE, DEFAULT_TICK_SIZE
from scanner import Opportunity

load_dotenv()
console = Console()


class Trader:
    def __init__(self):
        self.client = None
        self.connected = False

    def connect(self):
        """Se connecter au CLOB API avec les credentials"""
        private_key = os.getenv("PRIVATE_KEY")
        funder = os.getenv("FUNDER_ADDRESS")
        sig_type = int(os.getenv("SIGNATURE_TYPE", "0"))

        if not private_key or private_key == "0xTACLEPRIVEEICI":
            console.print("[red]ERREUR: Configure ta clé privée dans .env[/red]")
            return False

        if not funder or funder == "0xTONADRESSEICI":
            console.print("[red]ERREUR: Configure ton adresse dans .env[/red]")
            return False

        try:
            self.client = ClobClient(
                host=CLOB_HOST,
                key=private_key,
                chain_id=CHAIN_ID,
                signature_type=sig_type,
                funder=funder,
            )
            creds = self.client.create_or_derive_api_creds()
            self.client.set_api_creds(creds)
            self.connected = True
            balance = self.get_usdc_balance()
            console.print(f"[green]Connecté au CLOB API | Solde: ${balance:.2f} USDC[/green]")
            return True
        except Exception as e:
            console.print(f"[red]Erreur de connexion: {e}[/red]")
            return False

    def get_usdc_balance(self):
        """Récupère le solde USDC réel depuis Polymarket"""
        if not self.connected:
            return 0.0
        try:
            ba = self.client.get_balance_allowance(BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=int(os.getenv("SIGNATURE_TYPE", "2")),
            ))
            raw = int(ba.get("balance", "0"))
            return raw / 1e6  # USDC a 6 décimales
        except Exception:
            return 0.0

    def propose_trade(self, opp: Opportunity, amount: float = None):
        """Affiche les détails d'un trade proposé"""
        if amount is None:
            amount = min(MAX_PER_TRADE, 10.0)

        shares = amount / opp.current_price if opp.current_price > 0 else 0
        potential_profit = shares * opp.estimated_value - amount
        potential_loss = -amount  # Pire cas: le marché résout à 0

        table = Table(title="Trade Proposé", show_header=False, border_style="cyan")
        table.add_column("", style="bold")
        table.add_column("")

        table.add_row("Marché", opp.market_question)
        table.add_row("Stratégie", opp.strategy)
        table.add_row("Action", f"BUY {opp.outcome}")
        table.add_row("Prix actuel", f"${opp.current_price:.3f}")
        table.add_row("Valeur estimée", f"${opp.estimated_value:.3f}")
        table.add_row("Montant", f"${amount:.2f}")
        table.add_row("Shares", f"{shares:.1f}")
        table.add_row("Profit potentiel", f"[green]+${potential_profit:.2f} ({opp.profit_potential:.1%})[/green]")
        table.add_row("Perte max", f"[red]-${amount:.2f}[/red]")
        table.add_row("Score confiance", f"{opp.confidence_score}/100")
        table.add_row("Détails", opp.details)

        console.print(table)
        return amount, shares

    def execute_buy(self, opp: Opportunity, amount: float):
        """Exécute un achat"""
        if not self.connected:
            console.print("[red]Non connecté ! Lance connect() d'abord.[/red]")
            return None

        try:
            # Utiliser un ordre FOK (Fill-Or-Kill) pour un achat immédiat
            order = self.client.create_market_order(
                MarketOrderArgs(
                    token_id=opp.token_id,
                    amount=amount,
                    side=BUY,
                    price=min(opp.current_price * 1.02, 0.99),  # 2% de slippage max
                ),
                options={
                    "tick_size": opp.tick_size,
                    "neg_risk": opp.neg_risk,
                },
            )
            resp = self.client.post_order(order, order_type="FOK")

            if resp.get("success"):
                console.print(Panel(
                    f"[green]ACHAT EXÉCUTÉ[/green]\n"
                    f"Order ID: {resp.get('orderID', 'N/A')}\n"
                    f"Status: {resp.get('status', 'N/A')}",
                    title="Succès",
                    border_style="green",
                ))
            else:
                console.print(f"[yellow]Ordre non rempli: {resp}[/yellow]")

            return resp

        except Exception as e:
            console.print(f"[red]Erreur d'exécution: {e}[/red]")
            return None

    def execute_limit_buy(self, opp: Opportunity, amount: float, price: float = None):
        """Place un ordre limite (GTC)"""
        if not self.connected:
            console.print("[red]Non connecté ![/red]")
            return None

        if price is None:
            price = opp.current_price

        size = amount / price if price > 0 else 0

        try:
            resp = self.client.create_and_post_order(
                OrderArgs(
                    token_id=opp.token_id,
                    price=price,
                    size=size,
                    side=BUY,
                ),
                options={
                    "tick_size": opp.tick_size,
                    "neg_risk": opp.neg_risk,
                },
                order_type="GTC",
            )

            if resp.get("success"):
                console.print(Panel(
                    f"[green]ORDRE LIMITE PLACÉ[/green]\n"
                    f"Order ID: {resp.get('orderID', 'N/A')}\n"
                    f"Prix: ${price:.3f} | Size: {size:.1f} shares",
                    title="Succès",
                    border_style="green",
                ))
            else:
                console.print(f"[yellow]Ordre non placé: {resp}[/yellow]")

            return resp

        except Exception as e:
            console.print(f"[red]Erreur: {e}[/red]")
            return None

    def execute_sell(self, token_id: str, size: float, price: float,
                     tick_size: str = DEFAULT_TICK_SIZE, neg_risk: bool = False):
        """Vend des shares"""
        if not self.connected:
            console.print("[red]Non connecté ![/red]")
            return None

        try:
            resp = self.client.create_and_post_order(
                OrderArgs(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=SELL,
                ),
                options={
                    "tick_size": tick_size,
                    "neg_risk": neg_risk,
                },
                order_type="GTC",
            )

            if resp.get("success"):
                console.print(Panel(
                    f"[green]VENTE PLACÉE[/green]\n"
                    f"Order ID: {resp.get('orderID', 'N/A')}\n"
                    f"Prix: ${price:.3f} | Size: {size:.1f} shares",
                    title="Vente",
                    border_style="green",
                ))
            else:
                console.print(f"[yellow]Ordre non placé: {resp}[/yellow]")

            return resp

        except Exception as e:
            console.print(f"[red]Erreur: {e}[/red]")
            return None

    def get_open_orders(self):
        """Récupère les ordres ouverts"""
        if not self.connected:
            return []
        try:
            orders = self.client.get_orders(OpenOrderParams())
            return orders if orders else []
        except Exception as e:
            console.print(f"[red]Erreur: {e}[/red]")
            return []

    def cancel_order(self, order_id: str):
        """Annule un ordre"""
        if not self.connected:
            return None
        try:
            resp = self.client.cancel(order_id)
            console.print(f"[green]Ordre {order_id[:16]}... annulé[/green]")
            return resp
        except Exception as e:
            console.print(f"[red]Erreur annulation: {e}[/red]")
            return None

    def cancel_all_orders(self):
        """Annule tous les ordres"""
        if not self.connected:
            return None
        try:
            resp = self.client.cancel_all()
            console.print("[green]Tous les ordres annulés[/green]")
            return resp
        except Exception as e:
            console.print(f"[red]Erreur: {e}[/red]")
            return None
