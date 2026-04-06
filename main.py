"""
main.py — FastAPI wrapper for the Value Screener application.

Exposes the screener's core data as a JSON API so that any frontend
(React, Next.js, mobile app, etc.) can consume it without touching Streamlit.

Endpoints
---------
GET /api/screener   — scored instruments
GET /api/briefing   — AI/rule-based market briefing
GET /api/signals    — alerts & signal list
GET /api/watchlist  — user watchlist with live data
GET /api/macro      — macro indicator data (US + UK)

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
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
from user_data import load_watchlist, load_prefs
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
def get_screener(refresh: bool = False) -> dict:
    """
    Returns all instruments in UNIVERSE, scored and enriched with verdicts.

    Query params
    ------------
    refresh : bool  (default False)
        Pass ?refresh=true to bypass cache and pull live data from yfinance.
        Warning: can take 30–120 s for a full universe scan.
    """
    try:
        instruments, sector_medians = _build_instruments(force_refresh=refresh)
        clean = [_clean_record(i) for i in instruments]
        return {
            "ok": True,
            "count": len(clean),
            "sector_medians": _clean_record(sector_medians),
            "instruments": clean,
        }
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
        watchlist_tickers: list[str] = load_watchlist()

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
