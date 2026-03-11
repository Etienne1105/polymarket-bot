"""
Edge Detection Engine — Le coeur de RupeeHunter v4
====================================================
Detecte la divergence entre le prix marche et la probabilite
reelle estimee a partir de Navi, news, scanner et MAPEM.
"""

import logging
from dataclasses import dataclass, field

from models import Opportunity, NewsIntel

logger = logging.getLogger(__name__)


@dataclass
class EdgeResult:
    """Resultat de l'analyse d'edge."""
    edge: float              # estimated_prob - market_price
    estimated_prob: float    # notre meilleure estimation
    confidence: float        # 0.0 a 1.0
    grade: str               # A/B/C/D/F
    components: dict = field(default_factory=dict)  # breakdown par source


def _news_signal_to_prob(news_intel: NewsIntel, market_price: float) -> float:
    """Convertit un signal news en estimation de probabilite.

    Logique : le signal news ajuste le prix marche actuel.
    - CONFIRMS_YES + signal fort → pousse la prob vers le haut
    - CONFIRMS_NO + signal fort → pousse la prob vers le bas
    - MIXED/NO_DATA → reste pres du prix marche
    """
    if news_intel.signal_direction == "NO_DATA":
        return market_price

    strength = news_intel.signal_strength
    # Direction de l'ajustement
    if news_intel.signal_direction == "CONFIRMS_YES":
        # Pousse vers 1.0
        adjustment = strength * (1.0 - market_price) * 0.5
        return min(0.98, market_price + adjustment)
    elif news_intel.signal_direction == "CONFIRMS_NO":
        # Pousse vers 0.0
        adjustment = strength * market_price * 0.5
        return max(0.02, market_price - adjustment)
    else:
        # MIXED : leger ajustement par sentiment
        sentiment_adj = news_intel.avg_sentiment * strength * 0.1
        return max(0.02, min(0.98, market_price + sentiment_adj))


def _scanner_estimated_prob(opp: Opportunity) -> float:
    """Extrait la probabilite implicite du scanner."""
    if opp.estimated_value > 0:
        return min(0.98, max(0.02, opp.estimated_value))
    return opp.current_price


def _mapem_category_prior(opp: Opportunity) -> float:
    """Prior categoriel MAPEM : si le MAPEM score est haut,
    la categorie est previsible, donc on fait confiance au prix.
    Si bas, plus d'incertitude.
    """
    if opp.mapem_score < 0:
        return opp.current_price

    # Score MAPEM haut (>70) = previsible → prix marche fiable
    # Score MAPEM bas (<30) = imprevisible → prior neutre (0.5)
    mapem_norm = opp.mapem_score / 100.0
    return mapem_norm * opp.current_price + (1 - mapem_norm) * 0.5


def compute_edge(opp: Opportunity, news_intel: NewsIntel,
                 navi_result: dict | None = None) -> EdgeResult:
    """Calcule l'edge d'une opportunite.

    Composantes et poids :
    | Composante          | Avec Navi | Sans Navi |
    |---------------------|-----------|-----------|
    | Navi prob_estimee   | 50%       | 0%        |
    | News signal         | 25%       | 45%       |
    | Scanner est. value  | 15%       | 35%       |
    | MAPEM category prior| 10%       | 20%       |

    Returns:
        EdgeResult avec edge, estimated_prob, confidence, grade
    """
    has_navi = (navi_result is not None and
                navi_result.get("prob_estimee", 0) > 0)

    # Aussi utiliser opp.navi_prob si deja set
    if not has_navi and opp.navi_prob > 0:
        navi_result = {"prob_estimee": opp.navi_prob,
                       "verdict": opp.navi_verdict}
        has_navi = True

    components = {}

    # 1. Navi
    navi_prob = 0.0
    if has_navi:
        navi_prob = navi_result.get("prob_estimee", 0)
        components["navi"] = navi_prob

    # 2. News signal → prob
    news_prob = _news_signal_to_prob(news_intel, opp.current_price)
    components["news"] = news_prob

    # 3. Scanner estimated value
    scanner_prob = _scanner_estimated_prob(opp)
    components["scanner"] = scanner_prob

    # 4. MAPEM category prior
    mapem_prior = _mapem_category_prior(opp)
    components["mapem"] = mapem_prior

    # Weighted average
    if has_navi:
        estimated_prob = (
            0.50 * navi_prob +
            0.25 * news_prob +
            0.15 * scanner_prob +
            0.10 * mapem_prior
        )
    else:
        estimated_prob = (
            0.45 * news_prob +
            0.35 * scanner_prob +
            0.20 * mapem_prior
        )

    # Edge = estimated - market
    edge = estimated_prob - opp.current_price

    # Confidence
    # Base : combien de sources convergent ?
    probs = [news_prob, scanner_prob, mapem_prior]
    if has_navi:
        probs.append(navi_prob)

    # Variance des estimations → faible variance = haute confiance
    avg_prob = sum(probs) / len(probs)
    variance = sum((p - avg_prob) ** 2 for p in probs) / len(probs)
    convergence = max(0, 1.0 - variance * 10)  # 0 variance = 1.0

    # Bonus confiance si Navi est present
    navi_bonus = 0.2 if has_navi else 0.0

    # Bonus confiance si news recentes et alignees
    news_bonus = 0.0
    if news_intel.signal_strength > 0.3 and news_intel.signal_direction != "MIXED":
        news_bonus = 0.1
    if news_intel.velocity >= 3:
        news_bonus += 0.1

    confidence = min(1.0, convergence * 0.7 + navi_bonus + news_bonus)

    # Grading
    navi_verdict = ""
    if has_navi:
        navi_verdict = navi_result.get("verdict", "")

    # Edge negatif = marche surprice, jamais acheter
    if edge < 0:
        grade = "D"
    else:
        grade = _compute_grade(edge, confidence, navi_verdict, news_intel.velocity)

    return EdgeResult(
        edge=edge,
        estimated_prob=estimated_prob,
        confidence=confidence,
        grade=grade,
        components=components,
    )


def _compute_grade(abs_edge: float, confidence: float,
                   navi_verdict: str, velocity: int) -> str:
    """Determine le grade d'edge.

    - A : |edge| > 0.15 ET confidence > 0.7 ET Navi GO
    - B : |edge| > 0.10 ET confidence > 0.5
    - C : |edge| > 0.05 (edge faible mais present)
    - D : |edge| < 0.05 (pas d'edge significatif)
    - F : Navi dit PIEGE (override tout)
    """
    if navi_verdict == "PIEGE":
        return "F"
    if abs_edge > 0.15 and confidence > 0.7 and navi_verdict == "GO":
        return "A"
    if abs_edge > 0.10 and confidence > 0.5:
        return "B"
    if abs_edge > 0.05:
        return "C"
    return "D"
