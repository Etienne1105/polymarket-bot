"""
Modèles de données partagés — RupeeHunter v3
=============================================
Dataclasses utilisées par tous les modules du bot.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Opportunity:
    """Opportunité de trading détectée par le scanner."""
    market_question: str
    condition_id: str
    token_id: str
    outcome: str  # "Yes" or "No"
    current_price: float
    estimated_value: float
    profit_potential: float  # en %
    confidence_score: int  # 0-100
    strategy: str  # "near_resolution", "spread_arb", "momentum"
    volume_24h: float
    details: str
    hours_left: float = -1
    neg_risk: bool = False
    tick_size: str = "0.01"
    market_description: str = ""
    # MAPEM
    mapem_category: str = ""
    mapem_score: int = -1
    composite_score: int = -1
    # v3 — Explorer
    event_id: str = ""
    event_slug: str = ""
    # v3 — Expertise humaine
    human_score: int = 0
    human_notes: str = ""
    # v3 — Navi
    navi_verdict: str = ""  # GO, PIEGE, INCERTAIN
    navi_analysis: str = ""
    navi_prob: float = -1.0

    @property
    def expected_profit_usd(self):
        """Profit attendu pour 10$ investis."""
        if self.current_price <= 0:
            return 0
        shares = 10.0 / self.current_price
        return shares * self.estimated_value - 10.0


@dataclass
class MarketView:
    """Un marché vu via l'explorer (pas forcément une opportunité)."""
    question: str
    condition_id: str
    slug: str
    volume: float
    liquidity: float
    end_date: str
    prices: list  # [yes_price, no_price]
    token_ids: list
    description: str = ""
    event_slug: str = ""
    tags: list = field(default_factory=list)
    neg_risk: bool = False
    tick_size: str = "0.01"
    outcomes: list = field(default_factory=lambda: ["Yes", "No"])


def market_view_to_opportunity(mv: MarketView, outcome_idx: int = 0) -> Opportunity:
    """Convertit un MarketView en Opportunity basique (sans scoring scanner).
    outcome_idx: 0 = Yes, 1 = No (quel côté acheter).
    """
    price = mv.prices[outcome_idx] if outcome_idx < len(mv.prices) else 0.0
    token_id = mv.token_ids[outcome_idx] if outcome_idx < len(mv.token_ids) else ""
    outcome = mv.outcomes[outcome_idx] if outcome_idx < len(mv.outcomes) else "Yes"

    from scanner import hours_until_resolution
    hours_left = -1.0
    if mv.end_date:
        try:
            hours_left = hours_until_resolution({"endDate": mv.end_date})
        except Exception:
            pass

    return Opportunity(
        market_question=mv.question,
        condition_id=mv.condition_id,
        token_id=token_id,
        outcome=outcome,
        current_price=price,
        estimated_value=price,  # pas d'estimation sans scanner
        profit_potential=0.0,
        confidence_score=0,
        strategy="explorer",
        volume_24h=mv.volume,
        details=f"Via explorer · Vol ${mv.volume:,.0f}",
        hours_left=hours_left,
        neg_risk=mv.neg_risk,
        tick_size=mv.tick_size,
        market_description=mv.description,
        event_slug=mv.event_slug,
    )


@dataclass
class Position:
    """Position ouverte dans le portfolio."""
    market_question: str
    token_id: str
    outcome: str
    size: float  # nombre de shares
    avg_price: float  # prix moyen d'achat
    current_price: float
    condition_id: str = ""
    asset_id: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0
    neg_risk: bool = False
    tick_size: str = "0.01"
    market_slug: str = ""


@dataclass
class TagInfo:
    """Tag/catégorie Polymarket."""
    id: str
    label: str
    slug: str
    market_count: int = 0


@dataclass
class TradeRecord:
    """Enregistrement d'un trade pour le learner."""
    id: int = 0
    timestamp: str = ""
    market_question: str = ""
    token_id: str = ""
    outcome: str = ""
    side: str = ""  # BUY / SELL
    price: float = 0.0
    amount: float = 0.0
    size: float = 0.0
    strategy: str = ""
    category: str = ""
    scanner_score: int = 0
    mapem_score: int = 0
    composite_score: int = 0
    human_score: int = 0
    navi_verdict: str = ""
    resolved: bool = False
    resolution_price: float = -1.0
    profit_loss: float = 0.0
