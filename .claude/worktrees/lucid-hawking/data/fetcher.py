"""
Data fetcher — pulls instrument data from Yahoo Finance via yfinance.
Caches results locally so the app loads instantly on subsequent opens.
Cache is considered fresh for 6 hours.
"""

import json
import time
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

try:
    import yfinance as yf
except ImportError:
    yf = None

CACHE_DIR = Path(__file__).parent.parent / "cache" / "instruments"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_HOURS = 6


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_file(ticker: str) -> Path:
    safe = ticker.replace(".", "_").replace("-", "_")
    return CACHE_DIR / f"{safe}.json"


# Exposed as part of public API (used by app.py auto-load)
def _cache_is_fresh(ticker: str) -> bool:
    p = _cache_file(ticker)
    if not p.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)
    return age < timedelta(hours=CACHE_TTL_HOURS)

def _load_cache(ticker: str) -> dict:
    with open(_cache_file(ticker)) as f:
        return json.load(f)

def _save_cache(ticker: str, data: dict):
    with open(_cache_file(ticker), "w") as f:
        json.dump(data, f, default=str)


# ── Safe type helpers ─────────────────────────────────────────────────────────

def _float(v):
    """Convert any value to float, returning None if not possible."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else f  # NaN check
    except (TypeError, ValueError):
        return None


# ── Single ticker fetch ───────────────────────────────────────────────────────

def fetch_one(ticker: str, name: str, asset_class: str, group: str,
              force_refresh: bool = False) -> dict:
    """
    Fetch all metrics for one ticker.
    Uses cache if fresh, otherwise calls Yahoo Finance.
    force_refresh=True bypasses the cache and always fetches live data.
    """
    if not force_refresh and _cache_is_fresh(ticker):
        cached = _load_cache(ticker)
        # Ensure group/name are up to date (in case universe changed)
        cached["name"] = name
        cached["group"] = group
        return cached

    if yf is None:
        return {"ticker": ticker, "name": name, "asset_class": asset_class,
                "group": group, "ok": False, "error": "yfinance not installed"}

    # Retry up to 3 times with exponential backoff on rate-limit errors
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            # If Yahoo returned an empty info dict with no price, treat as rate-limited
            if not info or (not info.get("regularMarketPrice") and not info.get("currentPrice")
                            and not info.get("navPrice") and not info.get("previousClose")):
                if attempt < max_attempts - 1:
                    time.sleep(2 ** attempt * 3)  # 3s, 6s
                    continue

            break  # success — exit retry loop

        except Exception as e:
            err_str = str(e).lower()
            if ("429" in err_str or "too many" in err_str or "rate limit" in err_str) \
                    and attempt < max_attempts - 1:
                time.sleep(2 ** attempt * 5)  # 5s, 10s
                continue
            # Non-rate-limit error — return immediately
            return {
                "ticker": ticker, "name": name, "asset_class": asset_class,
                "group": group, "ok": False, "error": str(e),
                "fetched_at": datetime.now().isoformat(),
            }
    else:
        # Exhausted retries
        return {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False,
            "error": "Too Many Requests. Rate limited. Try after a while.",
            "fetched_at": datetime.now().isoformat(),
        }

    try:
        # Price history
        hist = t.history(period="1y")
        hist_ytd = t.history(start=f"{datetime.now().year}-01-01")

        price     = _float(hist["Close"].iloc[-1])  if not hist.empty else None
        high_52w  = _float(hist["Close"].max())     if not hist.empty else None
        low_52w   = _float(hist["Close"].min())     if not hist.empty else None

        pct_from_high = None
        if price and high_52w and high_52w > 0:
            pct_from_high = round((price / high_52w - 1) * 100, 1)

        ytd_ret = None
        if not hist_ytd.empty and len(hist_ytd) > 1:
            ytd_ret = round((hist_ytd["Close"].iloc[-1] / hist_ytd["Close"].iloc[0] - 1) * 100, 1)

        yr1_ret = None
        if not hist.empty and len(hist) > 10:
            yr1_ret = round((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 1)

        div_raw = _float(info.get("dividendYield"))
        if div_raw is None:
            div_yield = None
        elif div_raw > 1.0:
            # yfinance returned yield already as a percentage (e.g. 4.16 meaning 4.16%)
            # — clamp to a realistic range and use as-is
            div_yield = round(min(div_raw, 99.0), 2)
        else:
            # Normal case: yfinance returned a decimal (e.g. 0.0416 meaning 4.16%)
            div_yield = round(div_raw * 100, 2)

        ter_raw = _float(info.get("annualReportExpenseRatio") or info.get("totalExpenseRatio"))

        result = {
            "ticker":        ticker,
            "name":          name,
            "asset_class":   asset_class,
            "group":         group,
            "sector":        info.get("sector") or info.get("fundFamily") or "Unknown",
            "industry":      info.get("industry", "—"),
            "currency":      info.get("currency", ""),
            "exchange":      info.get("exchange", ""),
            # Price
            "price":         _float(round(price, 2)) if price else None,
            "high_52w":      _float(round(high_52w, 2)) if high_52w else None,
            "low_52w":       _float(round(low_52w, 2)) if low_52w else None,
            "pct_from_high": pct_from_high,
            "ytd_pct":       ytd_ret,
            "yr1_pct":       yr1_ret,
            "market_cap":    _float(info.get("marketCap")),
            # Stock fundamentals
            "pe":            _float(info.get("trailingPE")),
            "fwd_pe":        _float(info.get("forwardPE")),
            "pb":            _float(info.get("priceToBook")),
            "ev_ebitda":     _float(info.get("enterpriseToEbitda")),
            "div_yield":     div_yield,
            "debt_equity":   _float(info.get("debtToEquity")),
            "roe":           _float(info.get("returnOnEquity")),
            "roa":           _float(info.get("returnOnAssets")),
            "profit_margin": _float(info.get("profitMargins")),
            "free_cashflow": _float(info.get("freeCashflow")),
            "revenue_growth": _float(info.get("revenueGrowth")),
            "earnings_growth": _float(info.get("earningsGrowth")),
            # Fund metrics
            "ter":           ter_raw,
            "aum":           _float(info.get("totalAssets")),
            "fund_family":   info.get("fundFamily", "—"),
            # Meta
            "fetched_at":    datetime.now().isoformat(),
            "ok":            True,
        }

        _save_cache(ticker, result)
        return result

    except Exception as e:
        return {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False, "error": str(e),
            "fetched_at": datetime.now().isoformat(),
        }


# ── Sector medians ────────────────────────────────────────────────────────────

def compute_sector_medians(instruments: list[dict]) -> dict:
    """
    Given a list of instrument dicts, compute median P/E, P/B, EV/EBITDA,
    ROE, and D/E per sector. Used for sector-relative valuation scoring.
    """
    from collections import defaultdict

    buckets = defaultdict(lambda: {"pe": [], "pb": [], "ev_ebitda": [], "roe": [], "de": []})

    for inst in instruments:
        if inst.get("asset_class") != "Stock" or not inst.get("ok"):
            continue
        sector = inst.get("sector", "Unknown")
        # Skip instruments with no meaningful sector — don't pollute other buckets
        if not sector or sector in ("Unknown", "—", ""):
            continue
        for key, field in [("pe", "pe"), ("pb", "pb"), ("ev_ebitda", "ev_ebitda"),
                           ("roe", "roe"), ("de", "debt_equity")]:
            val = _float(inst.get(field))
            if val and val > 0:
                buckets[sector][key].append(val)

    medians = {}
    for sector, vals in buckets.items():
        medians[sector] = {}
        for key, lst in vals.items():
            if lst:
                sorted_lst = sorted(lst)
                n = len(sorted_lst)
                mid = n // 2
                medians[sector][key] = sorted_lst[mid] if n % 2 else (sorted_lst[mid-1] + sorted_lst[mid]) / 2

    return medians


# ── Fetch summary cache ───────────────────────────────────────────────────────

def save_scan_summary(summary: dict):
    p = Path(__file__).parent.parent / "cache" / "scan_summary.json"
    with open(p, "w") as f:
        json.dump(summary, f, default=str)

def load_scan_summary() -> dict | None:
    p = Path(__file__).parent.parent / "cache" / "scan_summary.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None

def any_cache_exists() -> bool:
    """Returns True if at least one instrument cache file exists."""
    return any(CACHE_DIR.glob("*.json"))

def cache_age_hours() -> float | None:
    """Returns age in hours of the most recent cache file, or None if no cache."""
    files = list(CACHE_DIR.glob("*.json"))
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    age = datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)
    return round(age.total_seconds() / 3600, 1)
