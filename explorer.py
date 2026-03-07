"""
Explorer — Navigation Polymarket par events et recherche
=========================================================
Utilise /events comme source principale (les vrais groupes de marches).
L'endpoint /tags de Gamma est inutile (tags user random avec 0 marches).
"""

import json
import logging
import requests
from typing import Optional

from config import GAMMA_API, EXPLORER_DEFAULT_LIMIT, EXPLORER_VOLUME_MIN
from models import MarketView, EventInfo, CategoryInfo

logger = logging.getLogger(__name__)

# Cache events (valide ~5 min)
_events_cache: list[EventInfo] | None = None
_events_cache_ts: float = 0
_EVENTS_CACHE_TTL = 300  # 5 minutes

# Cache categories (valide ~1h, change rarement)
_categories_cache: list[CategoryInfo] | None = None
_categories_cache_ts: float = 0
_CATEGORIES_CACHE_TTL = 3600  # 1 heure


class Explorer:
    """Navigation dans l'univers Polymarket via Events."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"

    # ------------------------------------------------------------------
    # Events (la vraie source de donnees)
    # ------------------------------------------------------------------

    def _fetch_events(self, limit: int = 200, force: bool = False) -> list[EventInfo]:
        """Fetch les top events par volume. Cache 5min."""
        import time
        global _events_cache, _events_cache_ts

        if not force and _events_cache and (time.time() - _events_cache_ts < _EVENTS_CACHE_TTL):
            return _events_cache

        try:
            resp = self._session.get(
                f"{GAMMA_API}/events",
                params={
                    "limit": limit,
                    "active": "true",
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=20,
            )
            resp.raise_for_status()
            raw_events = resp.json()

            events = []
            for ev in raw_events:
                markets = []
                for m in ev.get("markets", []):
                    parsed = self._parse_market(m)
                    if parsed:
                        parsed.event_slug = ev.get("slug", "")
                        markets.append(parsed)

                # Trier les marches par volume decroissant
                markets.sort(key=lambda x: x.volume, reverse=True)

                events.append(EventInfo(
                    id=str(ev.get("id", "")),
                    title=ev.get("title", "?"),
                    slug=ev.get("slug", ""),
                    volume=float(ev.get("volume", 0) or 0),
                    liquidity=float(ev.get("liquidity", 0) or 0),
                    markets=markets,
                    end_date=ev.get("endDate", ""),
                    active=ev.get("active", True),
                ))

            if events:
                _events_cache = events
                _events_cache_ts = time.time()

            return events

        except Exception as e:
            logger.warning(f"Explorer: erreur fetch events -- {e}")
            return _events_cache or []

    # ------------------------------------------------------------------
    # Categories (via /categories API)
    # ------------------------------------------------------------------

    def get_categories(self, top_level_only: bool = True) -> list[CategoryInfo]:
        """Fetch les categories officielles Polymarket. Cache 1h."""
        import time
        global _categories_cache, _categories_cache_ts

        if _categories_cache and (time.time() - _categories_cache_ts < _CATEGORIES_CACHE_TTL):
            cats = _categories_cache
        else:
            try:
                resp = self._session.get(f"{GAMMA_API}/categories", timeout=10)
                resp.raise_for_status()
                raw = resp.json()

                cats = []
                for c in raw:
                    cats.append(CategoryInfo(
                        id=str(c.get("id", "")),
                        label=c.get("label", ""),
                        slug=c.get("slug", ""),
                        parent_id=str(c.get("parentCategory", "")),
                    ))
                _categories_cache = cats
                _categories_cache_ts = time.time()
            except Exception as e:
                logger.warning(f"Explorer: erreur fetch categories -- {e}")
                cats = _categories_cache or []

        if top_level_only:
            return [c for c in cats if not c.parent_id]
        return cats

    def get_subcategories(self, parent_id: str) -> list[CategoryInfo]:
        """Retourne les sous-categories d'une categorie parente."""
        all_cats = self.get_categories(top_level_only=False)
        return [c for c in all_cats if c.parent_id == parent_id]

    def get_events_by_category(self, slug: str, limit: int = 20) -> list[EventInfo]:
        """Fetch les events d'une categorie par slug (via tag_slug)."""
        try:
            resp = self._session.get(
                f"{GAMMA_API}/events",
                params={
                    "tag_slug": slug,
                    "limit": limit,
                    "active": "true",
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
                timeout=20,
            )
            resp.raise_for_status()
            raw_events = resp.json()

            events = []
            for ev in raw_events:
                markets = []
                for m in ev.get("markets", []):
                    parsed = self._parse_market(m)
                    if parsed:
                        parsed.event_slug = ev.get("slug", "")
                        markets.append(parsed)

                markets.sort(key=lambda x: x.volume, reverse=True)

                events.append(EventInfo(
                    id=str(ev.get("id", "")),
                    title=ev.get("title", "?"),
                    slug=ev.get("slug", ""),
                    volume=float(ev.get("volume", 0) or 0),
                    liquidity=float(ev.get("liquidity", 0) or 0),
                    markets=markets,
                    end_date=ev.get("endDate", ""),
                    active=ev.get("active", True),
                ))

            return events

        except Exception as e:
            logger.warning(f"Explorer: erreur fetch events by category '{slug}' -- {e}")
            return []

    # ------------------------------------------------------------------
    # Search (recherche dans les events + leurs marches)
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Recherche dans les events et marches par texte."""
        if not query or len(query) > 200:
            return []

        events = self._fetch_events()
        q = query.lower()
        results = []

        for ev in events:
            # Match sur le titre de l'event
            event_match = q in ev.title.lower() or q in ev.slug.lower()

            for m in ev.markets:
                if event_match or q in m.question.lower() or q in m.description.lower():
                    results.append(m)

        # Trier par volume decroissant
        results.sort(key=lambda x: x.volume, reverse=True)
        return results[:limit]

    def search_events(self, query: str, limit: int = 10) -> list[EventInfo]:
        """Recherche des events par titre."""
        if not query:
            return []

        events = self._fetch_events()
        q = query.lower()
        matched = [ev for ev in events
                   if q in ev.title.lower() or q in ev.slug.lower()]
        return matched[:limit]

    # ------------------------------------------------------------------
    # Browse (marches d'un event specifique)
    # ------------------------------------------------------------------

    def browse_event(self, event_id: str) -> EventInfo | None:
        """Recupere un event par ID avec ses marches."""
        events = self._fetch_events()
        for ev in events:
            if ev.id == event_id:
                return ev
        return None

    def browse_markets(self, event_id: str = None, volume_min: float = 0,
                       limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Marches d'un event, ou top marches globaux."""
        if event_id:
            ev = self.browse_event(event_id)
            if ev:
                markets = [m for m in ev.markets if m.volume >= volume_min]
                return markets[:limit]
            return []

        # Global: tous les marches de tous les events, tries par volume
        events = self._fetch_events()
        all_markets = []
        for ev in events:
            all_markets.extend(ev.markets)

        all_markets.sort(key=lambda x: x.volume, reverse=True)
        if volume_min > 0:
            all_markets = [m for m in all_markets if m.volume >= volume_min]
        return all_markets[:limit]

    # ------------------------------------------------------------------
    # Trending / Hot / New
    # ------------------------------------------------------------------

    def get_hot(self, limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Marches les plus actifs (top volume global)."""
        return self.browse_markets(volume_min=EXPLORER_VOLUME_MIN, limit=limit)

    def get_new(self, limit: int = EXPLORER_DEFAULT_LIMIT) -> list[MarketView]:
        """Marches les plus recents (derniers events)."""
        try:
            resp = self._session.get(
                f"{GAMMA_API}/events",
                params={
                    "limit": 30,
                    "active": "true",
                    "closed": "false",
                    "order": "startDate",
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            raw_events = resp.json()

            markets = []
            for ev in raw_events:
                for m in ev.get("markets", []):
                    parsed = self._parse_market(m)
                    if parsed:
                        parsed.event_slug = ev.get("slug", "")
                        markets.append(parsed)

            markets.sort(key=lambda x: x.volume, reverse=True)
            return markets[:limit]

        except Exception as e:
            logger.warning(f"Explorer: erreur get_new -- {e}")
            return []

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def get_price_history(self, token_id: str, interval: str = "max") -> list[dict]:
        """Historique de prix d'un token."""
        try:
            resp = self._session.get(
                f"{GAMMA_API}/prices",
                params={"token_id": token_id, "interval": interval},
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Explorer: erreur price_history -- {e}")
            return []

    # ------------------------------------------------------------------
    # Parser interne
    # ------------------------------------------------------------------

    def _parse_market(self, m: dict) -> MarketView | None:
        """Convertit un dict Gamma API en MarketView."""
        prices_str = m.get("outcomePrices", "")
        prices = []
        if prices_str:
            try:
                raw_prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                if isinstance(raw_prices, list):
                    prices = [float(p) for p in raw_prices[:10]]
            except (json.JSONDecodeError, ValueError):
                pass

        token_ids_str = m.get("clobTokenIds", "")
        token_ids = []
        if token_ids_str:
            try:
                raw_ids = json.loads(token_ids_str) if isinstance(token_ids_str, str) else token_ids_str
                if isinstance(raw_ids, list):
                    token_ids = [str(t) for t in raw_ids[:10]]
            except (json.JSONDecodeError, ValueError):
                pass

        outcomes_str = m.get("outcomes", "")
        outcomes = ["Yes", "No"]
        if outcomes_str:
            try:
                raw_outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                if isinstance(raw_outcomes, list) and raw_outcomes:
                    outcomes = [str(o) for o in raw_outcomes[:10]]
            except (json.JSONDecodeError, ValueError):
                pass

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
