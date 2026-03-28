"""
Free market data sources — surveillance layer.

Sources used (all free, no API keys required unless noted):
  - FRED (Federal Reserve) — macro indicators
  - ECB Statistical Data Warehouse — EU rates & inflation
  - ONS (UK Office for National Statistics) — UK macro
  - RSS feeds — news headlines from Reuters, BBC, FT
  - SEC EDGAR full-text search — US filings & 8-K material events
  - OpenInsider — US insider transactions (HTML scrape)

Design principles (compute efficiency):
  - Each source has its own cache file with a suitable TTL
  - No source is re-fetched until its cache expires
  - All network calls are wrapped in try/except — failures are silent
    (surveillance is best-effort; a broken feed never crashes the screener)
  - Parsing is done with stdlib only (json, xml.etree, urllib) to avoid
    heavy dependencies; feedparser added only for RSS where available
"""

import json
import time
import re
from pathlib import Path
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

CACHE_DIR = Path(__file__).parent.parent / "cache" / "surveillance"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(key: str) -> Path:
    safe = re.sub(r"[^a-z0-9_]", "_", key.lower())
    return CACHE_DIR / f"{safe}.json"


def _is_fresh(key: str, ttl_hours: float) -> bool:
    p = _cache_path(key)
    if not p.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    return age < timedelta(hours=ttl_hours)


def _load(key: str) -> dict | list | None:
    p = _cache_path(key)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def _save(key: str, data):
    _cache_path(key).write_text(json.dumps(data, default=str, indent=2))


def _get(url: str, timeout: int = 10) -> bytes | None:
    """Simple HTTP GET with a browser-like User-Agent."""
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ValueScreener/1.0)"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (URLError, HTTPError, Exception):
        return None


# ══════════════════════════════════════════════════════════════════════════════
# MACRO DATA — FRED (Federal Reserve Economic Data)
# No API key needed for public series. Rate limit: generous for personal use.
# TTL: 4 hours (most series update daily at most)
# ══════════════════════════════════════════════════════════════════════════════

FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="

# Series we care about: (series_id, friendly_name, unit)
FRED_SERIES = [
    ("DFF",      "Fed Funds Rate",          "%"),
    ("T10Y2Y",   "Yield Curve (10Y-2Y)",    "%"),   # negative = inversion
    ("CPIAUCSL", "US CPI (YoY)",            "index"),
    ("UNRATE",   "US Unemployment",         "%"),
    ("BAMLH0A0HYM2", "US HY Credit Spread", "bps"), # junk spread, stress indicator
    ("VIXCLS",   "VIX (Fear Index)",        "pts"),
    ("DGS10",    "US 10Y Treasury Yield",   "%"),
    ("DGS2",     "US 2Y Treasury Yield",    "%"),
]


def fetch_fred_series(series_id: str) -> float | None:
    """Fetch the latest value for a single FRED series. Returns float or None."""
    url = FRED_BASE + series_id
    raw = _get(url)
    if not raw:
        return None
    try:
        lines = raw.decode("utf-8").strip().splitlines()
        # CSV: DATE,VALUE — take last non-empty, non-'.' row
        for line in reversed(lines[1:]):
            parts = line.split(",")
            if len(parts) == 2 and parts[1].strip() not in (".", ""):
                return float(parts[1].strip())
    except Exception:
        pass
    return None


def get_macro_indicators(force: bool = False) -> dict:
    """
    Returns a dict of macro indicators.
    Cached for 4 hours; set force=True to bypass cache.
    """
    key = "fred_macro"
    if not force and _is_fresh(key, ttl_hours=4):
        cached = _load(key)
        if cached:
            return cached

    result = {
        "source":    "FRED / Federal Reserve",
        "fetched_at": datetime.now().isoformat(),
        "series":    {},
        "signals":   [],
    }

    for series_id, name, unit in FRED_SERIES:
        val = fetch_fred_series(series_id)
        result["series"][series_id] = {
            "name":  name,
            "value": val,
            "unit":  unit,
        }

    # Derive signals from raw values
    s = result["series"]

    # Yield curve inversion
    yc = s.get("T10Y2Y", {}).get("value")
    if yc is not None:
        if yc < 0:
            result["signals"].append({
                "type":     "macro_warning",
                "severity": "high" if yc < -0.5 else "medium",
                "title":    "Yield Curve Inverted",
                "detail":   f"10Y–2Y spread is {yc:+.2f}%. Historically precedes recessions by 6–18 months.",
            })
        elif yc > 1.0:
            result["signals"].append({
                "type":     "macro_positive",
                "severity": "low",
                "title":    "Yield Curve Steepening",
                "detail":   f"10Y–2Y spread is {yc:+.2f}%. Positive for banks and growth-oriented sectors.",
            })

    # Credit spread stress
    hy = s.get("BAMLH0A0HYM2", {}).get("value")
    if hy is not None:
        if hy > 600:
            result["signals"].append({
                "type":     "macro_warning",
                "severity": "high",
                "title":    "Credit Stress Elevated",
                "detail":   f"HY spread at {hy:.0f}bps — above 600 signals credit market stress.",
            })
        elif hy > 400:
            result["signals"].append({
                "type":     "macro_warning",
                "severity": "medium",
                "title":    "Credit Spread Widening",
                "detail":   f"HY spread at {hy:.0f}bps — elevated but not crisis levels.",
            })

    # VIX fear gauge
    vix = s.get("VIXCLS", {}).get("value")
    if vix is not None:
        if vix > 30:
            result["signals"].append({
                "type":     "macro_warning",
                "severity": "high",
                "title":    "Elevated Market Fear (VIX)",
                "detail":   f"VIX at {vix:.1f} — above 30 indicates significant uncertainty. May signal buying opportunity.",
            })
        elif vix < 15:
            result["signals"].append({
                "type":     "macro_info",
                "severity": "low",
                "title":    "Low Volatility Environment",
                "detail":   f"VIX at {vix:.1f} — complacency risk; markets may be underpricing tail risk.",
            })

    # Fed rate context
    ffr = s.get("DFF", {}).get("value")
    dgs10 = s.get("DGS10", {}).get("value")
    if ffr is not None and dgs10 is not None:
        if dgs10 < ffr:
            result["signals"].append({
                "type":     "macro_warning",
                "severity": "medium",
                "title":    "Inverted Rate Structure",
                "detail":   f"10Y yield ({dgs10:.2f}%) below Fed Funds ({ffr:.2f}%). Favours short-duration assets.",
            })

    _save(key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# UK MACRO — ONS (Office for National Statistics)
# Free JSON API. TTL: 6 hours
# ══════════════════════════════════════════════════════════════════════════════

ONS_BASE = "https://api.beta.ons.gov.uk/v1/datasets"


def _fetch_ons_series(dataset_id: str, edition: str = "time-series") -> float | None:
    """Fetch latest observation from ONS API v1."""
    # ONS beta API: get latest datapoint
    url = f"https://api.beta.ons.gov.uk/v1/datasets/{dataset_id}/editions/{edition}/versions/1/observations?time=*&geography=K02000001"
    raw = _get(url)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        obs = data.get("observations", [])
        if obs:
            latest = sorted(obs, key=lambda x: x.get("time", ""))[-1]
            return float(latest.get("observation", 0))
    except Exception:
        pass
    return None


def get_uk_macro(force: bool = False) -> dict:
    """
    UK macro context: CPI, base rate (scraped from BoE), gilt yields.
    Falls back gracefully if ONS API unavailable.
    TTL: 6 hours.
    """
    key = "uk_macro"
    if not force and _is_fresh(key, ttl_hours=6):
        cached = _load(key)
        if cached:
            return cached

    result = {
        "source":     "ONS / Bank of England",
        "fetched_at": datetime.now().isoformat(),
        "series":     {},
        "signals":    [],
    }

    # Bank of England base rate — from their public statistics API
    boe_url = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp?Travel=NIxAZxSUx&FromSeries=1&ToSeries=50&DAT=RNG&FD=1&FM=Jan&FY=2024&TD=31&TM=Dec&TY=2026&VFD=Y&html.x=66&html.y=26&C=BYU&Filter=N"
    raw = _get(boe_url)
    boe_rate = None
    if raw:
        try:
            # Parse CSV: Date, Value
            lines = raw.decode("utf-8", errors="ignore").strip().splitlines()
            for line in reversed(lines):
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        boe_rate = float(parts[-1].strip().strip('"'))
                        break
                    except ValueError:
                        continue
        except Exception:
            pass

    result["series"]["BOE_BASE"] = {"name": "BoE Base Rate", "value": boe_rate, "unit": "%"}

    # UK 10Y gilt yield via FRED (they carry it)
    gilt_10y = fetch_fred_series("IRLTLT01GBM156N")  # OECD monthly series for UK
    result["series"]["GILT_10Y"] = {"name": "UK 10Y Gilt Yield", "value": gilt_10y, "unit": "%"}

    # Signals
    if boe_rate is not None:
        if boe_rate >= 5.0:
            result["signals"].append({
                "type":     "macro_info",
                "severity": "medium",
                "title":    f"BoE Rate Elevated at {boe_rate:.2f}%",
                "detail":   "High base rate compresses equity multiples; favours value over growth. Cash and short-duration bonds attractive.",
            })
        elif boe_rate <= 1.0:
            result["signals"].append({
                "type":     "macro_info",
                "severity": "low",
                "title":    f"BoE Rate Low at {boe_rate:.2f}%",
                "detail":   "Low rate environment supports equity valuations and growth stocks.",
            })

    if gilt_10y is not None and boe_rate is not None:
        real_yield = gilt_10y - boe_rate
        if abs(real_yield) > 1.5:
            result["signals"].append({
                "type":     "macro_info",
                "severity": "low",
                "title":    "UK Yield Curve Signal",
                "detail":   f"10Y gilt ({gilt_10y:.2f}%) vs base rate ({boe_rate:.2f}%). Spread: {real_yield:+.2f}%.",
            })

    _save(key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# NEWS & SENTIMENT — RSS feeds
# Sources: Reuters, BBC Business, FT (free headlines only)
# Sentiment: VADER (if installed) else simple keyword scoring
# TTL: 1 hour (news is time-sensitive)
# ══════════════════════════════════════════════════════════════════════════════

RSS_FEEDS = {
    "Reuters Business":   "https://feeds.reuters.com/reuters/businessNews",
    "BBC Business":       "https://feeds.bbci.co.uk/news/business/rss.xml",
    "Reuters Markets":    "https://feeds.reuters.com/reuters/marketsNews",
    "FT Markets":         "https://www.ft.com/markets?format=rss",
    "Seeking Alpha":      "https://seekingalpha.com/market_currents.xml",
}

# Simple keyword-based sentiment (VADER fallback)
_POS_WORDS = {"beat", "beats", "upgrade", "upgrades", "raised", "raises", "profit", "growth",
              "record", "strong", "outperforms", "buyback", "dividend", "surge", "rally",
              "expansion", "gains", "positive", "exceeds", "recovery"}
_NEG_WORDS = {"miss", "misses", "downgrade", "downgrades", "cut", "cuts", "loss", "losses",
              "warning", "warns", "falls", "decline", "decline", "risk", "investigation",
              "fraud", "lawsuit", "recall", "shortage", "layoffs", "writedown", "impairment"}


def _keyword_sentiment(text: str) -> float:
    """Returns score in [-1, 1] using simple keyword matching."""
    words = set(text.lower().split())
    pos = len(words & _POS_WORDS)
    neg = len(words & _NEG_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _vader_sentiment(text: str) -> float:
    """Use VADER if available, fallback to keyword method."""
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
        return analyzer.polarity_scores(text)["compound"]
    except ImportError:
        return _keyword_sentiment(text)


def _parse_rss(raw_bytes: bytes) -> list[dict]:
    """Parse RSS/Atom XML into a list of {title, link, published, summary} dicts."""
    items = []
    try:
        root = ET.fromstring(raw_bytes.decode("utf-8", errors="replace"))
        # Handle both RSS and Atom
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        for item in root.findall(".//item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link", "").strip()
            pub   = item.findtext("pubDate", item.findtext("dc:date", ""))
            desc  = item.findtext("description", "").strip()
            # Strip HTML tags from description
            desc = re.sub(r"<[^>]+>", " ", desc).strip()
            if title:
                items.append({"title": title, "link": link, "published": pub, "summary": desc})

        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title = entry.findtext("atom:title", "", ns).strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                pub  = entry.findtext("atom:published", "", ns)
                desc = entry.findtext("atom:summary", "", ns).strip()
                desc = re.sub(r"<[^>]+>", " ", desc).strip()
                if title:
                    items.append({"title": title, "link": link, "published": pub, "summary": desc})
    except Exception:
        pass
    return items[:30]  # cap at 30 per feed


def fetch_news(tickers: list[str] = None, force: bool = False) -> dict:
    """
    Fetch headlines from all RSS feeds.
    If tickers provided, also scores each headline for ticker relevance.
    TTL: 1 hour.
    """
    key = "rss_news"
    if not force and _is_fresh(key, ttl_hours=1):
        cached = _load(key)
        if cached:
            return _filter_news_for_tickers(cached, tickers)

    all_items = []
    for feed_name, url in RSS_FEEDS.items():
        raw = _get(url)
        if raw:
            items = _parse_rss(raw)
            for item in items:
                item["feed"]     = feed_name
                item["sentiment"] = _vader_sentiment(item["title"] + " " + item.get("summary", ""))
            all_items.extend(items)
        # Small delay to be polite to servers
        time.sleep(0.3)

    result = {
        "fetched_at": datetime.now().isoformat(),
        "total":      len(all_items),
        "items":      all_items,
    }
    _save(key, result)
    return _filter_news_for_tickers(result, tickers)


def _filter_news_for_tickers(news_data: dict, tickers: list[str] | None) -> dict:
    """Tag news items that mention any of the given tickers/company names."""
    if not tickers or not news_data.get("items"):
        return news_data

    # Build lookup: ticker root → ticker
    ticker_roots = {}
    for t in tickers:
        root = t.replace(".L", "").replace(".AS", "").replace(".DE", "").replace(".PA", "").upper()
        ticker_roots[root] = t

    result = dict(news_data)
    result["ticker_mentions"] = {}

    for item in news_data.get("items", []):
        text = (item.get("title", "") + " " + item.get("summary", "")).upper()
        for root, ticker in ticker_roots.items():
            if root in text:
                if ticker not in result["ticker_mentions"]:
                    result["ticker_mentions"][ticker] = []
                result["ticker_mentions"][ticker].append({
                    "title":     item["title"],
                    "sentiment": item["sentiment"],
                    "feed":      item["feed"],
                    "link":      item.get("link", ""),
                })

    return result


# ══════════════════════════════════════════════════════════════════════════════
# US INSIDER TRANSACTIONS — OpenInsider
# Free HTML data, no API key. TTL: 6 hours.
# Only covers US tickers (no exchange suffix)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_insider_buys(tickers: list[str], force: bool = False) -> dict:
    """
    Fetch recent insider buys from OpenInsider for US tickers.
    Returns dict: {ticker: [transactions]}
    Cluster buying (3+ insiders buying within 30 days) flagged as high-signal.
    TTL: 6 hours.
    """
    key = "insider_buys"
    if not force and _is_fresh(key, ttl_hours=6):
        cached = _load(key)
        if cached:
            return cached

    # Only US tickers (no dot-suffix)
    us_tickers = [t for t in tickers if "." not in t]
    result = {"fetched_at": datetime.now().isoformat(), "transactions": {}, "cluster_signals": []}

    for ticker in us_tickers[:20]:  # Rate-limit ourselves: top 20 US only
        url = f"http://openinsider.com/screener?s={ticker}&o=&pl=&ph=&ll=&lh=&fd=30&fdr=&td=0&tdr=&fdlyl=&fdlyh=&daysago=30&xp=1&xs=1&vl=25000&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&iscob=0&isceo=0&ispres=0&iscoo=0&iscfo=0&isgc=0&isvp=0&isdirector=0&istenpercent=0&isother=0&grp=0&nfl=&nfh=&nil=&nih=&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=20&action=1"
        raw = _get(url)
        if not raw:
            continue

        try:
            html = raw.decode("utf-8", errors="replace")
            # Extract table rows (quick regex parse — no BeautifulSoup needed)
            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
            transactions = []
            for row in rows[1:]:  # Skip header
                cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
                cells = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
                if len(cells) >= 10:
                    transactions.append({
                        "date":       cells[1] if len(cells) > 1 else "",
                        "insider":    cells[3] if len(cells) > 3 else "",
                        "title":      cells[4] if len(cells) > 4 else "",
                        "trade_type": cells[5] if len(cells) > 5 else "",
                        "price":      cells[6] if len(cells) > 6 else "",
                        "qty":        cells[7] if len(cells) > 7 else "",
                        "value":      cells[9] if len(cells) > 9 else "",
                    })
            if transactions:
                result["transactions"][ticker] = transactions[:10]

                # Cluster signal: 3+ buys in 30 days
                buys = [t for t in transactions if "P" in t.get("trade_type", "")]
                if len(buys) >= 3:
                    result["cluster_signals"].append({
                        "ticker":   ticker,
                        "severity": "high",
                        "title":    f"Cluster Insider Buying: {ticker}",
                        "detail":   f"{len(buys)} insiders bought {ticker} in last 30 days. Historically a positive signal.",
                        "count":    len(buys),
                    })
        except Exception:
            pass

        time.sleep(0.5)  # Be polite — 0.5s between requests

    _save(key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SEC EDGAR — Material Event Filings (8-K)
# Free full-text search API. No key needed. TTL: 4 hours.
# ══════════════════════════════════════════════════════════════════════════════

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K"


def fetch_material_events(tickers: list[str], force: bool = False) -> dict:
    """
    Check SEC EDGAR for recent 8-K filings (material events) for US tickers.
    TTL: 4 hours.
    """
    key = "edgar_events"
    if not force and _is_fresh(key, ttl_hours=4):
        cached = _load(key)
        if cached:
            return cached

    us_tickers = [t for t in tickers if "." not in t]
    result = {"fetched_at": datetime.now().isoformat(), "events": {}}

    start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    end   = datetime.now().strftime("%Y-%m-%d")

    for ticker in us_tickers[:15]:  # Cap to avoid hammering EDGAR
        url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K"
        raw = _get(url)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            hits = data.get("hits", {}).get("hits", [])
            events = []
            for hit in hits[:5]:
                src = hit.get("_source", {})
                events.append({
                    "date":  src.get("file_date", ""),
                    "title": src.get("display_names", [{"name": ticker}])[0].get("name", ticker),
                    "form":  src.get("form_type", "8-K"),
                    "url":   "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=" + src.get("entity_id", ""),
                })
            if events:
                result["events"][ticker] = events
        except Exception:
            pass
        time.sleep(0.3)

    _save(key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED SURVEILLANCE FETCH
# Single entry point for the signals engine
# ══════════════════════════════════════════════════════════════════════════════

def run_all_sources(tickers: list[str], force: bool = False) -> dict:
    """
    Run all surveillance sources and return combined data.
    This is the main entry point called by the signals engine.

    Args:
        tickers: list of all tickers in the current universe
        force:   bypass all caches and re-fetch everything

    Returns dict with keys: macro_us, macro_uk, news, insider, edgar
    """
    return {
        "macro_us": get_macro_indicators(force=force),
        "macro_uk": get_uk_macro(force=force),
        "news":     fetch_news(tickers=tickers, force=force),
        "insider":  fetch_insider_buys(tickers=tickers, force=force),
        "edgar":    fetch_material_events(tickers=tickers, force=force),
    }
