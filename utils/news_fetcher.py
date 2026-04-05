"""
surveillance/news_fetcher.py — Financial news aggregator with ticker matching,
sentiment scoring, and caching.

Architecture:
  • fetch_market_news()       — broad market headlines (CNBC, MarketWatch, Yahoo)
  • fetch_news_for_ticker()   — per-ticker headlines (Yahoo Finance RSS by symbol)
  • get_signals_from_news()   — returns list of signal dicts for Signals page
  • get_trending_stories()    — top stories by recency for Morning Briefing
  • get_news_for_ticker()     — cached per-ticker news for Holdings deep analysis

Cache: cache/news/<feed>.json with 1h TTL (30min during market hours)
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# ── Optional deps — graceful degradation ─────────────────────────────────────

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
    VADER_AVAILABLE = True
except ImportError:
    _vader = None
    VADER_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# finnews is bundled as uploaded files — try package import, fall back to None
try:
    from finnews.client import News as _FinnewsClient
    FINNEWS_AVAILABLE = True
except ImportError:
    _FinnewsClient = None
    FINNEWS_AVAILABLE = False

# ── Cache setup ───────────────────────────────────────────────────────────────

_BASE  = Path(__file__).parent.parent / "cache"
_NEWS  = _BASE / "news"
_NEWS.mkdir(parents=True, exist_ok=True)

NEWS_TTL_MINUTES       = 30   # market hours
NEWS_TTL_CLOSED        = 120  # off-hours / weekend

# ── Market hours (for TTL selection) ─────────────────────────────────────────

def _market_open() -> bool:
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    h = now.hour
    return (7 <= h < 17) or (13 <= h < 20)


def _news_ttl() -> int:
    return NEWS_TTL_MINUTES if _market_open() else NEWS_TTL_CLOSED


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", key)
    return _NEWS / f"{safe}.json"


def _load_cache(key: str) -> Optional[dict]:
    path = _cache_path(key)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = data.get("cached_at")
            if ts:
                dt = datetime.fromisoformat(str(ts))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_min = (datetime.now(timezone.utc) - dt).total_seconds() / 60
                if age_min < _news_ttl():
                    return data
    except Exception:
        pass
    return None


def _save_cache(key: str, articles: list) -> None:
    data = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "articles": articles,
    }
    try:
        _cache_path(key).write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception:
        pass


# ── Sentiment scoring ─────────────────────────────────────────────────────────

def _score_sentiment(text: str) -> float:
    """Return VADER compound sentiment score in [-1, 1]. 0 if unavailable."""
    if not VADER_AVAILABLE or not text:
        return 0.0
    try:
        return _vader.polarity_scores(text)["compound"]
    except Exception:
        return 0.0


def _sentiment_label(score: float) -> str:
    if score >= 0.05:
        return "positive"
    if score <= -0.05:
        return "negative"
    return "neutral"


# ── Ticker matching ───────────────────────────────────────────────────────────

def _build_name_index(instruments: list) -> dict:
    """
    Build a mapping of lower-case name tokens → ticker for fast mention detection.
    Also indexes ticker itself (e.g. 'LLOY' → 'LLOY.L').
    """
    index = {}
    for inst in instruments:
        ticker = inst.get("ticker", "")
        name   = inst.get("name", "")
        if not ticker:
            continue
        # Index the ticker (strip exchange suffix for matching)
        base = ticker.split(".")[0].lower()
        index[base] = ticker
        # Index significant words from the name (3+ chars, not stop words)
        STOP = {"the", "and", "for", "plc", "ltd", "inc", "corp", "group",
                "holdings", "international", "limited", "company"}
        for word in re.split(r"[\s\-\&\,\.]+", name.lower()):
            if len(word) >= 4 and word not in STOP:
                index[word] = ticker
    return index


def _find_mentioned_tickers(text: str, name_index: dict) -> list:
    """Return list of tickers mentioned in text, deduped."""
    if not text or not name_index:
        return []
    text_lower = text.lower()
    found = set()
    for token, ticker in name_index.items():
        # Whole-word match only
        pattern = r"\b" + re.escape(token) + r"\b"
        if re.search(pattern, text_lower):
            found.add(ticker)
    return list(found)


# ── RSS fetch helpers ─────────────────────────────────────────────────────────

def _fetch_with_finnews(source: str, method: str, **kwargs) -> list:
    """
    Generic wrapper: instantiate finnews client, call the requested method.
    Returns list of article dicts or [].
    """
    if not FINNEWS_AVAILABLE:
        return []
    try:
        client = _FinnewsClient()
        src = getattr(client, source, None)
        if src is None:
            return []
        fn = getattr(src, method, None)
        if fn is None:
            return []
        result = fn(**kwargs)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _normalise_articles(raw: list, source_label: str) -> list:
    """
    Ensure each article dict has: title, summary, url, published, source, sentiment.
    finnews returns dicts with keys like 'title', 'summary'/'description', 'url'/'link',
    'published'/'pubDate'.
    """
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or item.get("headline") or "").strip()
        summary = (item.get("summary") or item.get("description") or
                   item.get("content") or "").strip()
        url = (item.get("url") or item.get("link") or
               item.get("href") or "").strip()
        published = (item.get("published") or item.get("pubDate") or
                     item.get("date") or "")

        # Parse published date if possible
        pub_iso = ""
        if published:
            try:
                # Try various common RSS date formats
                for fmt in [
                    "%a, %d %b %Y %H:%M:%S %z",
                    "%a, %d %b %Y %H:%M:%S %Z",
                    "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%d %H:%M:%S",
                ]:
                    try:
                        dt = datetime.strptime(str(published).strip(), fmt)
                        pub_iso = dt.isoformat()
                        break
                    except ValueError:
                        continue
                if not pub_iso:
                    pub_iso = str(published)
            except Exception:
                pub_iso = str(published)

        if not title:
            continue

        compound = _score_sentiment(f"{title} {summary}")
        out.append({
            "title":     title,
            "summary":   summary[:300] if summary else "",
            "url":       url,
            "published": pub_iso,
            "source":    source_label,
            "sentiment": compound,
            "sentiment_label": _sentiment_label(compound),
        })
    return out


# ── Public fetch functions ────────────────────────────────────────────────────

def fetch_market_news(force: bool = False) -> list:
    """
    Fetch broad market news from 8 sources:
      CNBC, MarketWatch, Yahoo Finance, WSJ, Seeking Alpha,
      NASDAQ, S&P Global, CNN Finance.
    Cached for NEWS_TTL minutes.
    Returns combined, deduped list sorted by recency (most recent first).
    """
    cache_key = "market_news"
    if not force:
        cached = _load_cache(cache_key)
        if cached:
            return cached["articles"]

    articles = []

    # ── Tier 1: existing sources ──────────────────────────────────────────────

    # CNBC — top news + investing + earnings
    for topic in ["top_news", "investing", "earnings"]:
        raw = _fetch_with_finnews("cnbc", "news_feed", topic=topic)
        articles.extend(_normalise_articles(raw, "CNBC"))
        if raw:
            time.sleep(0.4)

    # MarketWatch — top stories + real-time headlines
    for method in ["top_stories", "real_time_headlines"]:
        raw = _fetch_with_finnews("market_watch", method)
        articles.extend(_normalise_articles(raw, "MarketWatch"))
        if raw:
            time.sleep(0.4)

    # Yahoo Finance — general news
    raw = _fetch_with_finnews("yahoo_finance", "news")
    articles.extend(_normalise_articles(raw, "Yahoo Finance"))
    if raw:
        time.sleep(0.4)

    # ── Tier 2: new sources ───────────────────────────────────────────────────

    # WSJ — market news + US business (premium, low noise)
    for method in ["market_news", "us_business_news"]:
        raw = _fetch_with_finnews("wsj", method)
        articles.extend(_normalise_articles(raw, "WSJ"))
        if raw:
            time.sleep(0.4)

    # Seeking Alpha — Wall Street Breakfast digest + latest articles
    for method in ["wall_street_breakfast", "latest_articles"]:
        raw = _fetch_with_finnews("seeking_alpha", method)
        articles.extend(_normalise_articles(raw, "Seeking Alpha"))
        if raw:
            time.sleep(0.4)

    # NASDAQ — markets feed + stocks feed
    for method in ["markets_feed", "stocks_feed"]:
        raw = _fetch_with_finnews("nasdaq", method)
        articles.extend(_normalise_articles(raw, "NASDAQ"))
        if raw:
            time.sleep(0.4)

    # S&P Global — market commentary + research (institutional/macro)
    for method in ["market_commentary", "research"]:
        raw = _fetch_with_finnews("sp_global", method)
        articles.extend(_normalise_articles(raw, "S&P Global"))
        if raw:
            time.sleep(0.4)

    # CNN Finance — top stories + markets
    for method in ["top_stories", "markets"]:
        raw = _fetch_with_finnews("cnn_finance", method)
        articles.extend(_normalise_articles(raw, "CNN Finance"))
        if raw:
            time.sleep(0.4)

    # Dedupe by URL
    seen_urls = set()
    unique = []
    for a in articles:
        key = a.get("url") or a.get("title", "")
        if key and key not in seen_urls:
            seen_urls.add(key)
            unique.append(a)

    # Sort: articles with parseable ISO dates first (most recent)
    def _pub_key(a):
        try:
            return a.get("published", "") or ""
        except Exception:
            return ""

    unique.sort(key=_pub_key, reverse=True)

    _save_cache(cache_key, unique)
    return unique


def fetch_news_for_ticker(ticker: str, name: str = "", force: bool = False) -> list:
    """
    Fetch news specific to a single ticker.
    Priority order:
      1. Yahoo Finance per-symbol RSS (fastest, most direct)
      2. Seeking Alpha per-ticker API (richer editorial analysis)
      3. NASDAQ ticker feed (exchange-specific)
      4. Broad market news scan for ticker/name mentions (fallback)
    Returns list of article dicts, cached per-ticker.
    """
    cache_key = f"ticker_{ticker}"
    if not force:
        cached = _load_cache(cache_key)
        if cached:
            return cached["articles"]

    articles = []
    seen_urls: set = set()

    def _add(raw, source):
        for art in _normalise_articles(raw, source):
            key = art.get("url") or art.get("title", "")
            if key and key not in seen_urls:
                seen_urls.add(key)
                articles.append(art)

    # 1. Yahoo Finance per-ticker RSS
    raw = _fetch_with_finnews("yahoo_finance", "headlines", symbols=[ticker])
    _add(raw, "Yahoo Finance")
    if raw:
        time.sleep(0.3)

    # 2. Seeking Alpha per-ticker API (editorial depth, especially good for US stocks)
    # Use the base ticker without exchange suffix (e.g. AAPL, not AAPL.L)
    base_ticker = ticker.split(".")[0]
    raw = _fetch_with_finnews("seeking_alpha", "stocks", ticker=base_ticker)
    _add(raw, "Seeking Alpha")
    if raw:
        time.sleep(0.3)

    # 3. NASDAQ ticker feed
    raw = _fetch_with_finnews("nasdaq", "ticker_feed", ticker_symbol=base_ticker)
    _add(raw, "NASDAQ")

    # 4. If still nothing, fall back to scanning broad market news for mentions
    if not articles:
        market = fetch_market_news()
        name_index = {}
        if ticker:
            name_index[base_ticker.lower()] = ticker
        if name:
            STOP = {"the", "and", "for", "plc", "ltd", "inc", "corp", "group",
                    "holdings", "international", "limited", "company"}
            for word in re.split(r"[\s\-\&\,\.]+", name.lower()):
                if len(word) >= 4 and word not in STOP:
                    name_index[word] = ticker

        for art in market:
            text = f"{art.get('title', '')} {art.get('summary', '')}"
            if _find_mentioned_tickers(text, name_index):
                articles.append(art)

    _save_cache(cache_key, articles)
    return articles


def get_news_for_ticker(ticker: str, name: str = "", max_articles: int = 10) -> list:
    """
    Public API for Holdings deep analysis — returns up to max_articles
    news items for the given ticker, sorted by recency.
    """
    articles = fetch_news_for_ticker(ticker, name)
    return articles[:max_articles]


def get_trending_stories(max_stories: int = 15) -> list:
    """
    Public API for Morning Briefing — returns the top stories by recency
    from the combined market news feed.
    """
    articles = fetch_market_news()
    return articles[:max_stories]


def get_signals_from_news(instruments: list, max_signals: int = 20) -> list:
    """
    Public API for Signals page — scans market news for mentions of
    instruments in the universe, returns signal dicts with:
      ticker, name, headline, url, sentiment, sentiment_label, source, published

    Returns up to max_signals, sorted by absolute sentiment (strongest first).
    """
    if not instruments:
        return []

    name_index = _build_name_index(instruments)
    inst_map   = {i["ticker"]: i for i in instruments if i.get("ticker")}
    articles   = fetch_market_news()

    signals = []
    seen    = set()  # dedupe (ticker, url)

    for art in articles:
        text = f"{art.get('title', '')} {art.get('summary', '')}"
        tickers = _find_mentioned_tickers(text, name_index)
        for ticker in tickers:
            key = (ticker, art.get("url", art.get("title", "")))
            if key in seen:
                continue
            seen.add(key)
            inst = inst_map.get(ticker, {})
            signals.append({
                "ticker":          ticker,
                "name":            inst.get("name", ticker),
                "score":           inst.get("score"),
                "headline":        art.get("title", ""),
                "summary":         art.get("summary", ""),
                "url":             art.get("url", ""),
                "sentiment":       art.get("sentiment", 0),
                "sentiment_label": art.get("sentiment_label", "neutral"),
                "source":          art.get("source", ""),
                "published":       art.get("published", ""),
            })

    # Sort by absolute sentiment strength (most bullish/bearish first)
    signals.sort(key=lambda s: abs(s.get("sentiment", 0)), reverse=True)
    return signals[:max_signals]


def get_news_summary_for_briefing(max_stories: int = 10) -> str:
    """
    Returns a formatted text block of top stories suitable for injection
    into the Morning Briefing AI prompt.
    """
    stories = get_trending_stories(max_stories)
    if not stories:
        return "No recent news available."

    lines = []
    for i, s in enumerate(stories, 1):
        label = s.get("sentiment_label", "neutral")
        emoji = "📈" if label == "positive" else ("📉" if label == "negative" else "📰")
        lines.append(f"{i}. {emoji} {s.get('title', '')}")
        if s.get("summary"):
            lines.append(f"   {s['summary'][:120]}...")
    return "\n".join(lines)


# ── Sector-targeted news (Phase 4) ────────────────────────────────────────────

# Map of app sector names → Seeking Alpha sector slug
_SECTOR_SA_SLUG = {
    "Technology":          "technology",
    "Financials":          "financial",
    "Healthcare":          "healthcare",
    "Consumer Staples":    "consumer-staples",
    "Consumer Discretionary": "consumer-discretionary",
    "Industrials":         "industrial",
    "Energy":              "energy",
    "Materials":           "basic-materials",
    "Real Estate":         "real-estate",
    "Utilities":           "utilities",
    "Communication Services": "communication-services",
}

# Map of app sector names → CNBC topic key
_SECTOR_CNBC_TOPIC = {
    "Technology":    "technology",
    "Energy":        "energy",
    "Healthcare":    "health_care",
    "Financials":    "finance",
    "Real Estate":   "real_estate",
    "Media":         "media",
    "Retail":        "retail",
    "Travel":        "travel",
}


def fetch_sector_news(sectors: list, max_per_sector: int = 5, force: bool = False) -> dict:
    """
    Fetch news targeted to specific sectors.
    Returns dict of {sector_name: [article_dicts]}.

    sectors: list of sector name strings (e.g. ['Technology', 'Energy'])
    Uses Seeking Alpha sector feeds + relevant CNBC topic feeds.
    Cached per sector with standard TTL.
    """
    result = {}
    for sector in sectors[:4]:  # cap at 4 sectors to avoid overlong fetches
        cache_key = f"sector_{re.sub(r'[^a-z0-9]', '_', sector.lower())}"
        if not force:
            cached = _load_cache(cache_key)
            if cached:
                result[sector] = cached["articles"][:max_per_sector]
                continue

        articles = []
        seen_urls: set = set()

        def _add(raw, source):
            for art in _normalise_articles(raw, source):
                key = art.get("url") or art.get("title", "")
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    articles.append(art)

        # Seeking Alpha sector feed
        sa_slug = _SECTOR_SA_SLUG.get(sector)
        if sa_slug:
            raw = _fetch_with_finnews("seeking_alpha", "sectors", sector=sa_slug)
            _add(raw, "Seeking Alpha")
            if raw:
                time.sleep(0.3)

        # CNBC topic feed (if mapped)
        cnbc_topic = _SECTOR_CNBC_TOPIC.get(sector)
        if cnbc_topic:
            raw = _fetch_with_finnews("cnbc", "news_feed", topic=cnbc_topic)
            _add(raw, "CNBC")

        articles.sort(key=lambda a: a.get("published", "") or "", reverse=True)
        _save_cache(cache_key, articles)
        result[sector] = articles[:max_per_sector]

    return result


def get_sector_news_for_briefing(sectors: list, max_per_sector: int = 3) -> str:
    """
    Returns a formatted text block of sector-targeted stories for the
    Morning Briefing AI prompt. Labelled by sector for clear context.
    """
    if not sectors:
        return ""

    sector_news = fetch_sector_news(sectors, max_per_sector=max_per_sector)
    if not sector_news:
        return ""

    lines = []
    for sector, stories in sector_news.items():
        if not stories:
            continue
        lines.append(f"\n{sector.upper()} NEWS:")
        for s in stories:
            label = s.get("sentiment_label", "neutral")
            prefix = "▲" if label == "positive" else ("▼" if label == "negative" else "─")
            lines.append(f"  {prefix} {s.get('title', '')} [{s.get('source', '')}]")
    return "\n".join(lines)


# ── Market mood (Phase 6) ─────────────────────────────────────────────────────

def get_market_mood(sample_size: int = 30) -> dict:
    """
    Derive a market mood label from recent article sentiment scores.
    Returns dict with:
      label:   "Broadly positive" / "Mixed" / "Broadly negative" / "Risk-off tone"
      score:   float avg sentiment in [-1, 1]
      count:   number of articles sampled
    """
    articles = fetch_market_news()[:sample_size]
    if not articles:
        return {"label": "No data", "score": 0.0, "count": 0}

    scores = [a.get("sentiment", 0.0) for a in articles if a.get("sentiment") is not None]
    if not scores:
        return {"label": "No data", "score": 0.0, "count": 0}

    avg = sum(scores) / len(scores)

    if avg >= 0.10:
        label = "Broadly positive"
    elif avg >= 0.02:
        label = "Cautiously optimistic"
    elif avg >= -0.02:
        label = "Mixed signals"
    elif avg >= -0.10:
        label = "Cautious tone"
    else:
        label = "Risk-off tone"

    return {"label": label, "score": round(avg, 3), "count": len(scores)}


# ── Cache management ──────────────────────────────────────────────────────────

def news_cache_age_minutes() -> Optional[float]:
    """Age of the market_news cache in minutes, or None if no cache."""
    path = _cache_path("market_news")
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            ts = data.get("cached_at")
            if ts:
                dt = datetime.fromisoformat(str(ts))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - dt).total_seconds() / 60
    except Exception:
        pass
    return None


def clear_news_cache() -> None:
    """Delete all cached news files."""
    for p in _NEWS.glob("*.json"):
        try:
            p.unlink()
        except Exception:
            pass
