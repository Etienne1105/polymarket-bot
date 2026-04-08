"""
News — Contexte actualites en temps reel
=========================================
Source primaire : Event Registry (articles structures, 2000 req/mois).
Fallback 1 : Perigon API.
Fallback 2 : DuckDuckGo HTML (filtre par sources tier 1-2).
Cache 15 min par requete.

v4 : fetch_articles() retourne des NewsArticle structures.
     fetch_headlines() appelle fetch_articles() puis formate (backward compat).
"""

import re
import os
import json
import time
import html as html_mod
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from models import NewsArticle

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sources fiables — classees par tier (pour fallback DDG)
# ---------------------------------------------------------------------------

_TIER1 = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    "nytimes.com", "washingtonpost.com", "wsj.com",
    "economist.com", "ft.com", "bloomberg.com",
    "theguardian.com", "aljazeera.com",
}

_TIER2 = {
    # US
    "cnbc.com", "cnn.com", "cbsnews.com", "nbcnews.com", "abcnews.go.com",
    "politico.com", "thehill.com", "axios.com", "npr.org", "pbs.org",
    "usatoday.com", "time.com", "forbes.com", "businessinsider.com",
    "vox.com", "theatlantic.com",
    # Crypto / finance
    "coindesk.com", "cointelegraph.com", "theblock.co", "decrypt.co",
    "defiant.io", "blockworks.co", "dlnews.com",
    # Canada
    "globalnews.ca", "cbc.ca", "thestar.com",
    # Europe
    "lemonde.fr", "lefigaro.fr", "spiegel.de", "elpais.com",
    "corriere.it", "skynews.com.au", "sky.com",
    # Asie
    "scmp.com", "japantimes.co.jp", "straitstimes.com",
    # Science / tech
    "nature.com", "sciencemag.org", "wired.com", "arstechnica.com",
    "techcrunch.com", "theverge.com",
}

_ALL_TRUSTED = _TIER1 | _TIER2

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_news_cache: dict = {}          # headline strings (backward compat)
_articles_cache: dict = {}      # v4: NewsArticle objects
_NEWS_CACHE_TTL = 900  # 15 minutes

_STOP_WORDS = {
    "will", "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "by", "of", "to", "in", "on", "at", "for", "and", "or", "not", "no",
    "do", "does", "did", "has", "have", "had", "this", "that", "it",
    "with", "from", "as", "but", "if", "its", "than", "more", "before",
    "after", "during", "between", "about", "into", "over", "under",
    "end", "before", "above", "below", "up", "down", "out", "off",
    "there", "here", "when", "where", "how", "what", "which", "who",
    "whom", "why", "can", "could", "would", "should", "may", "might",
    "shall", "must", "need", "get", "got", "go", "going", "come",
    "yes", "happen", "take", "place",
}


def _normalize_query(query: str) -> str:
    """Normalise une requete pour le cache."""
    words = re.sub(r'[^\w\s]', '', query.lower()).split()
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 1]
    return " ".join(keywords[:6])


def _build_search_query(query: str) -> str:
    """Construit une requete de recherche optimisee pour Perigon/DDG.

    Extrait les mots-cles significatifs de la question du marche,
    vire les stop words et le bruit des questions yes/no.
    """
    words = re.sub(r'[^\w\s]', '', query.lower()).split()
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    # Garder max 5 mots-cles pour une recherche efficace
    return " ".join(keywords[:5])


# ---------------------------------------------------------------------------
# Event Registry (source primaire v4)
# ---------------------------------------------------------------------------

_ER_WARNING_THRESHOLD = 1500  # alerte a 75% du quota mensuel
_ER_QUOTA_FILE = os.path.join(os.path.dirname(__file__), ".er_quota.json")


def _load_er_quota() -> dict:
    """Charge le compteur de quota ER persistant."""
    try:
        with open(_ER_QUOTA_FILE, "r") as f:
            data = json.load(f)
        # Reset si mois different
        if data.get("month") != datetime.now().strftime("%Y-%m"):
            return {"month": datetime.now().strftime("%Y-%m"), "calls": 0}
        return data
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {"month": datetime.now().strftime("%Y-%m"), "calls": 0}


def _save_er_quota(data: dict):
    """Sauvegarde le compteur de quota ER."""
    try:
        with open(_ER_QUOTA_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _get_er_key() -> str | None:
    """Lit la cle API Event Registry depuis le Keychain macOS."""
    try:
        from keychain import get_secret
        key = get_secret("EVENTREGISTRY_API_KEY")
        return key if key else None
    except Exception:
        return None


def _search_eventregistry_articles(query: str, max_results: int) -> list[NewsArticle]:
    """Recherche via Event Registry API. Retourne des NewsArticle structures."""
    api_key = _get_er_key()
    if not api_key:
        return []

    search_query = _build_search_query(query)
    from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        resp = requests.post(
            "https://eventregistry.org/api/v1/article/getArticles",
            json={
                "action": "getArticles",
                "keyword": search_query,
                "dateStart": from_date,
                "articlesPage": 1,
                "articlesCount": min(max_results * 5, 100),
                "articlesSortBy": "date",
                "articlesSortByAsc": False,
                "dataType": ["news"],
                "lang": "eng",
                "apiKey": api_key,
            },
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()

        quota = _load_er_quota()
        quota["calls"] += 1
        _save_er_quota(quota)
        if quota["calls"] >= _ER_WARNING_THRESHOLD:
            logger.warning(
                f"Event Registry quota warning: {quota['calls']}/2000 this month"
            )

        raw_articles = (
            data.get("articles", {}).get("results", [])
        )
        if not raw_articles:
            return []

        result = []
        seen = set()

        for art in raw_articles:
            if len(result) >= max_results:
                break

            title = (art.get("title") or "").strip()
            if not title:
                continue

            title_key = re.sub(r'\W+', '', title.lower())
            if title_key in seen:
                continue
            seen.add(title_key)

            # Domain extraction — filtrer les sources non-fiables
            source = art.get("source", {})
            domain = (source.get("uri") or "").replace("www.", "").lower()
            if not domain or domain not in _ALL_TRUSTED:
                continue  # source non-fiable ou inconnue
            tier = 1 if domain in _TIER1 else 2

            # Sentiment ER: float -1 a +1
            raw_sent = art.get("sentiment")
            if isinstance(raw_sent, (int, float)):
                if raw_sent > 0.1:
                    sentiment = "positive"
                elif raw_sent < -0.1:
                    sentiment = "negative"
                else:
                    sentiment = "neutral"
            else:
                sentiment = "neutral"

            # Date parse
            pub_date_str = art.get("dateTime") or art.get("date") or ""
            pub_date = _parse_iso_date(pub_date_str)

            result.append(NewsArticle(
                title=title,
                description=(art.get("description") or (art.get("body") or "")[:300]).strip(),
                source_domain=domain,
                source_tier=tier,
                pub_date=pub_date,
                sentiment=sentiment,
                url=art.get("url", ""),
            ))

        return result

    except Exception as e:
        logger.debug(f"Event Registry fetch failed for '{query[:50]}': {e}")
        return []


def er_quota_status() -> dict:
    """Retourne l'etat du quota Event Registry (persistant par mois)."""
    quota = _load_er_quota()
    return {
        "month": quota["month"],
        "calls": quota["calls"],
        "monthly_quota": 2000,
        "remaining": max(0, 2000 - quota["calls"]),
        "warning_threshold": _ER_WARNING_THRESHOLD,
        "has_key": _get_er_key() is not None,
    }


# ---------------------------------------------------------------------------
# Perigon API (fallback 1)
# ---------------------------------------------------------------------------

def _get_perigon_key() -> str | None:
    """Lit la cle API Perigon depuis le Keychain macOS."""
    try:
        from keychain import get_secret
        key = get_secret("PERIGON_API_KEY")
        return key if key else None
    except Exception:
        return None


def _parse_iso_date(date_str: str) -> datetime:
    """Parse une date ISO 8601 depuis Perigon/ER.
    Fallback = 7 jours (recency_weight ~0.1, pas artificiellement frais).
    """
    if not date_str:
        return datetime.now(timezone.utc) - timedelta(days=7)
    try:
        # Perigon format: "2026-03-08T12:00:00Z" ou avec +00:00
        cleaned = date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc) - timedelta(days=7)


def _search_perigon_articles(query: str, max_results: int) -> list[NewsArticle]:
    """Recherche via Perigon API. Retourne des NewsArticle structures."""
    api_key = _get_perigon_key()
    if not api_key:
        return []

    source_filter = ",".join(sorted(_ALL_TRUSTED))
    from_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    search_query = _build_search_query(query)

    try:
        resp = requests.get(
            "https://api.goperigon.com/v1/all",
            params={
                "apiKey": api_key,
                "q": search_query,
                "size": max_results * 2,
                "sortBy": "relevance",
                "from": from_date,
                "source": source_filter,
                "showReprints": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        raw_articles = data.get("articles", [])
        if not raw_articles:
            return []

        result = []
        seen = set()

        for art in raw_articles:
            if len(result) >= max_results:
                break

            title = (art.get("title") or "").strip()
            if not title:
                continue

            title_key = re.sub(r'\W+', '', title.lower())
            if title_key in seen:
                continue
            seen.add(title_key)

            source = art.get("source", {})
            domain = source.get("domain", "").replace("www.", "")
            tier = 1 if domain in _TIER1 else 2

            # Perigon sentiment: peut etre un dict {positive, negative, neutral}
            # ou un string simple
            raw_sentiment = art.get("sentiment")
            if isinstance(raw_sentiment, dict):
                pos = raw_sentiment.get("positive", 0) or 0
                neg = raw_sentiment.get("negative", 0) or 0
                neu = raw_sentiment.get("neutral", 0) or 0
                if pos > neg and pos > neu:
                    sentiment = "positive"
                elif neg > pos and neg > neu:
                    sentiment = "negative"
                else:
                    sentiment = "neutral"
            elif isinstance(raw_sentiment, str):
                sentiment = raw_sentiment.lower()
                if sentiment not in ("positive", "negative", "neutral"):
                    sentiment = "neutral"
            else:
                sentiment = "neutral"

            result.append(NewsArticle(
                title=title,
                description=(art.get("description") or "")[:300].strip(),
                source_domain=domain,
                source_tier=tier,
                pub_date=_parse_iso_date(art.get("pubDate", "")),
                sentiment=sentiment,
                url=art.get("url", ""),
            ))

        return result

    except Exception as e:
        logger.debug(f"Perigon fetch failed for '{query[:50]}': {e}")
        return []


def _search_perigon(query: str, max_results: int) -> str:
    """Recherche via Perigon API. Retourne headlines formatees ou ''.
    Wrapper backward-compat qui appelle _search_perigon_articles().
    """
    articles = _search_perigon_articles(query, max_results)
    return _format_articles_as_headlines(articles)


def _perigon_source_label(domain: str) -> str:
    """Nom court pour un domaine Perigon."""
    return _SOURCE_LABELS.get(domain, domain.split(".")[0].capitalize())


# ---------------------------------------------------------------------------
# DuckDuckGo HTML (fallback)
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Extrait le domaine d'une URL DuckDuckGo redirect."""
    match = re.search(r'uddg=([^&]+)', url)
    if match:
        decoded = unquote(match.group(1))
        domain_match = re.search(r'https?://(?:www\.)?([^/]+)', decoded)
        if domain_match:
            return domain_match.group(1).lower()
    domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if domain_match:
        return domain_match.group(1).lower()
    return ""


def _search_ddg(query: str, max_results: int) -> str:
    """Recherche DuckDuckGo HTML, filtre par sources fiables."""
    try:
        search_query = _build_search_query(query)
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": search_query + " news 2026", "t": "h_", "ia": "news"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()

        hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', resp.text)
        titles = re.findall(r'class="result__a"[^>]*>([^<]+)<', resp.text)
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.DOTALL
        )

        headlines = []
        seen = set()

        for i, title in enumerate(titles):
            if len(headlines) >= max_results:
                break

            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            if not clean_title:
                continue

            title_key = re.sub(r'\W+', '', clean_title.lower())
            if title_key in seen:
                continue

            domain = ""
            if i < len(hrefs):
                domain = _extract_domain(hrefs[i])

            if domain and domain not in _ALL_TRUSTED:
                continue

            seen.add(title_key)

            clean_snippet = ""
            if i < len(snippets):
                clean_snippet = re.sub(r'<[^>]+>', '', snippets[i]).strip()

            source = _SOURCE_LABELS.get(domain, domain.split(".")[0].capitalize()) if domain else "?"
            tier = "T1" if domain in _TIER1 else "T2"

            line = f"- [{source}|{tier}] {clean_title}"
            if clean_snippet:
                line += f": {clean_snippet[:200]}"
            headlines.append(line)

        if not headlines:
            logger.debug(f"No trusted sources found for '{query[:50]}'")

        return "\n".join(headlines)

    except Exception as e:
        logger.debug(f"DDG fetch failed for '{query[:50]}': {e}")
        return ""


# ---------------------------------------------------------------------------
# Labels de sources (partage entre Perigon et DDG)
# ---------------------------------------------------------------------------

_SOURCE_LABELS = {
    "reuters.com": "Reuters", "apnews.com": "AP",
    "bbc.com": "BBC", "bbc.co.uk": "BBC",
    "nytimes.com": "NYT", "washingtonpost.com": "WaPo",
    "wsj.com": "WSJ", "bloomberg.com": "Bloomberg",
    "ft.com": "FT", "economist.com": "Economist",
    "theguardian.com": "Guardian", "aljazeera.com": "Al Jazeera",
    "cnbc.com": "CNBC", "cnn.com": "CNN",
    "cbsnews.com": "CBS", "nbcnews.com": "NBC",
    "abcnews.go.com": "ABC", "politico.com": "Politico",
    "thehill.com": "The Hill", "axios.com": "Axios",
    "npr.org": "NPR", "forbes.com": "Forbes",
    "coindesk.com": "CoinDesk", "cointelegraph.com": "CoinTelegraph",
    "theblock.co": "The Block", "decrypt.co": "Decrypt",
    "blockworks.co": "Blockworks", "dlnews.com": "DL News",
    "globalnews.ca": "Global", "cbc.ca": "CBC",
    "lemonde.fr": "Le Monde", "scmp.com": "SCMP",
}

# ---------------------------------------------------------------------------
# Formatage articles → headlines (backward compat)
# ---------------------------------------------------------------------------

def _format_articles_as_headlines(articles: list[NewsArticle]) -> str:
    """Formate une liste de NewsArticle en string headlines."""
    if not articles:
        return ""
    lines = []
    for art in articles:
        source_label = _perigon_source_label(art.source_domain) if art.source_domain else "?"
        tier = f"T{art.source_tier}"
        line = f"- [{source_label}|{tier}] {art.title}"
        if art.description:
            line += f": {art.description[:200]}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------

def fetch_articles(query: str, max_results: int = 5) -> list[NewsArticle]:
    """Fetch des articles structures — Perigon d'abord, DDG en fallback.

    Retourne une liste de NewsArticle. Resultat cache 15 min.
    """
    normalized = _normalize_query(query)

    if normalized in _articles_cache:
        ts, cached = _articles_cache[normalized]
        if time.time() - ts < _NEWS_CACHE_TTL:
            return cached

    # Event Registry = source primaire
    articles = _search_eventregistry_articles(query, max_results)

    # Fallback 1 : Perigon
    if not articles:
        articles = _search_perigon_articles(query, max_results)

    # Fallback 2 : DDG
    if not articles:
        articles = _ddg_to_articles(query, max_results)

    _articles_cache[normalized] = (time.time(), articles)
    return articles


def fetch_articles_batch(questions: list[str], max_results: int = 3) -> dict[str, list[NewsArticle]]:
    """Fetch des articles structures pour plusieurs questions.

    Retourne {question: list[NewsArticle]}.
    Dedup queries similaires (meme normalized key = 1 seul appel).
    """
    results = {}
    seen_keys = {}
    for q in questions:
        key = _normalize_query(q)
        if key in seen_keys:
            results[q] = seen_keys[key]
        else:
            articles = fetch_articles(q, max_results)
            results[q] = articles
            seen_keys[key] = articles
    return results


def fetch_headlines(query: str, max_results: int = 5) -> str:
    """Fetch des headlines recentes — backward compat.

    Appelle fetch_articles() puis formate en string.
    """
    articles = fetch_articles(query, max_results)
    return _format_articles_as_headlines(articles)


def fetch_headlines_batch(questions: list[str], max_results: int = 3) -> dict[str, str]:
    """Fetch des headlines pour plusieurs questions — backward compat.

    Retourne {question: headlines_str}.
    """
    articles_batch = fetch_articles_batch(questions, max_results)
    return {q: _format_articles_as_headlines(arts) for q, arts in articles_batch.items()}


def _ddg_to_articles(query: str, max_results: int) -> list[NewsArticle]:
    """Convertit les resultats DDG en NewsArticle (infos limitees)."""
    headline_str = _search_ddg(query, max_results)
    if not headline_str:
        return []

    articles = []
    now = datetime.now(timezone.utc)
    for line in headline_str.split("\n"):
        m = re.match(r'^- \[([^|]+)\|T(\d)\] (.+?)(?:: (.+))?$', line)
        if m:
            articles.append(NewsArticle(
                title=m.group(3).strip(),
                description=(m.group(4) or "").strip(),
                source_domain="",
                source_tier=int(m.group(2)),
                pub_date=now,  # DDG ne donne pas de date precise
                sentiment="neutral",
            ))
    return articles


# ---------------------------------------------------------------------------
# Trending headlines (DDG, zero coût API) — pour stratégie breaking
# ---------------------------------------------------------------------------

_trending_cache: dict = {}
_TRENDING_CACHE_TTL = 600  # 10 min

_TRENDING_QUERIES = [
    "Trump tariffs trade war",
    "congress senate bill vote",
    "federal reserve economy inflation",
    "Ukraine Russia ceasefire war",
    "election 2026 polls",
    "crypto bitcoin SEC regulation",
    "AI artificial intelligence OpenAI",
    "climate hurricane earthquake disaster",
]

_HOMEPAGE_RE = re.compile(
    r'breaking news|latest news|top stories|headlines today|'
    r"l'actualité|dernière heure|"
    r'\| cnn|\| bbc|\| ap news|\| reuters|\| wsj|'
    r'top news:|find latest|every corner|international news & views|'
    r'top headlines from|^national \||'
    r'results,?\s*news\s*(and|&)\s*analysis',
    re.IGNORECASE,
)


def _fetch_one_ddg_trending(query: str) -> list[dict]:
    """Fetch headlines pour une query DDG. Retourne les résultats bruts (dedup par le caller)."""
    results = []
    try:
        resp = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{query} news 2026", "t": "h_"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()

        titles = re.findall(r'class="result__a"[^>]*>([^<]+)<', resp.text)
        hrefs = re.findall(r'class="result__a"[^>]*href="([^"]+)"', resp.text)

        for i, title in enumerate(titles):
            clean_title = re.sub(r'<[^>]+>', '', title).strip()
            clean_title = html_mod.unescape(clean_title)
            if not clean_title or len(clean_title) < 20:
                continue
            if _HOMEPAGE_RE.search(clean_title):
                continue

            domain = ""
            url = ""
            if i < len(hrefs):
                domain = _extract_domain(hrefs[i])
                url = hrefs[i]
            if domain and domain not in _ALL_TRUSTED:
                continue

            source = _SOURCE_LABELS.get(domain, domain.split(".")[0].capitalize()) if domain else "?"
            results.append({"title": clean_title, "source": source, "url": url})

    except Exception as e:
        logger.debug(f"Trending headlines fetch failed for '{query}': {e}")

    return results


def fetch_trending_headlines(max_results: int = 25) -> list[dict]:
    """Fetch des headlines tendance SANS query spécifique à un marché.

    Utilise DuckDuckGo News (zero coût API), 8 queries en parallèle.
    Retourne liste de {title, source, url}.
    Résultat caché 10 min.
    """
    cache_key = f"trending_{max_results}"
    if cache_key in _trending_cache:
        ts, cached = _trending_cache[cache_key]
        if time.time() - ts < _TRENDING_CACHE_TTL:
            return cached

    headlines = []
    seen_titles = set()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_fetch_one_ddg_trending, q): q for q in _TRENDING_QUERIES}
        for future in as_completed(futures, timeout=30):
            try:
                batch = future.result(timeout=15)
                for h in batch:
                    title_key = re.sub(r'\W+', '', h["title"].lower())
                    if title_key not in seen_titles:
                        seen_titles.add(title_key)
                        headlines.append(h)
            except Exception:
                pass

    headlines = headlines[:max_results]
    _trending_cache[cache_key] = (time.time(), headlines)
    return headlines


def cache_status() -> dict:
    """Retourne l'etat du cache pour debug."""
    now = time.time()
    active_headlines = sum(1 for ts, _ in _news_cache.values() if now - ts < _NEWS_CACHE_TTL)
    active_articles = sum(1 for ts, _ in _articles_cache.values() if now - ts < _NEWS_CACHE_TTL)
    has_er = _get_er_key() is not None
    has_perigon = _get_perigon_key() is not None
    if has_er:
        source = "Event Registry"
    elif has_perigon:
        source = "Perigon (fallback)"
    else:
        source = "DuckDuckGo (fallback)"
    return {
        "total": len(_articles_cache) + len(_news_cache),
        "active": active_headlines + active_articles,
        "expired": (len(_articles_cache) - active_articles) + (len(_news_cache) - active_headlines),
        "source": source,
        "er_calls_month": _load_er_quota()["calls"],
    }
