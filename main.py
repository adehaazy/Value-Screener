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
GET    /api/price-history     — OHLCV price history for a ticker (yfinance)
GET    /api/deepdive          — full instrument record + AI investment thesis

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

import os
import sys
import json
import datetime
from pathlib import Path
from typing import Any, Optional

import threading

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Request
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
from surveillance.briefing import load_briefing, generate_briefing
from data.sources import fetch_news, run_all_sources
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
# Startup — seed cache + background warm-up
# ══════════════════════════════════════════════════════════════════════════════

import asyncio
import shutil

_SEED_DIR = ROOT / "cache-seed"


def _seed_cache() -> None:
    """
    Copy files from cache-seed/ into cache/ for any that don't already exist.
    This ensures Render always starts with a pre-warmed cache after a deploy,
    rather than an empty one that forces a slow full rebuild on first request.
    """
    if not _SEED_DIR.exists():
        return
    cache_dir = ROOT / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for src in _SEED_DIR.rglob("*"):
        if src.is_file():
            rel = src.relative_to(_SEED_DIR)
            dst = cache_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(src, dst)


def _background_warm_up() -> None:
    """
    Triggered on startup: refreshes the screener cache in the background so
    data is fresh without blocking the first incoming request.
    Only runs if a seed cache is already in place (so first request is fast).
    """
    try:
        _build_instruments(force_refresh=True)
    except Exception:
        pass


@app.on_event("startup")
async def on_startup() -> None:
    # 1. Seed cache from committed snapshot (instant — just file copies)
    _seed_cache()
    # 2. Kick off a background refresh so data freshens without blocking users
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _background_warm_up)


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


# ── Persistent cache file paths ───────────────────────────────────────────────
_CACHE_DIR       = ROOT / "cache"
_THESIS_CACHE    = _CACHE_DIR / "thesis_cache.json"
_RATE_LIMIT_FILE = _CACHE_DIR / "thesis_rate.json"
_DIVIDEND_CACHE  = _CACHE_DIR / "dividend_cache.json"

_THESIS_TTL_DAYS   = 7
_DIVIDEND_TTL_DAYS = 30
_THESIS_DAILY_LIMIT = 5

_json_lock = threading.Lock()


def _read_json(path: Path) -> dict:
    """Read a JSON file; return {} on missing or corrupt."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_json(path: Path, data: dict) -> None:
    """Atomically write data to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ── Thesis cache ───────────────────────────────────────────────────────────────

def _thesis_cache_get(ticker: str) -> str | None:
    """Return cached thesis if it exists and is < THESIS_TTL_DAYS old, else None."""
    with _json_lock:
        store = _read_json(_THESIS_CACHE)
        entry = store.get(ticker.upper())
        if not entry:
            return None
        try:
            age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(entry["generated_at"])).days
            if age < _THESIS_TTL_DAYS:
                return entry["thesis"]
        except Exception:
            pass
    return None


def _thesis_cache_set(ticker: str, thesis: str) -> None:
    """Persist a thesis to the cache."""
    with _json_lock:
        store = _read_json(_THESIS_CACHE)
        store[ticker.upper()] = {
            "thesis":       thesis,
            "generated_at": datetime.datetime.utcnow().isoformat(),
        }
        _write_json(_THESIS_CACHE, store)


# ── Rate limiter ───────────────────────────────────────────────────────────────

def _rate_limit_check(ip: str) -> tuple[bool, int]:
    """
    Returns (allowed, calls_remaining_today).
    Counts calls made by `ip` today (UTC date).
    Limit resets at midnight UTC.
    """
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    with _json_lock:
        store = _read_json(_RATE_LIMIT_FILE)
        record = store.get(ip, {})
        if record.get("date") != today:
            record = {"date": today, "count": 0}
        count = record.get("count", 0)
    return count < _THESIS_DAILY_LIMIT, max(0, _THESIS_DAILY_LIMIT - count)


def _rate_limit_increment(ip: str) -> None:
    """Record one thesis generation for `ip` today."""
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    with _json_lock:
        store = _read_json(_RATE_LIMIT_FILE)
        record = store.get(ip, {})
        if record.get("date") != today:
            record = {"date": today, "count": 0}
        record["count"] = record.get("count", 0) + 1
        store[ip] = record
        _write_json(_RATE_LIMIT_FILE, store)


# ── Dividend cache ─────────────────────────────────────────────────────────────

def _dividend_cache_get(ticker: str) -> dict | None:
    """Return cached dividend data if < DIVIDEND_TTL_DAYS old, else None."""
    with _json_lock:
        store = _read_json(_DIVIDEND_CACHE)
        entry = store.get(ticker.upper())
        if not entry:
            return None
        try:
            age = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(entry["generated_at"])).days
            if age < _DIVIDEND_TTL_DAYS:
                return entry
        except Exception:
            pass
    return None


def _dividend_cache_set(ticker: str, data: dict) -> None:
    """Persist dividend data for a ticker."""
    with _json_lock:
        store = _read_json(_DIVIDEND_CACHE)
        store[ticker.upper()] = {
            **data,
            "generated_at": datetime.datetime.utcnow().isoformat(),
        }
        _write_json(_DIVIDEND_CACHE, store)


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
    Returns the most recently generated market briefing with staleness metadata.
    Includes age_hours and stale flag (>4 hours) so the frontend can show a warning.
    """
    try:
        briefing = load_briefing()
        if not briefing:
            return {
                "ok": False,
                "briefing": None,
                "message": "No briefing generated yet. Run a surveillance scan first.",
                "age_hours": None,
                "stale": True,
            }

        # Compute age
        age_hours = None
        stale = False
        generated_at = briefing.get("generated_at")
        if generated_at:
            try:
                gen_dt = datetime.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                if gen_dt.tzinfo is None:
                    gen_dt = gen_dt.replace(tzinfo=datetime.timezone.utc)
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                age_hours = round((now_utc - gen_dt).total_seconds() / 3600, 1)
                stale = age_hours > 4
            except Exception:
                pass

        cleaned = _clean_record(briefing) if isinstance(briefing, dict) else briefing
        return {
            "ok":         True,
            "briefing":   cleaned,
            "age_hours":  age_hours,
            "stale":      stale,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/briefing/refresh", summary="Lightweight briefing refresh")
def refresh_briefing(background_tasks: BackgroundTasks) -> dict:
    """
    Triggers a fast briefing refresh: re-fetches macro data + RSS news +
    Yahoo Finance watchlist news. Does NOT re-score the full universe.
    Typically completes in 5–20 seconds. Results are persisted to
    cache/briefing.json so the next GET /api/briefing serves fresh data.
    """
    try:
        # Load watchlist tickers
        from user_data import load_watchlist as _load_wl
        wl_items = _load_wl(user_id=None)
        watchlist_tickers = [
            (i.get("ticker", i) if isinstance(i, dict) else i)
            for i in wl_items
        ]

        # Use cached instruments (no full fetch) for the briefing
        cached_result = _build_from_cache()
        if cached_result:
            instruments, _ = cached_result
        else:
            instruments = []

        # Load signals from cache (don't re-run)
        signals = load_latest_signals()

        # Refresh surveillance data — macro + news only (fast path)
        surveillance_data = run_all_sources(
            tickers=watchlist_tickers,
            force=True,
        )

        briefing = generate_briefing(
            instruments=instruments,
            signals=signals,
            surveillance_data=surveillance_data,
            watchlist=watchlist_tickers,
        )

        cleaned = _clean_record(briefing) if isinstance(briefing, dict) else briefing
        return {
            "ok":       True,
            "briefing": cleaned,
            "age_hours": 0,
            "stale":    False,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/briefing/news", summary="Watchlist-prioritised news feed")
def get_briefing_news(
    tickers: str = Query("", description="Comma-separated watchlist tickers for prioritised headlines"),
) -> dict:
    """
    Returns a news feed combining:
    1. Yahoo Finance per-ticker news for watchlist instruments (prioritised)
    2. General RSS headlines (Reuters, BBC, FT) as market context

    Watchlist news is cached per-ticker for 1 hour.
    General RSS news uses the existing surveillance cache (1 hour TTL).
    """
    try:
        try:
            import yfinance as yf
        except ImportError:
            yf = None

        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

        # ── 1. Yahoo Finance per-ticker news ─────────────────────────────────
        _NEWS_CACHE_DIR = _CACHE_DIR / "yf_news"
        _NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _NEWS_TTL_HOURS = 1

        watchlist_news: list[dict] = []

        if yf and ticker_list:
            for ticker in ticker_list:
                cache_file = _NEWS_CACHE_DIR / f"{ticker}.json"
                # Check cache freshness
                use_cache = False
                if cache_file.exists():
                    age_h = (
                        datetime.datetime.utcnow()
                        - datetime.datetime.utcfromtimestamp(cache_file.stat().st_mtime)
                    ).total_seconds() / 3600
                    use_cache = age_h < _NEWS_TTL_HOURS

                if use_cache:
                    try:
                        items = json.loads(cache_file.read_text(encoding="utf-8"))
                    except Exception:
                        items = []
                else:
                    items = []
                    try:
                        t_obj = yf.Ticker(ticker)
                        raw_news = t_obj.news or []
                        for article in raw_news[:8]:
                            content = article.get("content", {})
                            # yfinance >=0.2.x wraps articles in a 'content' dict
                            title = (
                                content.get("title")
                                or article.get("title", "")
                            )
                            link = (
                                content.get("canonicalUrl", {}).get("url")
                                or article.get("link", "")
                            )
                            publisher = (
                                content.get("provider", {}).get("displayName")
                                or article.get("publisher", "")
                            )
                            pub_time = (
                                content.get("pubDate")
                                or article.get("providerPublishTime")
                            )
                            if title:
                                items.append({
                                    "title":     title,
                                    "link":      link,
                                    "publisher": publisher,
                                    "pub_time":  str(pub_time) if pub_time else None,
                                    "ticker":    ticker,
                                })
                        cache_file.write_text(
                            json.dumps(items, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass

                for item in items:
                    item["source_type"] = "watchlist"
                    item.setdefault("ticker", ticker)
                    watchlist_news.append(item)

        # ── 2. General RSS headlines from existing surveillance cache ─────────
        rss_news: list[dict] = []
        try:
            rss_data = fetch_news(tickers=ticker_list or None, force=False)
            rss_items = rss_data.get("items", [])
            # Sort by absolute sentiment, cap at 20
            rss_items_sorted = sorted(
                rss_items,
                key=lambda x: abs(x.get("sentiment", 0)),
                reverse=True,
            )[:20]
            for item in rss_items_sorted:
                rss_news.append({
                    "title":      item.get("title", ""),
                    "link":       item.get("link", ""),
                    "publisher":  item.get("feed", ""),
                    "pub_time":   item.get("published", ""),
                    "sentiment":  item.get("sentiment", 0),
                    "source_type": "market",
                    "ticker":     None,
                })
        except Exception:
            pass

        return {
            "ok":             True,
            "watchlist_news": watchlist_news,
            "market_news":    rss_news,
            "tickers":        ticker_list,
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

        # Build a universe ticker→meta lookup from UNIVERSE (no fetching)
        universe_meta: dict[str, tuple[str, str, str]] = {}  # ticker → (name, asset_class, group)
        for group, meta in UNIVERSE.items():
            asset_class = meta.get("asset_class", "Stock")
            for ticker, name in meta["tickers"].items():
                universe_meta[ticker] = (name, asset_class, group)

        # Fetch only the watchlist tickers — from cache where possible
        raw: list[dict] = []
        for ticker in watchlist_tickers:
            if ticker in universe_meta:
                name, asset_class, group = universe_meta[ticker]
                inst = _load_cache(ticker)
                if inst:
                    inst.setdefault("name", name)
                    inst.setdefault("asset_class", asset_class)
                    inst.setdefault("group", group)
                    raw.append(inst)
                else:
                    # Cache miss — fetch live for this one ticker only
                    raw.append(fetch_one(ticker, name, asset_class, group))
            else:
                # Not in UNIVERSE — fetch live
                raw.append(fetch_one(ticker, ticker, "Stock", "Watchlist"))

        # Score only the watchlist instruments
        sector_medians = compute_sector_medians(raw)
        scored = score_all(raw, sector_medians)
        result_list = add_verdicts(scored, sector_medians)
        for inst in result_list:
            sc = inst.get("score")
            if sc is not None:
                inst["score_label"] = score_label(sc)
                inst["score_colour"] = score_colour(sc)
        result = result_list

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


@app.get("/api/price-history", summary="OHLCV price history for a ticker")
def get_price_history(
    ticker: str = Query(..., description="Yahoo Finance ticker, e.g. ABF.L"),
    period: str = Query("1y", description="One of: 1mo 3mo 6mo ytd 1y 5y"),
) -> dict:
    """
    Returns a time-series of daily closing prices for the requested period.
    Uses yfinance under the hood; results are NOT cached (called on demand).
    Response: { ok, ticker, period, data: [{date, price}, ...] }
    """
    # Validate ticker
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker parameter is required")
    ticker = ticker.strip().upper()
    if len(ticker) > 15 or not all(c.isalnum() or c in ".-" for c in ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {ticker}")

    try:
        try:
            import yfinance as yf
        except ImportError:
            raise HTTPException(status_code=500, detail="yfinance not installed")

        # Normalise period to a yfinance-accepted value
        period_map = {
            "1m": "1mo", "1mo": "1mo",
            "3m": "3mo", "3mo": "3mo",
            "6m": "6mo", "6mo": "6mo",
            "ytd": "ytd",
            "1y": "1y",
            "5y": "5y",
        }
        yf_period = period_map.get(period.lower(), "1y")

        hist = yf.Ticker(ticker.upper()).history(period=yf_period)
        if hist is None or hist.empty:
            return {"ok": False, "ticker": ticker, "period": period, "data": []}

        data = [
            {
                "date": str(idx.date()),
                "price": round(float(row["Close"]), 4),
            }
            for idx, row in hist.iterrows()
        ]
        return {"ok": True, "ticker": ticker.upper(), "period": yf_period, "data": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _generate_thesis(inst: dict, briefing: dict | None) -> str:
    """
    Generate an AI investment thesis for `inst` using Claude.
    Falls back to a data-driven template if the API key is absent or the
    call fails — so the endpoint always returns something useful.
    """
    try:
        import anthropic as _ant
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        client = _ant.Anthropic(api_key=api_key)

        name        = inst.get("name", inst.get("ticker", ""))
        ticker      = inst.get("ticker", "")
        sector      = inst.get("sector", "Unknown")
        score       = inst.get("score")
        score_lbl   = inst.get("score_label", "")
        price       = inst.get("price")
        currency    = inst.get("currency", "")
        pe          = inst.get("pe")
        pb          = inst.get("pb")
        ev_ebitda   = inst.get("ev_ebitda")
        div_yield   = inst.get("div_yield")
        yr1_pct     = inst.get("yr1_pct")
        roe         = inst.get("roe")
        revenue     = inst.get("revenue")
        rev_growth  = inst.get("revenue_growth")
        earn_growth = inst.get("earnings_growth")
        debt_eq     = inst.get("debt_equity")
        market_cap  = inst.get("market_cap")
        high_52w    = inst.get("high_52w")
        low_52w     = inst.get("low_52w")

        # Format helpers
        def _pct(v, decimals=1):
            if v is None: return "N/A"
            return f"{v:.{decimals}f}%"
        def _x(v, decimals=1):
            if v is None: return "N/A"
            return f"{v:.{decimals}f}x"
        def _fmt(v, decimals=2):
            if v is None: return "N/A"
            return f"{v:.{decimals}f}"

        # Briefing excerpt (if available and mentions this ticker)
        briefing_snippet = ""
        if briefing:
            full = briefing.get("briefing", "") or ""
            if isinstance(full, dict):
                full = full.get("text", "") or ""
            # Pull any sentence that mentions the ticker or company name
            import re
            sentences = re.split(r'(?<=[.!?])\s+', str(full))
            relevant = [s for s in sentences if ticker in s or name.split()[0] in s]
            if relevant:
                briefing_snippet = " ".join(relevant[:3])

        prompt = f"""You are a senior equity analyst writing a concise investment thesis for a professional investor.

Instrument: {name} ({ticker})
Sector: {sector}
Composite Score: {score}/100 — {score_lbl}

Key Metrics:
- Price: {currency} {_fmt(price)}
- Market Cap: {_fmt(market_cap, 0) if market_cap else 'N/A'}
- P/E: {_x(pe)}
- P/B: {_x(pb)}
- EV/EBITDA: {_x(ev_ebitda)}
- Dividend Yield: {_pct(div_yield)}
- 1Y Return: {_pct(yr1_pct)}
- ROE: {_pct(roe * 100 if roe else None)}
- Revenue Growth: {_pct(rev_growth * 100 if rev_growth else None)}
- Earnings Growth: {_pct(earn_growth * 100 if earn_growth else None)}
- Debt/Equity: {_fmt(debt_eq)}
- 52W High: {_fmt(high_52w)} / Low: {_fmt(low_52w)}
{f'Recent context from market briefing: {briefing_snippet}' if briefing_snippet else ''}

Write a 3–4 paragraph investment thesis in the tone of a highly skilled financial analyst. Structure it as:
1. Opening: What is the company and why it matters right now
2. Valuation & Quality case (reference the specific metrics above)
3. Key risks and considerations
4. Conclusion with a balanced view

Be specific, use the numbers provided, and cite your reasoning. Do not use bullet points — flowing prose only. Do not add headers. Attribute any market context to the briefing where relevant."""

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except Exception:
        # Graceful fallback — deterministic template from data
        name      = inst.get("name", inst.get("ticker", ""))
        score     = inst.get("score")
        score_lbl = inst.get("score_label", "")
        sector    = inst.get("sector", "")
        pe        = inst.get("pe")
        div_yield = inst.get("div_yield")
        yr1_pct   = inst.get("yr1_pct")

        valuation_note = f"trading on a P/E of {pe:.1f}x" if pe else "with valuation metrics under review"
        div_note       = f"a dividend yield of {div_yield:.1f}%" if div_yield else "a dividend policy currently under review"
        return_note    = (f"returning {yr1_pct:.1f}% over the past year" if yr1_pct else "with mixed recent price performance")

        return (
            f"{name} is a {sector} company currently rated {score_lbl} with a composite score of "
            f"{round(score) if score else 'N/A'}/100. "
            f"The company is {valuation_note}, offering {div_note}, and {return_note}. "
            f"A detailed AI-generated thesis is temporarily unavailable — check back shortly or ensure "
            f"ANTHROPIC_API_KEY is configured on the server."
        )


@app.get("/api/deepdive", summary="Full instrument record + AI investment thesis")
def get_deepdive(
    request: Request,
    ticker: str = Query(..., description="Yahoo Finance ticker, e.g. ABF.L"),
) -> dict:
    """
    Returns scored instrument data for a single ticker, plus an AI-generated
    investment thesis written in the style of a senior equity analyst.

    Thesis generation is rate-limited to 5 calls per IP per day (resets midnight UTC).
    Generated theses are cached server-side for 7 days — subsequent loads of the
    same ticker serve the cached version instantly at no API cost.
    Instrument data is served from SQLite cache where possible.
    """
    # Validate ticker
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker parameter is required")
    ticker = ticker.strip().upper()
    if len(ticker) > 15 or not all(c.isalnum() or c in ".-" for c in ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {ticker}")

    try:
        ticker = ticker.upper().strip()

        # ── 1. Resolve instrument data ──────────────────────────────────────
        universe_meta: dict[str, tuple[str, str, str]] = {}
        for group, meta in UNIVERSE.items():
            ac = meta.get("asset_class", "Stock")
            for t, n in meta["tickers"].items():
                universe_meta[t] = (n, ac, group)

        if ticker in universe_meta:
            name, asset_class, group = universe_meta[ticker]
            raw = _load_cache(ticker)
            if raw:
                raw.setdefault("name", name)
                raw.setdefault("asset_class", asset_class)
                raw.setdefault("group", group)
            else:
                raw = fetch_one(ticker, name, asset_class, group)
        else:
            raw = fetch_one(ticker, ticker, "Stock", "Deepdive")

        if not raw or not raw.get("ok"):
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

        # ── 2. Score and enrich ─────────────────────────────────────────────
        sector_medians = compute_sector_medians([raw])
        scored         = score_all([raw], sector_medians)
        enriched       = add_verdicts(scored, sector_medians)
        inst           = enriched[0] if enriched else raw

        sc = inst.get("score")
        if sc is not None:
            inst["score_label"]  = score_label(sc)
            inst["score_colour"] = score_colour(sc)

        # ── 3. Thesis — cache-first, rate-limit on generation ───────────────
        cached_thesis = _thesis_cache_get(ticker)
        thesis_from_cache = cached_thesis is not None
        thesis_cached_at  = None

        if cached_thesis:
            # Serve from cache — no API call, no rate-limit deduction
            thesis = cached_thesis
            with _json_lock:
                store = _read_json(_THESIS_CACHE)
            entry = store.get(ticker, {})
            thesis_cached_at = entry.get("generated_at")
        else:
            # Need to generate — check rate limit first
            # Respect X-Forwarded-For set by Render's proxy
            client_ip = (
                request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                or request.headers.get("x-real-ip", "")
                or (request.client.host if request.client else "unknown")
            )

            allowed, remaining = _rate_limit_check(client_ip)
            if not allowed:
                # Return instrument data but signal rate limit on thesis
                return {
                    "ok":               True,
                    "ticker":           ticker,
                    "instrument":       _clean_record(inst),
                    "thesis":           None,
                    "thesis_from_cache": False,
                    "rate_limited":     True,
                    "rate_limit_reset": "midnight UTC",
                    "calls_remaining":  0,
                }

            try:
                briefing = load_briefing()
            except Exception:
                briefing = None

            thesis = _generate_thesis(inst, briefing)
            _rate_limit_increment(client_ip)
            _thesis_cache_set(ticker, thesis)

            # Recompute remaining after increment
            _, remaining = _rate_limit_check(client_ip)

        return {
            "ok":               True,
            "ticker":           ticker,
            "instrument":       _clean_record(inst),
            "thesis":           thesis,
            "thesis_from_cache": thesis_from_cache,
            "thesis_cached_at":  thesis_cached_at,
            "rate_limited":     False,
            "calls_remaining":  _THESIS_DAILY_LIMIT if thesis_from_cache else (
                _rate_limit_check(
                    request.headers.get("x-forwarded-for", "").split(",")[0].strip()
                    or request.headers.get("x-real-ip", "")
                    or (request.client.host if request.client else "unknown")
                )[1]
            ),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _fetch_dividend_data(ticker: str, inst: dict) -> dict:
    """
    Fetch dividend data from yfinance (already in instrument cache) and
    enrich with publicly available data. Returns a structured dict.
    """
    try:
        import yfinance as yf
    except ImportError:
        yf = None

    currency = (inst.get("currency") or "").upper()
    sym = "£" if currency in ("GBP", "GBX") else "$" if currency == "USD" else "€" if currency == "EUR" else ""

    # ── Pull what we already have from the scored instrument ──────────────────
    div_yield   = inst.get("div_yield")        # already normalised to %
    payout_ratio = inst.get("payout_ratio")    # decimal (0–1) or None
    roe         = inst.get("roe")
    revenue     = inst.get("revenue")

    # ── Pull richer dividend data from yfinance ───────────────────────────────
    history_rows: list[dict] = []
    dividends_per_year = None
    last_dividend_value = None
    last_ex_date = None
    five_year_avg_yield = None
    dividend_growth_3y = None

    try:
        if yf:
            t = yf.Ticker(ticker)
            info = t.fast_info if hasattr(t, "fast_info") else {}

            # Dividend history
            divs = t.dividends
            if divs is not None and not divs.empty:
                # Last 5 years of quarterly/annual history
                recent = divs.tail(20)
                history_rows = [
                    {"date": str(idx.date()), "amount": round(float(v), 6)}
                    for idx, v in recent.items()
                ]
                last_dividend_value = round(float(divs.iloc[-1]), 6) if len(divs) > 0 else None
                last_ex_date = str(divs.index[-1].date()) if len(divs) > 0 else None

                # Payments per year (approximate from last 2 years)
                recent_2y = divs[divs.index >= (divs.index[-1] - datetime.timedelta(days=730))]
                dividends_per_year = round(len(recent_2y) / 2) if len(recent_2y) >= 2 else None

                # 3-year dividend growth (CAGR)
                if len(history_rows) >= 4:
                    try:
                        annual = {}
                        for row in history_rows:
                            yr = row["date"][:4]
                            annual[yr] = annual.get(yr, 0) + row["amount"]
                        years = sorted(annual.keys())
                        if len(years) >= 3:
                            start_val = annual[years[-3]]
                            end_val   = annual[years[-1]]
                            if start_val > 0 and end_val > 0:
                                dividend_growth_3y = round(((end_val / start_val) ** (1 / 2) - 1) * 100, 1)
                    except Exception:
                        pass

            # 5-year average yield from yfinance info
            try:
                raw_info = t.info
                five_year_avg_yield = raw_info.get("fiveYearAvgDividendYield")
                if five_year_avg_yield and five_year_avg_yield < 1.0:
                    five_year_avg_yield = round(five_year_avg_yield * 100, 2)
                elif five_year_avg_yield:
                    five_year_avg_yield = round(float(five_year_avg_yield), 2)
                payout_ratio = payout_ratio or raw_info.get("payoutRatio")
            except Exception:
                pass

    except Exception:
        pass

    freq_label = {1: "Annual", 2: "Semi-annual", 4: "Quarterly", 12: "Monthly"}.get(
        dividends_per_year, f"~{dividends_per_year}x/year" if dividends_per_year else "Unknown"
    )

    return {
        "ticker":               ticker,
        "currency":             currency,
        "symbol":               sym,
        "div_yield":            div_yield,
        "five_year_avg_yield":  five_year_avg_yield,
        "last_dividend":        last_dividend_value,
        "last_ex_date":         last_ex_date,
        "payment_frequency":    freq_label,
        "dividends_per_year":   dividends_per_year,
        "payout_ratio":         round(float(payout_ratio) * 100, 1) if payout_ratio else None,
        "dividend_growth_3y":   dividend_growth_3y,
        "history":              history_rows,
        "roe":                  round(float(roe) * 100, 1) if roe else None,
    }


def _generate_dividend_summary(ticker: str, div_data: dict, inst: dict) -> str:
    """
    Generate an AI dividend analysis using Claude.
    Falls back to a data-driven template if API key is absent or call fails.
    """
    try:
        import anthropic as _ant
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")

        client = _ant.Anthropic(api_key=api_key)
        name = inst.get("name", ticker)
        sector = inst.get("sector", "Unknown")

        def _fmt(v, suffix="", decimals=1):
            if v is None: return "N/A"
            return f"{v:.{decimals}f}{suffix}"

        prompt = f"""You are a senior equity income analyst. Write a concise dividend analysis for {name} ({ticker}).

Company: {name} | Sector: {sector}

Dividend Data:
- Current Yield: {_fmt(div_data.get('div_yield'), '%')}
- 5-Year Average Yield: {_fmt(div_data.get('five_year_avg_yield'), '%')}
- Payment Frequency: {div_data.get('payment_frequency', 'N/A')}
- Last Dividend Amount: {div_data.get('symbol', '')}{_fmt(div_data.get('last_dividend'), decimals=4)}
- Last Ex-Dividend Date: {div_data.get('last_ex_date', 'N/A')}
- Payout Ratio: {_fmt(div_data.get('payout_ratio'), '%')}
- 3-Year Dividend CAGR: {_fmt(div_data.get('dividend_growth_3y'), '%')}
- Return on Equity: {_fmt(div_data.get('roe'), '%')}

Write 2–3 paragraphs covering:
1. Income characteristics — is this a reliable income stock? How does the yield compare to sector norms?
2. Dividend sustainability — payout ratio, earnings cover, balance sheet capacity
3. Growth outlook — is the dividend likely to grow, hold, or be at risk?

Be specific, reference the numbers, write in flowing prose (no bullet points or headers).
Keep it under 250 words. Use the tone of a senior portfolio manager advising a client."""

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    except Exception:
        # Deterministic fallback
        name  = inst.get("name", ticker)
        dy    = div_data.get("div_yield")
        pr    = div_data.get("payout_ratio")
        g3y   = div_data.get("dividend_growth_3y")
        freq  = div_data.get("payment_frequency", "unknown frequency")
        parts = []
        if dy is not None:
            parts.append(f"{name} currently offers a dividend yield of {dy:.2f}%, paid at {freq}.")
        if pr is not None:
            sustainability = "comfortably covered" if pr < 60 else "relatively stretched" if pr > 85 else "broadly sustainable"
            parts.append(f"The payout ratio of {pr:.1f}% appears {sustainability}.")
        if g3y is not None:
            direction = "grown" if g3y > 0 else "declined"
            parts.append(f"The dividend has {direction} at a {abs(g3y):.1f}% CAGR over the past 3 years.")
        if not parts:
            parts.append(f"Dividend data for {name} is limited. Review the latest annual report for income details.")
        return " ".join(parts)


@app.get("/api/dividends", summary="Dividend data and AI income analysis")
def get_dividends(
    ticker: str = Query(..., description="Yahoo Finance ticker, e.g. ABF.L"),
) -> dict:
    """
    Returns structured dividend data plus an AI-generated income analysis.

    Data sourced from yfinance (dividend history, yield, payout ratio, frequency).
    Results are cached for 30 days — dividend policy rarely changes mid-year.
    AI analysis uses claude-opus-4-6; does NOT count against the thesis rate limit.
    """
    # Validate ticker
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker parameter is required")
    ticker = ticker.strip().upper()
    if len(ticker) > 15 or not all(c.isalnum() or c in ".-" for c in ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {ticker}")

    try:
        ticker = ticker.upper().strip()

        # ── 1. Check cache ──────────────────────────────────────────────────
        cached = _dividend_cache_get(ticker)
        if cached:
            return {"ok": True, "ticker": ticker, "from_cache": True, **cached}

        # ── 2. Load instrument data (for sector/currency context) ────────────
        universe_meta: dict[str, tuple[str, str, str]] = {}
        for group, meta in UNIVERSE.items():
            ac = meta.get("asset_class", "Stock")
            for t, n in meta["tickers"].items():
                universe_meta[t] = (n, ac, group)

        if ticker in universe_meta:
            name, asset_class, group = universe_meta[ticker]
            inst = _load_cache(ticker) or fetch_one(ticker, name, asset_class, group)
            if inst:
                inst.setdefault("name", name)
        else:
            inst = fetch_one(ticker, ticker, "Stock", "Dividends")

        if not inst or not inst.get("ok"):
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

        # ── 3. Fetch structured dividend data ────────────────────────────────
        div_data = _fetch_dividend_data(ticker, inst)

        # ── 4. Generate AI summary ───────────────────────────────────────────
        summary = _generate_dividend_summary(ticker, div_data, inst)
        div_data["summary"] = summary

        # ── 5. Cache and return ──────────────────────────────────────────────
        _dividend_cache_set(ticker, div_data)

        return {"ok": True, "ticker": ticker, "from_cache": False, **div_data}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/analyses", summary="List all cached investment theses")
def list_analyses() -> dict:
    """
    Returns all server-cached investment theses with metadata.
    Includes ticker, company name (resolved from UNIVERSE), generated_at,
    age in days, and a short excerpt of the thesis for display.
    """
    try:
        with _json_lock:
            store = _read_json(_THESIS_CACHE)

        # Build universe name lookup
        universe_meta: dict[str, tuple[str, str, str]] = {}
        for group, meta in UNIVERSE.items():
            ac = meta.get("asset_class", "Stock")
            for t, n in meta["tickers"].items():
                universe_meta[t] = (n, ac, group)

        now = datetime.datetime.utcnow()
        analyses = []
        for ticker, entry in store.items():
            generated_at = entry.get("generated_at")
            thesis       = entry.get("thesis", "")
            try:
                age_days = (now - datetime.datetime.fromisoformat(generated_at)).days
                expires_in = max(0, _THESIS_TTL_DAYS - age_days)
            except Exception:
                age_days   = None
                expires_in = None

            # Short excerpt — first sentence or first 200 chars
            excerpt = ""
            if thesis:
                first_sentence = thesis.split(".")[0]
                excerpt = (first_sentence[:200] + "…") if len(first_sentence) > 200 else first_sentence + "."

            name_meta = universe_meta.get(ticker)
            analyses.append({
                "ticker":       ticker,
                "name":         name_meta[0] if name_meta else ticker,
                "sector":       None,   # resolved from cache below if available
                "generated_at": generated_at,
                "age_days":     age_days,
                "expires_in":   expires_in,
                "excerpt":      excerpt,
            })

        # Sort newest first
        analyses.sort(key=lambda x: x.get("generated_at") or "", reverse=True)

        # Enrich with sector from SQLite cache (best-effort)
        for item in analyses:
            try:
                cached = _load_cache(item["ticker"])
                if cached:
                    item["sector"] = cached.get("sector")
                    if not item.get("name") or item["name"] == item["ticker"]:
                        item["name"] = cached.get("name", item["ticker"])
            except Exception:
                pass

        return {"ok": True, "count": len(analyses), "analyses": analyses}

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/api/analyses/{ticker}", summary="Delete a cached investment thesis")
def delete_analysis(ticker: str) -> dict:
    """
    Removes a ticker's cached thesis from the server cache.
    Next time /api/deepdive is called for this ticker, a fresh thesis will be
    generated (subject to the rate limit).
    """
    # Validate ticker
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker parameter is required")
    ticker = ticker.strip().upper()
    if len(ticker) > 15 or not all(c.isalnum() or c in ".-" for c in ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {ticker}")

    try:
        ticker = ticker.upper().strip()
        with _json_lock:
            store = _read_json(_THESIS_CACHE)
            if ticker not in store:
                raise HTTPException(status_code=404, detail=f"No cached thesis for {ticker}")
            del store[ticker]
            _write_json(_THESIS_CACHE, store)
        return {"ok": True, "ticker": ticker, "action": "deleted"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/analyses/{ticker}/refresh", summary="Force-refresh a cached investment thesis")
def refresh_analysis(request: Request, ticker: str) -> dict:
    """
    Deletes the existing cached thesis for `ticker` and regenerates it
    immediately using a fresh Claude call.

    This counts against the caller's daily rate limit (same as /api/deepdive).
    Returns the full new thesis plus updated metadata.
    """
    # Validate ticker
    if not ticker or not ticker.strip():
        raise HTTPException(status_code=400, detail="ticker parameter is required")
    ticker = ticker.strip().upper()
    if len(ticker) > 15 or not all(c.isalnum() or c in ".-" for c in ticker):
        raise HTTPException(status_code=400, detail=f"Invalid ticker symbol: {ticker}")

    try:
        ticker = ticker.upper().strip()

        # ── Rate limit check ──────────────────────────────────────────────────
        # Respect X-Forwarded-For set by Render's proxy
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip", "")
            or (request.client.host if request.client else "unknown")
        )
        allowed, remaining = _rate_limit_check(client_ip)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Daily thesis generation limit reached. Resets at midnight UTC."
            )

        # ── Resolve instrument ────────────────────────────────────────────────
        universe_meta: dict[str, tuple[str, str, str]] = {}
        for group, meta in UNIVERSE.items():
            ac = meta.get("asset_class", "Stock")
            for t, n in meta["tickers"].items():
                universe_meta[t] = (n, ac, group)

        if ticker in universe_meta:
            name, asset_class, group = universe_meta[ticker]
            raw = _load_cache(ticker)
            if raw:
                raw.setdefault("name", name)
                raw.setdefault("asset_class", asset_class)
                raw.setdefault("group", group)
            else:
                raw = fetch_one(ticker, name, asset_class, group)
        else:
            raw = fetch_one(ticker, ticker, "Stock", "Analyses")

        if not raw or not raw.get("ok"):
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

        sector_medians = compute_sector_medians([raw])
        scored         = score_all([raw], sector_medians)
        enriched       = add_verdicts(scored, sector_medians)
        inst           = enriched[0] if enriched else raw
        sc = inst.get("score")
        if sc is not None:
            inst["score_label"]  = score_label(sc)
            inst["score_colour"] = score_colour(sc)

        # ── Delete old cache entry ────────────────────────────────────────────
        with _json_lock:
            store = _read_json(_THESIS_CACHE)
            store.pop(ticker, None)
            _write_json(_THESIS_CACHE, store)

        # ── Generate fresh thesis ─────────────────────────────────────────────
        try:
            briefing = load_briefing()
        except Exception:
            briefing = None

        new_thesis = _generate_thesis(inst, briefing)
        _rate_limit_increment(client_ip)
        _thesis_cache_set(ticker, new_thesis)

        _, remaining_after = _rate_limit_check(client_ip)

        return {
            "ok":              True,
            "ticker":          ticker,
            "thesis":          new_thesis,
            "generated_at":    datetime.datetime.utcnow().isoformat(),
            "calls_remaining": remaining_after,
        }

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
