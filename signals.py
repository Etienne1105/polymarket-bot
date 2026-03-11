"""
Trade Signals — Recommandations de trading et sizing
=====================================================
Genere des signaux BUY/WATCH/PASS avec sizing via Kelly fractionnel.
"""

import logging
from dataclasses import dataclass

from models import Opportunity
from edge import EdgeResult
from config import MAX_PER_TRADE, MAX_OPEN_POSITIONS, MIN_TRADE_SIZE

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Signal de trade genere par le moteur."""
    action: str          # BUY, WATCH, PASS
    strength: str        # STRONG, MODERATE, WEAK
    suggested_size: float  # USDC
    kelly_fraction: float
    urgency: str         # NOW, SOON, PATIENT
    reasoning: str


def generate_signal(opp: Opportunity, edge: EdgeResult,
                    balance: float, open_positions: int) -> TradeSignal:
    """Genere un signal de trade a partir de l'edge et du contexte.

    Sizing via Kelly fractionnel (quarter Kelly pour la securite) :
    - kelly = edge / (1 - market_price)
    - size = kelly * budget_dispo * confidence
    - Jamais > MAX_PER_TRADE ($10)
    - Diversification : budget_dispo / (MAX_OPEN_POSITIONS - open_positions)

    Arbre de decision :
    1. Grade F → PASS
    2. Grade A + Navi GO + velocity >= 3 → BUY STRONG (NOW)
    3. Grade A + Navi GO → BUY MODERATE (SOON)
    4. Grade B + signal fort → BUY WEAK (PATIENT)
    5. Grade B + INCERTAIN → WATCH
    6. Grade C/D → PASS
    """
    # Grade F = toujours PASS
    if edge.grade == "F":
        return TradeSignal(
            action="PASS", strength="", suggested_size=0.0,
            kelly_fraction=0.0, urgency="",
            reasoning="Navi detecte un piege",
        )

    # Grade D = pas d'edge
    if edge.grade == "D":
        return TradeSignal(
            action="PASS", strength="", suggested_size=0.0,
            kelly_fraction=0.0, urgency="",
            reasoning="Edge trop faible (<5%)",
        )

    # Grade C = edge faible
    if edge.grade == "C":
        return TradeSignal(
            action="PASS", strength="", suggested_size=0.0,
            kelly_fraction=0.0, urgency="",
            reasoning=f"Edge faible ({edge.edge:+.0%}), confiance insuffisante",
        )

    # Calculer le sizing Kelly fractionnel
    kelly = _compute_kelly(edge, opp.current_price)
    slots_remaining = max(1, MAX_OPEN_POSITIONS - open_positions)
    budget_per_slot = balance / slots_remaining
    size = kelly * budget_per_slot * edge.confidence

    # Contraintes
    size = min(size, MAX_PER_TRADE)
    size = max(0, size)

    navi_verdict = opp.navi_verdict

    # Grade A
    if edge.grade == "A":
        if navi_verdict == "GO" and opp.news_velocity >= 3:
            if size < MIN_TRADE_SIZE:
                size = MIN_TRADE_SIZE
            return TradeSignal(
                action="BUY", strength="STRONG",
                suggested_size=round(size, 2),
                kelly_fraction=kelly,
                urgency="NOW",
                reasoning=f"Edge {edge.edge:+.0%} | Navi GO | {opp.news_velocity}x news recentes",
            )
        elif navi_verdict == "GO":
            if size < MIN_TRADE_SIZE:
                size = MIN_TRADE_SIZE
            return TradeSignal(
                action="BUY", strength="MODERATE",
                suggested_size=round(size, 2),
                kelly_fraction=kelly,
                urgency="SOON",
                reasoning=f"Edge {edge.edge:+.0%} | Navi GO",
            )
        else:
            # Grade A sans Navi GO → BUY WEAK
            return TradeSignal(
                action="BUY", strength="WEAK",
                suggested_size=round(min(size, MIN_TRADE_SIZE), 2),
                kelly_fraction=kelly,
                urgency="PATIENT",
                reasoning=f"Edge {edge.edge:+.0%} | Navi {navi_verdict or 'N/A'}",
            )

    # Grade B
    if edge.grade == "B":
        if opp.news_signal > 30 and navi_verdict != "INCERTAIN":
            return TradeSignal(
                action="BUY", strength="WEAK",
                suggested_size=round(min(size, MIN_TRADE_SIZE), 2),
                kelly_fraction=kelly,
                urgency="PATIENT",
                reasoning=f"Edge {edge.edge:+.0%} | Signal news {opp.news_signal:.0f}%",
            )
        else:
            return TradeSignal(
                action="WATCH", strength="",
                suggested_size=0.0,
                kelly_fraction=kelly,
                urgency="",
                reasoning=f"Edge {edge.edge:+.0%} mais signal insuffisant",
            )

    # Fallback
    return TradeSignal(
        action="PASS", strength="", suggested_size=0.0,
        kelly_fraction=0.0, urgency="",
        reasoning="Aucun signal clair",
    )


def _compute_kelly(edge: EdgeResult, market_price: float) -> float:
    """Calcule le Kelly fractionnel (quarter Kelly).

    kelly_full = edge / (1 - market_price)
    quarter_kelly = kelly_full / 4
    Cappe a 0.25 (jamais plus de 25% du budget dispo)
    """
    denom = 1.0 - market_price
    if denom <= 0.01:
        return 0.0

    kelly_full = edge.edge / denom
    quarter_kelly = kelly_full / 4.0

    return max(0.0, min(0.25, quarter_kelly))
