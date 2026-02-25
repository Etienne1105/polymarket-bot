"""
Trader Polymarket — Exécution des trades via CLOB API
"""

import os
import re
import logging
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OpenOrderParams, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY, SELL
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config import CLOB_HOST, CHAIN_ID, MAX_PER_TRADE, DEFAULT_TICK_SIZE, MIN_TRADE_SIZE
from scanner import Opportunity

load_dotenv()
console = Console()

# Audit log — séparé de la console, ne contient pas de clés privées
logging.basicConfig(
    filename="trading_audit.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
audit = logging.getLogger("audit")


class Trader:
    def __init__(self):
        self.client = None
        self.connected = False

    def connect(self):
        """Se connecter au CLOB API avec les credentials"""
        private_key = os.getenv("PRIVATE_KEY")
        funder = os.getenv("FUNDER_ADDRESS")
        sig_type_raw = os.getenv("SIGNATURE_TYPE", "2")

        # Validation clé privée — format 0x + 64 hex chars
        if not private_key or not re.match(r'^0x[0-9a-fA-F]{64}$', private_key):
            console.print("[red]ERREUR: Clé privée invalide dans .env (doit être 0x + 64 caractères hex)[/red]")
            return False

        # Validation adresse — format 0x + 40 hex chars
        if not funder or not re.match(r'^0x[0-9a-fA-F]{40}$', funder):
            console.print("[red]ERREUR: FUNDER_ADDRESS invalide dans .env (doit être 0x + 40 caractères hex)[/red]")
            return False

        # Validation signature type
        if sig_type_raw not in ("0", "1", "2"):
            console.print("[red]ERREUR: SIGNATURE_TYPE doit être 0, 1 ou 2[/red]")
            return False
        sig_type = int(sig_type_raw)

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
            audit.info(f"CONNECT | funder={funder[:10]}... | balance={balance:.2f}")
            return True
        except Exception:
            console.print("[red]Erreur de connexion. Vérification .env recommandée.[/red]")
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
        """Exécute un achat avec validation complète"""
        if not self.connected:
            console.print("[red]Non connecté ! Lance connect() d'abord.[/red]")
            return None

        # Validation du montant
        if not isinstance(amount, (int, float)) or amount != amount:  # NaN check
            console.print("[red]Montant invalide.[/red]")
            return None
        if amount < MIN_TRADE_SIZE or amount > MAX_PER_TRADE:
            console.print(f"[red]Montant doit être entre ${MIN_TRADE_SIZE} et ${MAX_PER_TRADE}[/red]")
            return None

        # Vérification du solde avant trade
        balance = self.get_usdc_balance()
        if amount > balance:
            console.print(f"[red]Solde insuffisant: ${balance:.2f} disponible, ${amount:.2f} requis[/red]")
            return None

        try:
            from py_clob_client.clob_types import PartialCreateOrderOptions, OrderType
            order = self.client.create_market_order(
                MarketOrderArgs(
                    token_id=opp.token_id,
                    amount=amount,
                    side=BUY,
                    price=min(opp.current_price * 1.02, 0.99),
                ),
                options=PartialCreateOrderOptions(tick_size=opp.tick_size, neg_risk=opp.neg_risk),
            )
            resp = self.client.post_order(order, OrderType.FOK)

            if resp.get("success"):
                order_id = resp.get("orderID", "N/A")
                audit.info(f"BUY|SUCCESS|{opp.market_question[:40]}|${amount:.2f}|order={order_id[:16]}...")
                console.print(Panel(
                    f"[green]ACHAT EXÉCUTÉ[/green]\n"
                    f"Order ID: ...{order_id[-8:]}\n"
                    f"Status: {resp.get('status', 'N/A')}",
                    title="Succès",
                    border_style="green",
                ))
            else:
                audit.warning(f"BUY|UNMATCHED|{opp.market_question[:40]}|${amount:.2f}")
                console.print("[yellow]Ordre non rempli (FOK). Essaie un ordre limite.[/yellow]")

            return resp

        except Exception:
            audit.error(f"BUY|FAILED|{opp.market_question[:40]}|${amount:.2f}")
            console.print("[red]Erreur d'exécution. Vérifie tes ordres ouverts.[/red]")
            return None

    def execute_limit_buy(self, opp: Opportunity, amount: float, price: float = None):
        """Place un ordre limite (GTC)"""
        if not self.connected:
            console.print("[red]Non connecté ![/red]")
            return None

        if price is None:
            price = opp.current_price

        size = amount / price if price > 0 else 0

        # Vérification du solde
        balance = self.get_usdc_balance()
        if amount > balance:
            console.print(f"[red]Solde insuffisant: ${balance:.2f} disponible[/red]")
            return None

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
                order_id = resp.get("orderID", "N/A")
                audit.info(f"LIMIT_BUY|SUCCESS|{opp.market_question[:40]}|${amount:.2f}|${price:.3f}")
                console.print(Panel(
                    f"[green]ORDRE LIMITE PLACÉ[/green]\n"
                    f"Order ID: ...{order_id[-8:]}\n"
                    f"Prix: ${price:.3f} | Size: {size:.1f} shares",
                    title="Succès",
                    border_style="green",
                ))
            else:
                console.print("[yellow]Ordre non placé.[/yellow]")

            return resp

        except Exception:
            console.print("[red]Erreur lors du placement de l'ordre limite.[/red]")
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
