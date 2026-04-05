"""
data/fetcher.py - Two-layer smart cache backed by SQLite.

Architecture:
  * fetch_one()           - public API, unchanged signature
  * _fetch_fundamentals() - slow data: ROE, D/E, EV/EBITDA, FCF (7-day TTL)
  * _fetch_prices()       - fast data: price, 52w range, P/E, P/B (15-min TTL)
  * _merge()              - combines both into the dict scoring.py expects

Cache behaviour:
  - Fundamentals are fetched at most once per 7 days
  - Prices refresh every 15 min while any market is open, 8h when closed
  - Both layers stored in a single SQLite file (cache/cache.db)
  - Startup reads 655 tickers in < 1 second vs. 655 file-system opens

On first run, existing JSON files in cache/instruments/ are migrated
automatically so no historical data is lost.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import yfinance as yf
except ImportError:
    yf = None

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from data import cache_db as _db

# -- TTLs --
FUNDAMENTALS_TTL_HOURS = 7 * 24
PRICE_TTL_MINUTES      = 15
PRICE_TTL_CLOSED_MIN   = 60 * 8

# -- One-time migration from old JSON files --
_BASE = Path(__file__).parent.parent / "cache"
_migrated_flag = _BASE / ".migrated_to_sqlite"

if not _migrated_flag.exists() and not _db.any_data_exists():
    _n = _db.migrate_from_json(
        instruments_dir=_BASE / "instruments",
        fundamentals_dir=_BASE / "fundamentals",
        prices_dir=_BASE / "prices",
    )
    if _n > 0:
        _migrated_flag.touch()


# -- Market hours (UTC) --

def _market_open():
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    h = now.hour
    return (7 <= h < 17) or (13 <= h < 20)


def _price_ttl_min():
    return PRICE_TTL_MINUTES if _market_open() else PRICE_TTL_CLOSED_MIN


def _age_minutes(data):
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


def _fund_fresh(ticker):
    data = _db.get_fundamentals(ticker)
    return bool(data) and _age_minutes(data) < FUNDAMENTALS_TTL_HOURS * 60


def _price_fresh(ticker):
    data = _db.get_prices(ticker)
    return bool(data) and _age_minutes(data) < _price_ttl_min()


def _yf_info(ticker, max_attempts=3):
    if yf is None:
        return {}
    last_err = None
    for attempt in range(max_attempts):
        try:
            t    = yf.Ticker(ticker)
            info = t.info or {}
            empty = not info or (
                not info.get("regularMarketPrice")
                and not info.get("currentPrice")
                and not info.get("navPrice")
                and not info.get("previousClose")
            )
            if empty and attempt < max_attempts - 1:
                time.sleep(2 ** attempt * 3)
                continue
            return info
        except Exception as e:
            last_err = e
            err_s = str(e).lower()
            if ("429" in err_s or "too many" in err_s or "rate limit" in err_s)                     and attempt < max_attempts - 1:
                time.sleep(2 ** attempt * 5)
                continue
            break
    raise last_err or RuntimeError("yfinance returned empty info")


def _fetch_fundamentals(ticker, name, asset_class, group, force=False):
    cached = _db.get_fundamentals(ticker)
    if not force and cached and _age_minutes(cached) < FUNDAMENTALS_TTL_HOURS * 60:
        return cached

    try:
        info = _yf_info(ticker)
    except Exception as e:
        if cached:
            cached["_stale"] = True
            return cached
        return {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False,
            "error": "Fundamentals fetch failed: " + str(e),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    mkt_cap = info.get("marketCap")
    fcf     = info.get("freeCashflow")
    p_fcf   = (mkt_cap / fcf) if (mkt_cap and fcf and fcf > 0) else None

    result = {
        "ticker":         ticker,
        "name":           name,
        "asset_class":    asset_class,
        "group":          group,
        "sector":         info.get("sector", ""),
        "industry":       info.get("industry", ""),
        "description":    (info.get("longBusinessSummary") or "")[:400],
        "ok":             True,
        "roe":            info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "debt_equity":    info.get("debtToEquity"),
        "profit_margin":  info.get("profitMargins"),
        "free_cashflow":  fcf,
        "market_cap":     mkt_cap,
        "p_fcf":          p_fcf,
        "ev_ebitda":      info.get("enterpriseToEbitda"),
        "revenue":        info.get("totalRevenue"),
        "ebitda":         info.get("ebitda"),
        "aum":            info.get("totalAssets"),
        "ter":            info.get("annualReportExpenseRatio"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth":info.get("earningsGrowth"),
        "roa":            info.get("returnOnAssets"),
        "fund_family":    info.get("fundFamily", ""),
        # -- Phase 1: additional fields for Z-Score, accrual ratio, debt quality --
        "total_assets":      info.get("totalAssets"),
        "total_debt":        info.get("totalDebt"),
        "net_income":        info.get("netIncomeToCommon") or info.get("netIncome"),
        "operating_cashflow":info.get("operatingCashflow"),
        "ebit":              info.get("operatingIncome") or info.get("ebitda"),
        "working_capital":   info.get("workingCapital"),
        "retained_earnings": info.get("retainedEarnings"),
        "current_ratio":     info.get("currentRatio"),
        # -- Phase 2: ROIC inputs --
        "total_equity": (
            info.get("totalStockholderEquity") or (
                (info.get("bookValue") or 0) * (info.get("sharesOutstanding") or 0)
            ) or None
        ),
        "total_cash":        info.get("totalCash"),
        "effective_tax_rate":info.get("effectiveTaxRate"),
        "cached_at":      datetime.now(timezone.utc).isoformat(),
        "cache_layer":    "fundamentals",
    }

    # -- Phase 3: historical cashflow + financials (optional — never blocks fetch) --
    # Provides: buyback_1y, capex_1y for capital allocation
    #           net_income_avg_3y for normalised earnings flag
    if result.get("ok") and asset_class == "Stock":
        try:
            import pandas as _pd
            yf_t = yf.Ticker(ticker)

            # ── Cashflow: buybacks + capex ────────────────────────────────
            cf = yf_t.cashflow
            if cf is not None and not cf.empty:
                # Columns are dates; take up to 4 most recent years
                cols = sorted(cf.columns, reverse=True)[:4]

                def _cf_row(df, *names):
                    """Return list of non-NaN values from first matching row."""
                    for nm in names:
                        if nm in df.index:
                            return [
                                abs(float(df.loc[nm, c]))
                                for c in cols
                                if _pd.notna(df.loc[nm, c])
                            ]
                    return []

                buybacks = _cf_row(cf,
                    "Repurchase Of Capital Stock",
                    "RepurchaseOfCapitalStock",
                    "Common Stock Repurchased",
                )
                capex_raw = _cf_row(cf,
                    "Capital Expenditure",
                    "CapitalExpenditure",
                    "Purchase Of Property Plant And Equipment",
                )

                result["buyback_1y"]   = buybacks[0]  if buybacks  else None
                result["capex_1y"]     = capex_raw[0] if capex_raw else None
                # 3-year average capex for intensity ratio
                result["capex_avg_3y"] = (
                    sum(capex_raw[:3]) / len(capex_raw[:3]) if capex_raw else None
                )

            # ── Annual financials: historical net income ──────────────────
            fin = yf_t.financials
            if fin is not None and not fin.empty:
                fcols = sorted(fin.columns, reverse=True)[:4]

                def _fin_row(df, *names):
                    return [
                        float(df.loc[nm, c])
                        for nm in names if nm in df.index
                        for c in fcols
                        if _pd.notna(df.loc[nm, c])
                    ][:4]

                ni_hist = _fin_row(fin, "Net Income", "NetIncome")
                # Average of up to 3 most recent years (require at least 2)
                result["net_income_hist"]   = ni_hist
                result["net_income_avg_3y"] = (
                    sum(ni_hist[:3]) / len(ni_hist[:3])
                    if len(ni_hist) >= 2 else None
                )

        except Exception:
            pass  # Phase 3 data is supplementary — never surface errors to user

    _db.set_fundamentals(ticker, result)
    return result


def _fetch_prices(ticker, force=False):
    cached = _db.get_prices(ticker)
    if not force and cached and _age_minutes(cached) < _price_ttl_min():
        return cached

    try:
        info = _yf_info(ticker)
    except Exception as e:
        if cached:
            cached["_stale"] = True
            return cached
        return {
            "ok": False,
            "price_error": str(e),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    price = (info.get("regularMarketPrice")
             or info.get("currentPrice")
             or info.get("navPrice")
             or info.get("previousClose"))

    low52  = info.get("fiftyTwoWeekLow")
    high52 = info.get("fiftyTwoWeekHigh")
    pos_52w = None
    if low52 and high52 and high52 > low52 and price:
        pos_52w = (price - low52) / (high52 - low52)

    return_1y = return_3m = None
    try:
        if yf:
            hist = yf.Ticker(ticker).history(period="1y")
            if len(hist) >= 2:
                first = hist["Close"].iloc[0]
                last  = hist["Close"].iloc[-1]
                if first and first > 0:
                    return_1y = (last - first) / first
            if len(hist) >= 63:
                f3 = hist["Close"].iloc[-63]
                if f3 and f3 > 0:
                    return_3m = (last - f3) / f3
    except Exception:
        pass

    prev = info.get("previousClose")
    result = {
        "price":          price,
        "currency":       info.get("currency", ""),
        "pe":             info.get("trailingPE") or info.get("forwardPE"),
        "fwd_pe":         info.get("forwardPE"),
        "pb":             info.get("priceToBook"),
        "price_to_book":  info.get("priceToBook"),
        # yfinance returns dividendYield as a decimal fraction (e.g. 0.034 for 3.4%).
        # Normalise to percentage form (3.4) so all downstream code is consistent.
        # Guard handles the rare edge-case where yfinance returns it already as a
        # percentage (> 1.0) — same logic used in the deepdive watchlist search.
        "div_yield":      (lambda _r: (
            None if _r is None
            else round(min(float(_r), 99.0), 4) if float(_r) > 1.0   # already %
            else round(float(_r) * 100, 4)                            # decimal → %
        ))(info.get("dividendYield")),
        "low_52w":        low52,
        "high_52w":       high52,
        "pct_from_high": (round((price / high52 - 1) * 100, 1)
                          if price and high52 and high52 > 0 else None),
        "pos_52w":        pos_52w,
        "return_1y":      return_1y,
        "return_3m":      return_3m,
        "yr1_pct":        (round(return_1y * 100, 1) if return_1y is not None else None),
        "ytd_pct":        None,
        "prev_close":     prev,
        "day_change_pct": (((price - prev) / prev) if price and prev and prev > 0 else None),
        "exchange":       info.get("exchange", ""),
        "cached_at":      datetime.now(timezone.utc).isoformat(),
        "cache_layer":    "prices",
    }
    _db.set_prices(ticker, result)
    return result


def _merge(fund, price):
    merged = {**fund}
    for k, v in price.items():
        if v is not None:
            merged[k] = v
    merged["fetched_at"] = price.get("cached_at") or fund.get("cached_at")
    merged["ok"] = fund.get("ok", False) and not price.get("price_error")
    return merged


# -- Public API --

def fetch_one(ticker, name, asset_class, group, force_refresh=False):
    """
    Fetch a single instrument using two-layer cache.
    force_refresh=True bypasses both caches (manual Refresh button).
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


def fetch_prices_only(ticker, force=False):
    """Refresh only the price layer (fast)."""
    return _fetch_prices(ticker, force=force)


def refresh_all_prices(tickers, progress_cb=None):
    """
    Refresh prices for all tickers without touching fundamentals.
    tickers: list of (ticker, name, asset_class, group)
    """
    results = []
    total = len(tickers)
    for i, (ticker, name, asset_class, group) in enumerate(tickers):
        fund  = _db.get_fundamentals(ticker) or {
            "ticker": ticker, "name": name, "asset_class": asset_class,
            "group": group, "ok": False, "error": "No fundamentals cache",
        }
        price = _fetch_prices(ticker, force=True)
        merged = _merge(fund, price) if fund.get("ok") else fund
        results.append(merged)
        if progress_cb:
            progress_cb((i + 1) / max(total, 1), "Updating price - " + name)
        if i < total - 1:
            time.sleep(0.4)
    return results


# -- Cache introspection --

def cache_age_hours():
    return _db.oldest_price_age_hours()


def fundamentals_age_days():
    return _db.oldest_fundamentals_age_days()


def any_cache_exists():
    return _db.any_data_exists()


def _cache_is_fresh(ticker):
    return _price_fresh(ticker)


def _load_cache(ticker):
    """Load merged fundamentals+price from SQLite without any network call."""
    fund  = _db.get_fundamentals(ticker)
    price = _db.get_prices(ticker)
    if fund and fund.get("ok"):
        return _merge(fund, price) if price else fund
    return None


def _auto_load_from_cache_entries(tickers):
    results = []
    for ticker, name, asset_class, group in tickers:
        entry = _load_cache(ticker)
        if entry:
            entry["name"]        = name
            entry["group"]       = group
            entry["asset_class"] = asset_class
            results.append(entry)
        else:
            results.append({
                "ticker": ticker, "name": name,
                "asset_class": asset_class, "group": group,
                "ok": False, "error": "No cache",
            })
    return results


# -- Scan summary --

_SCAN = _BASE / "scan_summary.json"


def save_scan_summary(data):
    try:
        _SCAN.write_text(json.dumps(data, default=str), encoding="utf-8")
    except Exception:
        pass


def load_scan_summary():
    try:
        if _SCAN.exists():
            return json.loads(_SCAN.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# -- Sector medians --

def compute_sector_medians(instruments):
    from utils.scoring import compute_sector_medians as _csm
    return _csm(instruments)

