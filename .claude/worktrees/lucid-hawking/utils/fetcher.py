"""
data/fetcher.py — Two-layer cache: fundamentals (7d TTL) + prices (market-hours TTL).

Architecture:
  • fetch_one()         — public API, unchanged signature, now uses two-layer cache
  • _fetch_fundamentals() — slow call: ROE, D/E, EV/EBITDA, FCF, sector, margins (7d TTL)
  • _fetch_prices()    — fast call: price, 52w range, P/E, P/B, div yield (15min TTL)
  • _merge()           — combines both into the result dict scoring.py expects

On first load everything is fetched. On subsequent loads:
  - Fundamentals are reused from cache (up to 7 days old) — no API call
  - Prices are refreshed if >15 min old during market hours, or at market open/close
  - Result: initial screen loads in seconds, not minutes
"""

from __future__ import annotations

import json
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    yf = None

# ── Cache directories ─────────────────────────────────────────────────────────
_BASE   = Path(__file__).parent.parent / "cache"
_FUND   = _BASE / "fundamentals"   # 7-day TTL
_PRICE  = _BASE / "prices"         # 15-min TTL during market hours
_SCAN   = _BASE / "scan_summary.json"

for _d in (_FUND, _PRICE):
    _d.mkdir(parents=True, exist_ok=True)

# ── TTLs ──────────────────────────────────────────────────────────────────────
FUNDAMENTALS_TTL_HOURS = 7 * 24   # 7 days
PRICE_TTL_MINUTES      = 15
PRICE_TTL_CLOSED       = 60 * 8   # 8h when market closed — no point refreshing

# ── Market hours (UTC) used to decide price TTL ───────────────────────────────
# Simple check: if current UTC time is within any major market session, use short TTL
def _market_open() -> bool:
    """Return True if any major market (London, Frankfurt, NYSE) is currently open."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:   # weekend
        return False
    h = now.hour
    # London 07:00–16:30 UTC, Frankfurt 07:00–17:30 UTC, NYSE 13:30–20:00 UTC
    return (7 <= h < 17) or (13 <= h < 20)


def _price_ttl_minutes() -> int:
    return PRICE_TTL_MINUTES if _market_open() else PRICE_TTL_CLOSED


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path(directory: Path, ticker: str) -> Path:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return directory / f"{safe}.json"


def _load_cache(path: Path) -> dict | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _save_cache(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception:
        pass


def _cache_age_minutes(data: dict) -> float:
    try:
        ts = data.get("cached_at") or data.get("fetched_at")
        if not ts:
            return float("inf")
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60
    except Exception:
        return float("inf")


def _fund_is_fresh(ticker: str) -> bool:
    data = _load_cache(_cache_path(_FUND, ticker))
    if not data:
        return False
    return _cache_age_minutes(data) < FUNDAMENTALS_TTL_HOURS * 60


def _price_is_fresh(ticker: str) -> bool:
    data = _load_cache(_cache_path(_PRICE, ticker))
    if not data:
        return False
    return _cache_age_minutes(data) < _price_ttl_minutes()


# ── Retry wrapper ─────────────────────────────────────────────────────────────

def _yf_info_with_retry(ticker: str, max_attempts: int = 3) -> dict:
    """Fetch yfinance info with exponential backoff on rate-limit errors."""
    if yf is None:
        return {}
    last_err = None
    for attempt in range(max_attempts):
        try:
            t    = yf.Ticker(ticker)
            info = t.info or {}
            # Empty info with no price = likely rate-limited
            if not info or (
                not info.get("regularMarketPrice")
                and not info.get("currentPrice")
                and not info.get("navPrice")
                and not info.get("previousClose")
            ):
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt * 3)
                    continue
            return info
        except Exception as e:
            last_err = e
            err_s = str(e).lower()
            if ("429" in err_s or "too many" in err_s or "rate limit" in err_s) \
                    and attempt < max_attempts - 1:
                time.sleep(2 ** attempt * 5)
                continue
            break
    raise last_err or RuntimeError("yfinance returned empty info")


# ── Fundamentals fetch (slow, 7d TTL) ────────────────────────────────────────

def _fetch_fundamentals(ticker: str, name: str, asset_class: str, group: str,
                        force: bool = False) -> dict:
    """Fetch or load from cache the slow-moving fundamental data."""
    path = _cache_path(_FUND, ticker)

    if not force:
        cached = _load_cache(path)
        if cached and _cache_age_minutes(cached) < FUNDAMENTALS_TTL_HOURS * 60:
            return cached

    try:
        info = _yf_info_with_retry(ticker)
    except Exception as e:
        # Return stale cache if available, otherwise error
        cached = _load_cache(path)
        if cached:
            cached["_stale"] = True
            return cached
        return {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False,
            "error": f"Fundamentals fetch failed: {e}",
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    mkt_cap = info.get("marketCap")
    fcf     = info.get("freeCashflow")
    p_fcf   = (mkt_cap / fcf) if (mkt_cap and fcf and fcf > 0) else None

    result = {
        # Identity
        "ticker":       ticker,
        "name":         name,
        "asset_class":  asset_class,
        "group":        group,
        "sector":       info.get("sector", ""),
        "industry":     info.get("industry", ""),
        "description":  (info.get("longBusinessSummary") or "")[:400],
        "ok":           True,
        # Fundamentals — change slowly (days/weeks)
        "roe":              info.get("returnOnEquity"),
        "debt_to_equity":   info.get("debtToEquity"),
        "profit_margin":    info.get("profitMargins"),
        "free_cashflow":    fcf,
        "market_cap":       mkt_cap,
        "p_fcf":            p_fcf,
        "ev_ebitda":        info.get("enterpriseToEbitda"),
        "revenue":          info.get("totalRevenue"),
        "ebitda":           info.get("ebitda"),
        "total_assets":     info.get("totalAssets"),       # for ETFs/MM
        "aum":              info.get("totalAssets"),
        "ter":              info.get("annualReportExpenseRatio"),
        # Cache metadata
        "cached_at":    datetime.now(timezone.utc).isoformat(),
        "cache_layer":  "fundamentals",
    }
    _save_cache(path, result)
    return result


# ── Price fetch (fast, 15-min TTL) ───────────────────────────────────────────

def _fetch_prices(ticker: str, force: bool = False) -> dict:
    """Fetch or load from cache the fast-moving price data."""
    path = _cache_path(_PRICE, ticker)

    if not force:
        cached = _load_cache(path)
        if cached and _cache_age_minutes(cached) < _price_ttl_minutes():
            return cached

    try:
        info = _yf_info_with_retry(ticker)
    except Exception as e:
        cached = _load_cache(path)
        if cached:
            cached["_stale"] = True
            return cached
        return {"ok": False, "price_error": str(e),
                "cached_at": datetime.now(timezone.utc).isoformat()}

    price = (info.get("regularMarketPrice")
             or info.get("currentPrice")
             or info.get("navPrice")
             or info.get("previousClose"))

    low52  = info.get("fiftyTwoWeekLow")
    high52 = info.get("fiftyTwoWeekHigh")
    pos_52w = None
    if low52 and high52 and high52 > low52 and price:
        pos_52w = (price - low52) / (high52 - low52)

    # Price history for return calculations
    return_1y = return_3m = None
    try:
        if yf:
            t    = yf.Ticker(ticker)
            hist = t.history(period="1y")
            if len(hist) >= 2:
                first = hist["Close"].iloc[0]
                last  = hist["Close"].iloc[-1]
                if first and first > 0:
                    return_1y = (last - first) / first
            if len(hist) >= 63:
                first3m = hist["Close"].iloc[-63]
                if first3m and first3m > 0:
                    return_3m = (last - first3m) / first3m
    except Exception:
        pass

    result = {
        # Prices — change every tick
        "price":         price,
        "currency":      info.get("currency", ""),
        "pe":            info.get("trailingPE") or info.get("forwardPE"),
        "pb":            info.get("priceToBook"),
        "price_to_book": info.get("priceToBook"),
        "div_yield":     info.get("dividendYield"),
        "low_52w":       low52,
        "high_52w":      high52,
        "pos_52w":       pos_52w,
        "return_1y":     return_1y,
        "return_3m":     return_3m,
        "prev_close":    info.get("previousClose"),
        "day_change_pct": (
            ((price - info.get("previousClose")) / info.get("previousClose"))
            if price and info.get("previousClose") and info.get("previousClose") > 0
            else None
        ),
        # Cache metadata
        "cached_at":    datetime.now(timezone.utc).isoformat(),
        "cache_layer":  "prices",
    }
    _save_cache(path, result)
    return result


# ── Merge layers ──────────────────────────────────────────────────────────────

def _merge(fund: dict, price: dict) -> dict:
    """Combine fundamentals and price layers into the full instrument dict."""
    merged = {**fund}
    # Price fields overwrite fundamentals where there's overlap
    for k, v in price.items():
        if v is not None:
            merged[k] = v
    # Unified fetched_at = price cache time (most recent)
    merged["fetched_at"] = price.get("cached_at") or fund.get("cached_at")
    merged["ok"] = fund.get("ok", False) and not price.get("price_error")
    return merged


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_one(ticker: str, name: str, asset_class: str, group: str,
              force_refresh: bool = False) -> dict:
    """
    Fetch a single instrument. Uses two-layer cache:
      - Fundamentals: fetched from Yahoo max once per 7 days
      - Prices: fetched from Yahoo max once per 15 min (market open) / 8h (closed)

    force_refresh=True bypasses both caches (used by manual Refresh button
    and single-ticker refresh in Holdings).
    """
    try:
        fund  = _fetch_fundamentals(ticker, name, asset_class, group, force=force_refresh)
        price = _fetch_prices(ticker, force=force_refresh)
        if not fund.get("ok"):
            return fund
        return _merge(fund, price)
    except Exception as e:
        return {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False,
            "error": str(e),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


def fetch_prices_only(ticker: str, force: bool = False) -> dict:
    """
    Refresh only the price layer for a ticker (fast, used at market open/close).
    Fundamentals are left untouched.
    """
    return _fetch_prices(ticker, force=force)


# ── Bulk price refresh (called at market open/close) ─────────────────────────

def refresh_all_prices(tickers: list[tuple[str, str, str, str]],
                       progress_cb=None) -> list[dict]:
    """
    Refresh prices for all tickers without touching fundamentals.
    tickers: list of (ticker, name, asset_class, group)
    Much faster than a full fetch — only 1 API call per ticker vs the full info blob.
    """
    results = []
    total   = len(tickers)
    for i, (ticker, name, asset_class, group) in enumerate(tickers):
        fund  = _load_cache(_cache_path(_FUND, ticker)) or {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False, "error": "No fundamentals cache"
        }
        price = _fetch_prices(ticker, force=True)
        merged = _merge(fund, price) if fund.get("ok") else fund
        results.append(merged)
        if progress_cb:
            progress_cb((i + 1) / max(total, 1), f"Updating price — {name}")
        # Pace: 400ms between calls to avoid rate limiting
        if i < total - 1:
            time.sleep(0.4)
    return results


# ── Cache introspection (used by sidebar / dashboard) ─────────────────────────

def cache_age_hours() -> float | None:
    """Age of the most recently updated price cache entry, in hours."""
    ages = []
    for p in _PRICE.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            ts   = data.get("cached_at") or data.get("fetched_at")
            if ts:
                dt = datetime.fromisoformat(str(ts))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ages.append((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        except Exception:
            pass
    return min(ages) if ages else None


def fundamentals_age_days() -> float | None:
    """Age of the oldest fundamentals cache entry, in days."""
    ages = []
    for p in _FUND.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            ts   = data.get("cached_at") or data.get("fetched_at")
            if ts:
                dt = datetime.fromisoformat(str(ts))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ages.append((datetime.now(timezone.utc) - dt).total_seconds() / 86400)
        except Exception:
            pass
    return max(ages) if ages else None


def any_cache_exists() -> bool:
    return any(_PRICE.glob("*.json")) or any(_FUND.glob("*.json"))


def _cache_is_fresh(ticker: str) -> bool:
    """True if price cache is fresh enough that fetch_one won't hit Yahoo."""
    return _price_is_fresh(ticker)


def _load_cache_entry(ticker: str) -> dict | None:
    """Load a merged fundamentals+price entry from cache without any fetching."""
    fund  = _load_cache(_cache_path(_FUND, ticker))
    price = _load_cache(_cache_path(_PRICE, ticker))
    if fund and fund.get("ok"):
        if price:
            return _merge(fund, price)
        return fund
    return None


# ── Auto-load from cache (startup, no network) ───────────────────────────────

def _auto_load_from_cache_entries(tickers: list[tuple]) -> list[dict]:
    """Load all available cache entries without any network calls."""
    results = []
    for ticker, name, asset_class, group in tickers:
        entry = _load_cache_entry(ticker)
        if entry:
            results.append(entry)
        else:
            results.append({
                "ticker": ticker, "name": name,
                "asset_class": asset_class, "group": group,
                "ok": False, "error": "No cache",
            })
    return results


# ── Scan summary (used by dashboard tiles) ───────────────────────────────────

def save_scan_summary(data: dict) -> None:
    try:
        _SCAN.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception:
        pass


def load_scan_summary() -> dict:
    try:
        if _SCAN.exists():
            return json.loads(_SCAN.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ── Sector medians (delegated to scoring.py) ──────────────────────────────────

def compute_sector_medians(instruments: list[dict]) -> dict:
    from utils.scoring import compute_sector_medians as _csm
    return _csm(instruments)
