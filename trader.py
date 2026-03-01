"""
Trader Polymarket — Exécution des trades via CLOB API
"""

import re
import logging
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OpenOrderParams, BalanceAllowanceParams, AssetType
from py_clob_client.order_builder.constants import BUY, SELL
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from config import CLOB_HOST, CHAIN_ID, MAX_PER_TRADE, DEFAULT_TICK_SIZE, MIN_TRADE_SIZE
from scanner import Opportunity
from keychain import get_secret
console = Console()

# Visual palette (shared with bot.py)
C_ACCENT = "bright_cyan"
C_ACCENT2 = "deep_sky_blue1"
C_GOLD = "gold1"
C_SUCCESS = "green"
C_DANGER = "red"
C_WARN = "yellow"
C_DIM = "bright_black"
C_MUTED = "grey62"

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
        private_key = get_secret("PRIVATE_KEY")
        funder = get_secret("FUNDER_ADDRESS")
        sig_type_raw = get_secret("SIGNATURE_TYPE") or "2"

        # Validation clé privée — format 0x + 64 hex chars
        if not private_key or not re.match(r'^0x[0-9a-fA-F]{64}$', private_key):
            console.print(f"  [{C_DANGER}]Cle privee invalide dans le Keychain[/{C_DANGER}]")
            console.print(f"  [{C_DIM}]Lance 'setup' pour configurer tes secrets.[/{C_DIM}]")
            return False

        # Validation adresse — format 0x + 40 hex chars
        if not funder or not re.match(r'^0x[0-9a-fA-F]{40}$', funder):
            console.print(f"  [{C_DANGER}]FUNDER_ADDRESS invalide dans le Keychain[/{C_DANGER}]")
            console.print(f"  [{C_DIM}]Lance 'setup' pour configurer tes secrets.[/{C_DIM}]")
            return False

        # Validation signature type
        if sig_type_raw not in ("0", "1", "2"):
            console.print(f"  [{C_DANGER}]SIGNATURE_TYPE doit etre 0, 1 ou 2[/{C_DANGER}]")
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
            console.print(f"  [{C_SUCCESS}]Connecte[/{C_SUCCESS}] [{C_DIM}]|[/{C_DIM}] [{C_ACCENT2}]${balance:.2f}[/{C_ACCENT2}] [{C_MUTED}]USDC[/{C_MUTED}]")
            audit.info(f"CONNECT | funder={funder[:10]}... | balance={balance:.2f}")
            return True
        except Exception:
            console.print(f"  [{C_DANGER}]Erreur de connexion. Verifie tes secrets (setup).[/{C_DANGER}]")
            return False

    def get_usdc_balance(self):
        """Récupère le solde USDC réel depuis Polymarket"""
        if not self.connected:
            return 0.0
        try:
            ba = self.client.get_balance_allowance(BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=int(get_secret("SIGNATURE_TYPE") or "2"),
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

        safe_question = opp.market_question.replace("[", "\\[")
        safe_outcome = opp.outcome.replace("[", "\\[")

        content = (
            f"  [bold white]{safe_question}[/bold white]\n\n"
            f"  [{C_MUTED}]Action[/{C_MUTED}]         [bold {C_ACCENT}]BUY[/bold {C_ACCENT}] [bold]{safe_outcome}[/bold]\n"
            f"  [{C_MUTED}]Strategie[/{C_MUTED}]      {opp.strategy}\n"
            f"  [{C_MUTED}]Prix actuel[/{C_MUTED}]    [bold {C_ACCENT2}]${opp.current_price:.3f}[/bold {C_ACCENT2}]\n"
            f"  [{C_MUTED}]Valeur estimee[/{C_MUTED}] [bold]${opp.estimated_value:.3f}[/bold]\n\n"
            f"  [{C_DIM}]{'─' * 40}[/{C_DIM}]\n\n"
            f"  [{C_MUTED}]Montant[/{C_MUTED}]        [bold {C_GOLD}]${amount:.2f}[/bold {C_GOLD}]\n"
            f"  [{C_MUTED}]Shares[/{C_MUTED}]         [bold]{shares:.1f}[/bold]\n"
            f"  [{C_MUTED}]Profit[/{C_MUTED}]         [bold {C_SUCCESS}]+${potential_profit:.2f}[/bold {C_SUCCESS}] [{C_DIM}]({opp.profit_potential:.1%})[/{C_DIM}]\n"
            f"  [{C_MUTED}]Perte max[/{C_MUTED}]      [bold {C_DANGER}]-${amount:.2f}[/bold {C_DANGER}]"
        )

        console.print(Panel(
            content,
            title=f"[bold {C_WARN}]  Trade Propose  [/bold {C_WARN}]",
            border_style=C_WARN,
            box=box.ROUNDED,
            padding=(1, 2),
        ))
        return amount, shares

    def execute_buy(self, opp: Opportunity, amount: float):
        """Exécute un achat avec validation complète"""
        if not self.connected:
            console.print(f"  [{C_DANGER}]Non connecte. Lance connect() d'abord.[/{C_DANGER}]")
            return None

        # Validation du montant
        if not isinstance(amount, (int, float)) or amount != amount:  # NaN check
            console.print(f"  [{C_DANGER}]Montant invalide.[/{C_DANGER}]")
            return None
        if amount < MIN_TRADE_SIZE or amount > MAX_PER_TRADE:
            console.print(f"  [{C_DANGER}]Montant doit etre entre ${MIN_TRADE_SIZE} et ${MAX_PER_TRADE}[/{C_DANGER}]")
            return None

        # Vérification du solde avant trade
        balance = self.get_usdc_balance()
        if amount > balance:
            console.print(f"  [{C_DANGER}]Solde insuffisant: ${balance:.2f} disponible, ${amount:.2f} requis[/{C_DANGER}]")
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
                    f"  [bold {C_SUCCESS}]ACHAT EXECUTE[/bold {C_SUCCESS}]\n\n"
                    f"  [{C_MUTED}]Order ID[/{C_MUTED}]  [{C_DIM}]...{order_id[-8:]}[/{C_DIM}]\n"
                    f"  [{C_MUTED}]Status[/{C_MUTED}]    [{C_SUCCESS}]{resp.get('status', 'N/A')}[/{C_SUCCESS}]",
                    border_style=C_SUCCESS,
                    box=box.ROUNDED,
                    padding=(1, 2),
                ))
                # Log dans MAPEM DB
                try:
                    from mapem_integration import log_trade_to_mapem
                    log_trade_to_mapem(opp, amount, resp)
                except Exception as e:
                    audit.warning(f"MAPEM_LOG|FAILED|{e}")
            else:
                audit.warning(f"BUY|UNMATCHED|{opp.market_question[:40]}|${amount:.2f}")
                console.print(f"  [{C_WARN}]Ordre non rempli (FOK). Essaie un ordre limite.[/{C_WARN}]")

            return resp

        except Exception as e:
            audit.error(f"BUY|FAILED|{opp.market_question[:40]}|${amount:.2f}|{e}")
            console.print(f"  [{C_DANGER}]Erreur d'execution: {e}[/{C_DANGER}]")
            console.print(f"  [{C_DIM}]Verifie tes ordres ouverts avec 'orders'.[/{C_DIM}]")
            return None

    def execute_limit_buy(self, opp: Opportunity, amount: float, price: float = None):
        """Place un ordre limite (GTC)"""
        if not self.connected:
            console.print(f"  [{C_DANGER}]Non connecte.[/{C_DANGER}]")
            return None

        if price is None:
            price = opp.current_price

        size = amount / price if price > 0 else 0

        # Vérification du solde
        balance = self.get_usdc_balance()
        if amount > balance:
            console.print(f"  [{C_DANGER}]Solde insuffisant: ${balance:.2f} disponible[/{C_DANGER}]")
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
                    f"  [bold {C_SUCCESS}]ORDRE LIMITE PLACE[/bold {C_SUCCESS}]\n\n"
                    f"  [{C_MUTED}]Order ID[/{C_MUTED}]  [{C_DIM}]...{order_id[-8:]}[/{C_DIM}]\n"
                    f"  [{C_MUTED}]Prix[/{C_MUTED}]      [{C_ACCENT2}]${price:.3f}[/{C_ACCENT2}]\n"
                    f"  [{C_MUTED}]Size[/{C_MUTED}]      [bold]{size:.1f}[/bold] [{C_DIM}]shares[/{C_DIM}]",
                    border_style=C_SUCCESS,
                    box=box.ROUNDED,
                    padding=(1, 2),
                ))
                # Log dans MAPEM DB
                try:
                    from mapem_integration import log_trade_to_mapem
                    log_trade_to_mapem(opp, amount, resp)
                except Exception as e:
                    audit.warning(f"MAPEM_LOG|FAILED|{e}")
            else:
                console.print(f"  [{C_WARN}]Ordre non place.[/{C_WARN}]")

            return resp

        except Exception:
            console.print(f"  [{C_DANGER}]Erreur lors du placement de l'ordre limite.[/{C_DANGER}]")
            return None

    def execute_sell(self, token_id: str, size: float, price: float,
                     tick_size: str = DEFAULT_TICK_SIZE, neg_risk: bool = False):
        """Vend des shares"""
        if not self.connected:
            console.print(f"  [{C_DANGER}]Non connecte.[/{C_DANGER}]")
            return None

        if not isinstance(size, (int, float)) or size != size:
            console.print(f"  [{C_DANGER}]Taille invalide.[/{C_DANGER}]")
            return None
        if size <= 0:
            console.print(f"  [{C_DANGER}]Taille doit etre > 0[/{C_DANGER}]")
            return None

        if not isinstance(price, (int, float)) or price != price:
            console.print(f"  [{C_DANGER}]Prix invalide.[/{C_DANGER}]")
            return None
        if price <= 0 or price > 1.0:
            console.print(f"  [{C_DANGER}]Prix doit etre entre 0 et 1.0[/{C_DANGER}]")
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
                order_id = resp.get('orderID', 'N/A')
                console.print(Panel(
                    f"  [bold {C_SUCCESS}]VENTE PLACEE[/bold {C_SUCCESS}]\n\n"
                    f"  [{C_MUTED}]Order ID[/{C_MUTED}]  [{C_DIM}]...{order_id[-8:]}[/{C_DIM}]\n"
                    f"  [{C_MUTED}]Prix[/{C_MUTED}]      [{C_ACCENT2}]${price:.3f}[/{C_ACCENT2}]\n"
                    f"  [{C_MUTED}]Size[/{C_MUTED}]      [bold]{size:.1f}[/bold] [{C_DIM}]shares[/{C_DIM}]",
                    border_style=C_SUCCESS,
                    box=box.ROUNDED,
                    padding=(1, 2),
                ))
            else:
                console.print(f"  [{C_WARN}]Ordre non place.[/{C_WARN}]")

            return resp

        except Exception as e:
            console.print(f"  [{C_DANGER}]Erreur: {e}[/{C_DANGER}]")
            return None

    def get_open_orders(self):
        """Récupère les ordres ouverts"""
        if not self.connected:
            return []
        try:
            orders = self.client.get_orders(OpenOrderParams())
            return orders if orders else []
        except Exception as e:
            console.print(f"  [{C_DANGER}]Erreur: {e}[/{C_DANGER}]")
            return []

    def cancel_order(self, order_id: str):
        """Annule un ordre"""
        if not self.connected:
            return None
        try:
            resp = self.client.cancel(order_id)
            console.print(f"  [{C_SUCCESS}]Ordre ...{order_id[-8:]} annule[/{C_SUCCESS}]")
            return resp
        except Exception as e:
            console.print(f"  [{C_DANGER}]Erreur annulation: {e}[/{C_DANGER}]")
            return None

    def cancel_all_orders(self):
        """Annule tous les ordres"""
        if not self.connected:
            return None
        try:
            resp = self.client.cancel_all()
            console.print(f"  [{C_SUCCESS}]Tous les ordres annules[/{C_SUCCESS}]")
            return resp
        except Exception as e:
            console.print(f"  [{C_DANGER}]Erreur: {e}[/{C_DANGER}]")
            return None
