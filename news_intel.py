"""
News Intel — Intelligence actionnable a partir des actualites
=============================================================
Analyse les NewsArticle pour un marche et produit un NewsIntel
avec direction, force du signal, velocity et sentiment.
"""

import re
import math
import logging
from datetime import datetime, timezone

from models import NewsArticle, NewsIntel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Classification d'un article par rapport a la question du marche
# ---------------------------------------------------------------------------

# Mots-cles de confirmation positive (l'evenement se produit)
_YES_KEYWORDS = [
    "will", "set to", "expected to", "likely to", "confirms", "confirmed",
    "agreed", "announces", "approval", "approved", "passes", "wins",
    "secures", "signs", "deal", "breakthrough", "succeeds", "victory",
    "accepts", "launches", "begins", "starts", "reaches", "achieves",
]

# Mots-cles de negation (l'evenement ne se produit pas)
_NO_KEYWORDS = [
    "won't", "will not", "unlikely", "rejects", "rejected", "denies",
    "denied", "fails", "failed", "blocks", "blocked", "opposes",
    "cancels", "cancelled", "postpones", "postponed", "delays", "delayed",
    "collapses", "abandons", "scraps", "withdraws", "loses", "defeat",
    "impossible", "rules out",
]

_SENTIMENT_SCORE = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}


def _classify_article(article: NewsArticle, question_lower: str) -> str:
    """Classe un article comme 'yes', 'no', ou 'neutral' par rapport a la question."""
    text = f"{article.title} {article.description}".lower()

    # Compter les signaux
    yes_signals = sum(1 for kw in _YES_KEYWORDS if kw in text)
    no_signals = sum(1 for kw in _NO_KEYWORDS if kw in text)

    # Ponderer par le sentiment Perigon
    if article.sentiment == "positive":
        yes_signals += 1
    elif article.sentiment == "negative":
        no_signals += 1

    if yes_signals > no_signals:
        return "yes"
    elif no_signals > yes_signals:
        return "no"
    return "neutral"


def _recency_weight(article: NewsArticle) -> float:
    """Poids de recence : 1.0 pour < 1h, decroit vers 0.1 a 7 jours."""
    now = datetime.now(timezone.utc)
    pub = article.pub_date
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    age_h = max(0, (now - pub).total_seconds() / 3600)
    # Decay exponentiel : demi-vie = 12h
    return max(0.1, math.exp(-0.058 * age_h))


# ---------------------------------------------------------------------------
# Fonction principale
# ---------------------------------------------------------------------------

def analyze_news(articles: list[NewsArticle], market_question: str) -> NewsIntel:
    """Analyse les articles et produit un resume actionnable pour un marche.

    Args:
        articles: Liste de NewsArticle pour ce marche
        market_question: La question du marche (ex: "Will Lakers win Game 7?")

    Returns:
        NewsIntel avec direction, force, velocity, sentiment
    """
    if not articles:
        return NewsIntel(
            articles=[],
            signal_direction="NO_DATA",
            signal_strength=0.0,
            velocity=0,
            avg_sentiment=0.0,
            freshest_age_h=float("inf"),
        )

    q_lower = market_question.lower()
    now = datetime.now(timezone.utc)

    # Classifier chaque article
    yes_score = 0.0
    no_score = 0.0
    sentiment_sum = 0.0
    t1_recent_count = 0    # T1 dans les 2 dernieres heures
    freshest_age_h = float("inf")

    for art in articles:
        pub = art.pub_date
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        age_h = max(0, (now - pub).total_seconds() / 3600)
        freshest_age_h = min(freshest_age_h, age_h)

        # Velocity : T1 recents
        if art.source_tier == 1 and age_h <= 2.0:
            t1_recent_count += 1

        # Classification
        direction = _classify_article(art, q_lower)
        weight = _recency_weight(art)
        tier_weight = 2.0 if art.source_tier == 1 else 1.0

        if direction == "yes":
            yes_score += weight * tier_weight
        elif direction == "no":
            no_score += weight * tier_weight

        sentiment_sum += _SENTIMENT_SCORE.get(art.sentiment, 0.0)

    # Direction du signal
    total_directional = yes_score + no_score
    if total_directional == 0:
        signal_direction = "MIXED"
    elif yes_score > no_score * 1.5:
        signal_direction = "CONFIRMS_YES"
    elif no_score > yes_score * 1.5:
        signal_direction = "CONFIRMS_NO"
    else:
        signal_direction = "MIXED"

    # Force du signal
    # Base = (2*t1_count + t2_count) * avg_recency * sentiment_alignment
    t1_count = sum(1 for a in articles if a.source_tier == 1)
    t2_count = sum(1 for a in articles if a.source_tier == 2)
    base_count = 2 * t1_count + t2_count

    avg_recency = sum(_recency_weight(a) for a in articles) / len(articles)

    # Sentiment alignment : articles vont-ils dans la meme direction ?
    if total_directional > 0:
        dominant = max(yes_score, no_score)
        alignment = dominant / total_directional
    else:
        alignment = 0.5

    raw_strength = base_count * avg_recency * alignment

    # Velocity bonus
    velocity_multiplier = 1.0
    if t1_recent_count >= 5:
        velocity_multiplier = 2.0
    elif t1_recent_count >= 3:
        velocity_multiplier = 1.5

    raw_strength *= velocity_multiplier

    # Normaliser entre 0 et 1 (sigmoid-like, cap a ~20 articles)
    signal_strength = min(1.0, raw_strength / 15.0)

    # Sentiment moyen
    avg_sentiment = sentiment_sum / len(articles) if articles else 0.0

    return NewsIntel(
        articles=articles,
        signal_direction=signal_direction,
        signal_strength=signal_strength,
        velocity=t1_recent_count,
        avg_sentiment=avg_sentiment,
        freshest_age_h=freshest_age_h,
    )
