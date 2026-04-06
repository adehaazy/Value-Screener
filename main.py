"""
main.py — FastAPI wrapper for the Value Screener application.

Exposes the screener's core data as a JSON API so that any frontend
(React, Next.js, mobile app, etc.) can consume it without touching Streamlit.

Endpoints
---------
GET    /api/screener          — scored instruments
GET    /api/briefing          — AI/rule-based market briefing
GET    /api/signals           — alerts & signal list
GET    /api/watchlist         — user watchlist with live data
GET    /api/macro             — macro indicator data (US + UK)
GET    /api/portfolio         — holdings merged with live scored data + summary stats
POST   /api/portfolio         — add or update a holding (upsert by ticker)
DELETE /api/portfolio/{ticker} — remove a holding

Run
---
    uvicorn main:app --reload --port 8000

Dependencies (add to requirements.txt if not already present)
-------------------------------------------------------------
    fastapi
    uvicorn[standard]
    yfinance
    pandas
    anthropic
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

import threading

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Make sure the project root is on sys.path so local modules resolve ─────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Local imports (mirror what app.py uses) ────────────────────────────────────
from data.universe import UNIVERSE
from data.fetcher import (
    fetch_one,
    compute_sector_medians,
    load_scan_summary,
    any_cache_exists,
    _load_cache,
)
from utils.scoring import score_all, score_label, score_colour, DEFAULT_QUALITY_THRESHOLDS
from utils.verdicts import add_verdicts
from utils.signals import load_latest_signals, get_last_run_time, signals_summary
from surveillance.briefing import load_briefing
from user_data import (
    load_watchlist,
    save_watchlist,
    add_to_watchlist as _add_to_watchlist,
    remove_from_watchlist,
    load_prefs,
    load_holdings,
    save_holdings,
    add_to_holdings,
    remove_from_holdings,
)
from utils.signal_enricher import get_macro_context, get_uk_macro_context

# ══════════════════════════════════════════════════════════════════════════════
# App setup
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Value Screener API",
    description="JSON API wrapper around the Value Screener investment research tool.",
    version="1.0.0",
)

# CORS — allow all origins (tighten in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _safe_float(value: Any) -> Any:
    """Convert numpy floats / NaN / Inf to plain Python types for JSON safety."""
    try:
        import math
        import numpy as np
        if isinstance(value, (np.floating, np.integer)):
            value = value.item()
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    except Exception:
        return value


def _clean_record(record: dict) -> dict:
    """Recursively make a dict JSON-serialisable."""
    cleaned = {}
    for k, v in record.items():
        if isinstance(v, dict):
            cleaned[k] = _clean_record(v)
        elif isinstance(v, list):
            cleaned[k] = [
                _clean_record(i) if isinstance(i, dict) else _safe_float(i)
                for i in v
            ]
        else:
            cleaned[k] = _safe_float(v)
    return cleaned


def _build_from_cache() -> tuple[list[dict], dict] | None:
    """
    Build a scored instrument list using ONLY cached data — no network calls.
    Returns (instruments, sector_medians) or None if the cache is completely empty.
    Fast: reads all rows from SQLite in a single query.
    """
    raw: list[dict] = []
    for group, meta in UNIVERSE.items():
        asset_class = meta.get("asset_class", "Stock")
        for ticker, name in meta["tickers"].items():
            cached = _load_cache(ticker)
            if cached:
                cached.setdefault("name", name)
                cached.setdefault("asset_class", asset_class)
                cached.setdefault("group", group)
                raw.append(cached)

    if not raw:
        return None

    sector_medians = compute_sector_medians(raw)
    scored = score_all(raw, sector_medians)
    enriched = add_verdicts(scored, sector_medians)
    for inst in enriched:
        score = inst.get("score")
        if score is not None:
            inst["score_label"] = score_label(score)
            inst["score_colour"] = score_colour(score)
    return enriched, sector_medians


# Background refresh state — prevents concurrent full-universe fetches
_refresh_lock = threading.Lock()
_refresh_in_progress = False


def _background_refresh():
    """Fetch all tickers from yfinance in the background, populating the cache."""
    global _refresh_in_progress
    with _refresh_lock:
        _refresh_in_progress = True
    try:
        _build_instruments(force_refresh=False)
    except Exception:
        pass
    finally:
        with _refresh_lock:
            _refresh_in_progress = False


def _build_instruments(force_refresh: bool = False) -> tuple[list[dict], dict]:
    """
    Fetch, score, and enrich all instruments from UNIVERSE.
    Returns (instruments, sector_medians).
    Falls back to cached data for speed when force_refresh is False.
    """
    raw: list[dict] = []

    for group, meta in UNIVERSE.items():
        asset_class = meta.get("asset_class", "Stock")
        for ticker, name in meta["tickers"].items():
            if force_refresh:
                data = fetch_one(ticker, name, asset_class, group, force_refresh=True)
            else:
                # Prefer cached data; fall back to live fetch only if nothing is cached
                cached = _load_cache(ticker)
                if cached:
                    cached.setdefault("name", name)
                    cached.setdefault("asset_class", asset_class)
                    cached.setdefault("group", group)
                    data = cached
                else:
                    data = fetch_one(ticker, name, asset_class, group)
            raw.append(data)

    sector_medians = compute_sector_medians(raw)
    scored = score_all(raw, sector_medians)
    enriched = add_verdicts(scored, sector_medians)

    # Attach human-readable label + colour for convenience
    for inst in enriched:
        score = inst.get("score")
        if score is not None:
            inst["score_label"] = score_label(score)
            inst["score_colour"] = score_colour(score)

    return enriched, sector_medians


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/screener", summary="Scored instrument list")
def get_screener(background_tasks: BackgroundTasks, refresh: bool = False) -> dict:
    """
    Returns all instruments in UNIVERSE, scored and enriched with verdicts.

    Strategy: cache-first, background-refresh.
      1. Try to serve from SQLite cache immediately (fast — <1s).
      2. If cache is empty OR refresh=true is requested, do a full live fetch
         (slow — can take several minutes for 648 tickers on first deploy).
      3. If cache has partial data, serve it immediately and kick off a
         background refresh so future requests will have fresh data.

    Query params
    ------------
    refresh : bool  (default False)
        Pass ?refresh=true to force a live fetch bypassing cache.
    """
    global _refresh_in_progress
    try:
        # Force-refresh: caller explicitly wants live data
        if refresh:
            instruments, sector_medians = _build_instruments(force_refresh=True)
            clean = [_clean_record(i) for i in instruments]
            return {"ok": True, "count": len(clean), "from_cache": False,
                    "sector_medians": _clean_record(sector_medians), "instruments": clean}

        # Try cache first
        cached_result = _build_from_cache()
        if cached_result:
            instruments, sector_medians = cached_result
            clean = [_clean_record(i) for i in instruments]
            # Kick off background refresh if nothing is already running
            with _refresh_lock:
                already_running = _refresh_in_progress
            if not already_running:
                background_tasks.add_task(_background_refresh)
            return {"ok": True, "count": len(clean), "from_cache": True,
                    "sector_medians": _clean_record(sector_medians), "instruments": clean}

        # Cache is empty (fresh deploy) — must do a full live fetch.
        # This is the slow path; it only happens once after a fresh deploy.
        instruments, sector_medians = _build_instruments(force_refresh=False)
        clean = [_clean_record(i) for i in instruments]
        return {"ok": True, "count": len(clean), "from_cache": False,
                "sector_medians": _clean_record(sector_medians), "instruments": clean}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/briefing", summary="Market briefing")
def get_briefing() -> dict:
    """
    Returns the most recently generated market briefing.
    Produced by surveillance/briefing.py and persisted to disk.
    """
    try:
        briefing = load_briefing()
        if not briefing:
            return {
                "ok": False,
                "briefing": None,
                "message": "No briefing generated yet. Run a surveillance scan first.",
            }
        return {
            "ok": True,
            "briefing": _clean_record(briefing) if isinstance(briefing, dict) else briefing,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/signals", summary="Alerts and signals list")
def get_signals() -> dict:
    """
    Returns the current signals list, including score drift, value opportunities,
    macro stress, news alerts, insider activity, and SEC 8-K filings.
    Loaded from cache/signals_history.json — run a scan to refresh.
    """
    try:
        signals = load_latest_signals()
        last_run = get_last_run_time()
        summary = signals_summary(signals)
        clean = [_clean_record(s) for s in signals]
        return {
            "ok": True,
            "last_run": last_run,
            "summary": summary,
            "count": len(clean),
            "signals": clean,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/watchlist", summary="Watchlist with live data")
def get_watchlist() -> dict:
    """
    Returns the user's saved watchlist tickers with scored instrument data.
    Instruments in UNIVERSE use cached scores; tickers added manually are
    fetched and scored on the fly.
    """
    try:
        watchlist_items: list[dict] = load_watchlist(user_id=None)
        watchlist_tickers: list[str] = [
            i.get("ticker", i) if isinstance(i, dict) else i
            for i in watchlist_items
        ]

        if not watchlist_tickers:
            return {"ok": True, "tickers": [], "count": 0, "instruments": []}

        # Build a lookup from the full scored universe
        instruments, sector_medians = _build_instruments()
        universe_map: dict[str, dict] = {inst["ticker"]: inst for inst in instruments}

        result: list[dict] = []
        for ticker in watchlist_tickers:
            if ticker in universe_map:
                result.append(universe_map[ticker])
            else:
                # Ticker is on the watchlist but not in UNIVERSE — fetch directly
                live = fetch_one(ticker, ticker, "Stock", "Watchlist")
                if live.get("ok"):
                    scored_list = score_all([live], {})
                    enriched = add_verdicts(scored_list, {})
                    inst = enriched[0] if enriched else live
                    score = inst.get("score")
                    if score is not None:
                        inst["score_label"] = score_label(score)
                        inst["score_colour"] = score_colour(score)
                    result.append(inst)
                else:
                    result.append(live)  # return the error record so caller knows

        clean = [_clean_record(i) for i in result]
        return {
            "ok": True,
            "tickers": watchlist_tickers,
            "count": len(clean),
            "instruments": clean,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/watchlist", summary="Add ticker to watchlist", status_code=200)
def add_watchlist_item(body: dict) -> dict:
    """
    Add a ticker to the watchlist.
    Body: { "ticker": "BP.L", "name": "BP plc" }
    No-op if ticker is already present.
    """
    try:
        ticker = (body.get("ticker") or "").upper().strip()
        if not ticker:
            raise HTTPException(status_code=422, detail="ticker is required")
        name = body.get("name") or ticker
        _add_to_watchlist(user_id=None, item={"ticker": ticker, "name": name})
        return {"ok": True, "ticker": ticker, "action": "added"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/watchlist/{ticker}", summary="Remove ticker from watchlist")
def delete_watchlist_item(ticker: str) -> dict:
    """
    Remove a ticker from the watchlist by ticker symbol.
    Returns 404 if the ticker is not on the watchlist.
    """
    try:
        ticker = ticker.upper().strip()
        current = load_watchlist(user_id=None)
        tickers = [
            (i.get("ticker", i) if isinstance(i, dict) else i)
            for i in current
        ]
        if ticker not in tickers:
            raise HTTPException(status_code=404, detail=f"{ticker} not found in watchlist")
        remove_from_watchlist(user_id=None, ticker=ticker)
        return {"ok": True, "ticker": ticker, "action": "removed"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/macro", summary="Macro indicator data")
def get_macro() -> dict:
    """
    Returns macro context for US and UK markets.
    Includes yield curve, credit spreads, VIX, and any pre-computed signals
    from the surveillance layer.
    """
    try:
        us_macro = get_macro_context()
        uk_macro = get_uk_macro_context()
        return {
            "ok": True,
            "us": _clean_record(us_macro) if isinstance(us_macro, dict) else us_macro,
            "uk": _clean_record(uk_macro) if isinstance(uk_macro, dict) else uk_macro,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio — request body model
# ══════════════════════════════════════════════════════════════════════════════

class HoldingIn(BaseModel):
    """
    Fields the client supplies when adding or updating a holding.
    All fields except ticker, shares, and avg_cost are optional — the
    endpoint will preserve existing values for fields not supplied on update.
    """
    ticker:        str   = Field(..., description="Yahoo Finance ticker, e.g. AAPL or BP.L")
    shares:        float = Field(..., gt=0, description="Number of shares (fractional OK)")
    avg_cost:      float = Field(..., gt=0, description="Average cost basis per share in `currency`")
    currency:      str   = Field("USD",  description="ISO-4217 currency of avg_cost, e.g. USD, GBP, EUR")
    account:       Optional[str]   = Field(None, description="Account label, e.g. ISA, SIPP, IRA, Trading")
    notes:         Optional[str]   = Field(None, description="Free-text notes — the investment thesis, reminders, etc.")
    target_weight: Optional[float] = Field(None, ge=0, le=100, description="Target portfolio weight %; enables drift alerting")


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio — helpers
# ══════════════════════════════════════════════════════════════════════════════

def _enrich_holding(h: dict, universe_map: dict[str, dict]) -> dict:
    """
    Merge a raw holdings record with live scored instrument data.
    Returns a single enriched holding dict ready to be JSON-serialised.
    """
    ticker   = h.get("ticker", "")
    shares   = float(h.get("shares",   0) or 0)
    avg_cost = float(h.get("avg_cost", 0) or 0)

    # Resolve instrument — prefer universe cache, fall back to live fetch
    if ticker in universe_map:
        inst = dict(universe_map[ticker])
    else:
        live = fetch_one(ticker, ticker, "Stock", "Portfolio")
        if live.get("ok"):
            scored   = score_all([live], {})
            enriched = add_verdicts(scored, {})
            inst     = enriched[0] if enriched else live
            sc = inst.get("score")
            if sc is not None:
                inst["score_label"] = score_label(sc)
                inst["score_colour"] = score_colour(sc)
        else:
            inst = live

    current_price = float(inst.get("price") or 0)
    market_value  = shares * current_price
    cost_basis    = shares * avg_cost
    gain          = market_value - cost_basis
    gain_pct      = (gain / cost_basis * 100) if cost_basis else 0.0

    return {
        # User-supplied fields
        "ticker":        ticker,
        "shares":        shares,
        "avg_cost":      avg_cost,
        "currency":      h.get("currency",      "USD"),
        "account":       h.get("account",       ""),
        "notes":         h.get("notes",         ""),
        "target_weight": h.get("target_weight", None),
        # Server-computed P&L
        "market_value":  round(market_value, 2),
        "cost_basis":    round(cost_basis,   2),
        "gain":          round(gain,         2),
        "gain_pct":      round(gain_pct,     4),
        "weight":        0.0,   # filled in second pass by caller
        # Full scored instrument record (price, P/E, score, verdict, …)
        "instrument":    _clean_record(inst),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio — routes
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/portfolio", summary="Portfolio holdings with live scored data")
def get_portfolio() -> dict:
    """
    Returns the user's portfolio holdings merged with live scored instrument data.

    Each holding record contains:

    - **User-supplied**: ticker, shares, avg_cost, currency, account, notes, target_weight
    - **Server-computed**: market_value, cost_basis, gain, gain_pct, weight (% of total)
    - **Live instrument data**: full scored record — price, P/E, P/B, div_yield, score,
      score_label, verdict, sector, signals, badges, …

    A top-level `summary` object gives portfolio-wide totals.

    Instruments in UNIVERSE are served from cache (fast).
    Holdings not in UNIVERSE are fetched and scored on the fly.

    The `weight_drift` field on each holding is populated when the user has set a
    `target_weight` — positive means the position is over-weight, negative under-weight.
    """
    try:
        raw_holdings: list[dict] = load_holdings(user_id=None)

        if not raw_holdings:
            return {
                "ok": True,
                "count": 0,
                "holdings": [],
                "summary": {
                    "total_value":    0.0,
                    "total_cost":     0.0,
                    "total_gain":     0.0,
                    "total_gain_pct": 0.0,
                },
            }

        # Build scored universe lookup (uses cache — fast path)
        instruments, _medians = _build_instruments(force_refresh=False)
        universe_map: dict[str, dict] = {inst["ticker"]: inst for inst in instruments}

        # First pass — enrich each holding and accumulate totals
        enriched: list[dict] = []
        total_value = 0.0
        total_cost  = 0.0

        for h in raw_holdings:
            record = _enrich_holding(h, universe_map)
            total_value += record["market_value"]
            total_cost  += record["cost_basis"]
            enriched.append(record)

        total_gain     = total_value - total_cost
        total_gain_pct = (total_gain / total_cost * 100) if total_cost else 0.0

        # Second pass — fill actual weight and weight_drift
        for record in enriched:
            actual_weight = (record["market_value"] / total_value * 100) if total_value else 0.0
            record["weight"] = round(actual_weight, 2)
            target = record.get("target_weight")
            record["weight_drift"] = round(actual_weight - target, 2) if target is not None else None

        return {
            "ok":    True,
            "count": len(enriched),
            "holdings": enriched,
            "summary": {
                "total_value":    round(total_value,    2),
                "total_cost":     round(total_cost,     2),
                "total_gain":     round(total_gain,     2),
                "total_gain_pct": round(total_gain_pct, 4),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/portfolio", summary="Add or update a holding", status_code=200)
def upsert_holding(body: HoldingIn) -> dict:
    """
    Add a new holding or update an existing one (upsert by ticker).

    If the ticker is already in the portfolio the existing record is replaced
    in full — pass all fields you want to keep, not just the ones that changed.

    Returns the updated portfolio summary so the UI can refresh without a
    second GET request.
    """
    try:
        ticker = body.ticker.upper().strip()
        item   = {
            "ticker":        ticker,
            "shares":        body.shares,
            "avg_cost":      body.avg_cost,
            "currency":      body.currency.upper(),
            "account":       body.account or "",
            "notes":         body.notes   or "",
            "target_weight": body.target_weight,
        }

        # Load, replace-or-append, save
        holdings = load_holdings(user_id=None)
        holdings = [h for h in holdings if h.get("ticker", "").upper() != ticker]
        holdings.append(item)
        save_holdings(user_id=None, items=holdings)

        return {"ok": True, "ticker": ticker, "action": "upserted"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/portfolio/{ticker}", summary="Remove a holding")
def delete_holding(ticker: str) -> dict:
    """
    Remove a holding from the portfolio by ticker.
    Returns 404 if the ticker is not in the portfolio.
    """
    try:
        ticker = ticker.upper().strip()
        holdings = load_holdings(user_id=None)
        before   = len(holdings)
        holdings = [h for h in holdings if h.get("ticker", "").upper() != ticker]

        if len(holdings) == before:
            raise HTTPException(status_code=404, detail=f"{ticker} not found in portfolio")

        save_holdings(user_id=None, items=holdings)
        return {"ok": True, "ticker": ticker, "action": "deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok", "cache_populated": any_cache_exists()}


# ══════════════════════════════════════════════════════════════════════════════
# Dev entrypoint
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
