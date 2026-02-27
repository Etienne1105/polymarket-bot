"""
Explorer 🔭 — Navigation Polymarket par tags, events et recherche
=================================================================
Permet de naviguer Polymarket comme sur le site : catégories,
événements, recherche libre, marchés tendance.
"""

import json
import logging
import requests
from typing import Optional

from config import GAMMA_API, EXPLORER_DEFAULT_LIMIT, EXPLORER_VOLUME_MIN
from models import MarketView, TagInfo

logger = logging.getLogger(__name__)

# Cache léger pour les tags (ne changent pas souvent)
_tags_cache: list[TagInfo] | None = None


class Explorer:
    """Navigation dans l'univers Polymarket."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

    # ------------------------------------------------------------------
    # Tags (catégories)
    # ------------------------------------------------------------------

    def get_tags(self, limit: int = 50, offset: int = 0) -> list[TagInfo]:
        """Récupère les tags Polymarket (catégories)."""
        global _tags_cache
        if _tags_cache and offset == 0 and limit <= len(_tags_cache):
            return _tags_cache[:limit]

        try:
            resp = self._session.get(
                f"{GAMMA_API}/tags",
                params={"limit": limit, "offset": offset},
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()

            tags = []
            for t in raw:
                tags.append(TagInfo(
                    id=str(t.get("id", "")),
                    label=t.get("label", t.get("name", "?")),
                    slug=t.get("slug", ""),
                    market_count=int(t.get("market_count", 0)),
                ))

            if offset == 0 and tags:
                _tags_cache = tags

            return tags

        except Exception as e:
            logger.warning(f"Explorer: erreur get_tags — {e}")
            return []

    def search_tags(self, query: str) -> list[TagInfo]:
        """Cherche dans les tags par nom."""
        tags = self.get_tags(limit=200)
        q = query.lower()
        return [t for t in tags if q in t.label.lower() or q in t.slug.lower()]

    # ------------------------------------------------------------------
    # Events (événements = groupes de marchés)
    # ------------------------------------------------------------------

    def browse_events(self, tag_id: str = None, order: str = "volume",
                      limit: int = EXPLORER_DEFAULT_LIMIT,
                      offset: int = 0, active: bool = True) -> list[dict]:
        """Récupère les événements depuis Gamma API."""
        params = {
            "limit": limit,
            "offset": offset,
            "order": order,
            "ascending": "false",
            "active": str(active).lower(),
            "closed": "false",
        }
        if tag_id:
            params["tag_id"] = tag_id

        try:
            resp = self._session.get(
                f"{GAMMA_API}/events",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Explorer: erreur browse_events — {e}")
            return []

    # ------------------------------------------------------------------
    # Markets (marchés filtrés)
    # ------------------------------------------------------------------

    def browse_markets(self, tag_id: str = None, volume_min: float = EXPLORER_VOLUME_MIN,
                       order: str = "volume", limit: int = EXPLORER_DEFAULT_LIMIT,
                       offset: int = 0, end_date_max: str = None) -> list[MarketView]:
        """Récupère des marchés filtrés par tag, volume, etc."""
        params = {
            "limit": limit,
            "offset": offset,
            "active": "true",
            "closed": "false",
            "order": order,
            "ascending": "false",
        }
        if tag_id:
            params["tag_id"] = tag_id
        if volume_min > 0:
            params["volume_num_min"] = int(volume_min)
        if end_date_max:
            params["end_date_max"] = end_date_max

        try:
            resp = self._session.get(
                f"{GAMMA_API}/markets",
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            raw_markets = resp.json()
            return [self._parse_market(m) for m in raw_markets if self._parse_market(m)]
        except Exception as e:
            logger.warning(f"Explorer: erreur browse_markets — {e}")
            return []

    # ------------------------------------------------------------------
    # Search (recherche libre)
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Recherche libre de marchés par texte."""
        if not query or len(query) > 200:
            return []

        # Essayer d'abord /markets avec le tag filter
        try:
            resp = self._session.get(
                f"{GAMMA_API}/markets",
                params={
                    "limit": limit,
                    "active": "true",
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            all_markets = resp.json()

            # Filtrer côté client par question
            q = query.lower()
            matched = [m for m in all_markets if q in m.get("question", "").lower()
                       or q in m.get("description", "").lower()]

            if matched:
                return [self._parse_market(m) for m in matched[:limit] if self._parse_market(m)]
        except Exception as e:
            logger.debug(f"Explorer: search filter fallback — {e}")

        # Fallback: recherche par l'endpoint dédié
        try:
            resp = self._session.get(
                f"{GAMMA_API}/markets",
                params={
                    "limit": 100,
                    "active": "true",
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            all_markets = resp.json()

            q = query.lower()
            matched = [m for m in all_markets if q in m.get("question", "").lower()]
            return [self._parse_market(m) for m in matched[:limit] if self._parse_market(m)]
        except Exception as e:
            logger.warning(f"Explorer: erreur search — {e}")
            return []

    # ------------------------------------------------------------------
    # Trending / Hot / New
    # ------------------------------------------------------------------

    def get_hot(self, limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Marchés les plus actifs (triés par volume)."""
        return self.browse_markets(order="volume", limit=limit, volume_min=5000)

    def get_new(self, limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Marchés les plus récents."""
        return self.browse_markets(order="startDate", limit=limit, volume_min=100)

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def get_price_history(self, token_id: str, interval: str = "max") -> list[dict]:
        """Récupère l'historique de prix d'un token."""
        try:
            resp = self._session.get(
                f"{GAMMA_API}/prices",
                params={"token_id": token_id, "interval": interval},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Explorer: erreur price_history — {e}")
            return []

    # ------------------------------------------------------------------
    # Parser interne
    # ------------------------------------------------------------------

    def _parse_market(self, m: dict) -> MarketView | None:
        """Convertit un dict Gamma API en MarketView."""
        # Parser les prix
        prices_str = m.get("outcomePrices", "")
        prices = []
        if prices_str:
            try:
                raw_prices = json.loads(prices_str)
                if isinstance(raw_prices, list):
                    prices = [float(p) for p in raw_prices[:10]]
            except (json.JSONDecodeError, ValueError):
                pass

        # Parser les token IDs
        token_ids_str = m.get("clobTokenIds", "")
        token_ids = []
        if token_ids_str:
            try:
                raw_ids = json.loads(token_ids_str)
                if isinstance(raw_ids, list):
                    token_ids = [str(t) for t in raw_ids[:10]]
            except (json.JSONDecodeError, ValueError):
                pass

        # Parser les outcomes
        outcomes_str = m.get("outcomes", "")
        outcomes = ["Yes", "No"]
        if outcomes_str:
            try:
                raw_outcomes = json.loads(outcomes_str)
                if isinstance(raw_outcomes, list) and raw_outcomes:
                    outcomes = [str(o) for o in raw_outcomes[:10]]
            except (json.JSONDecodeError, ValueError):
                pass

        # Parser les tags
        tags = []
        raw_tags = m.get("tags", [])
        if isinstance(raw_tags, list):
            for t in raw_tags:
                if isinstance(t, dict):
                    tags.append(t.get("label", t.get("slug", "?")))
                elif isinstance(t, str):
                    tags.append(t)

        question = m.get("question", "")
        if not question:
            return None

        return MarketView(
            question=question,
            condition_id=m.get("conditionId", ""),
            slug=m.get("slug", ""),
            volume=float(m.get("volume", 0) or 0),
            liquidity=float(m.get("liquidity", 0) or 0),
            end_date=m.get("endDate", m.get("end_date_iso", "")),
            prices=prices,
            token_ids=token_ids,
            description=m.get("description", ""),
            event_slug=m.get("eventSlug", ""),
            tags=tags,
            neg_risk=m.get("negRisk", False),
            outcomes=outcomes,
        )


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_explorer_instance: Explorer | None = None


def get_explorer() -> Explorer:
    """Retourne l'instance singleton de l'Explorer."""
    global _explorer_instance
    if _explorer_instance is None:
        _explorer_instance = Explorer()
    return _explorer_instance
