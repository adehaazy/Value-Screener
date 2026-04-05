"""
data/cache_db.py — SQLite-backed cache for instrument data.

Replaces hundreds of individual JSON files with a single database file
(cache/cache.db). Benefits:
  * Single file to back up / move / inspect
  * Much faster startup — one DB open vs. 655+ file-system reads
  * WAL mode allows concurrent readers while a writer is active
  * Indexed queries for instant lookups by ticker

Public API (used by fetcher.py):
  get_fundamentals(ticker)       -> dict | None
  set_fundamentals(ticker, data)
  get_prices(ticker)             -> dict | None
  set_prices(ticker, data)
  any_data_exists()              -> bool
  oldest_price_age_hours()       -> float | None
  oldest_fundamentals_age_days() -> float | None
  migrate_from_json(...)         -> int (files imported)
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

# -- Database location --------------------------------------------------------
_DB_PATH = Path(__file__).parent.parent / "cache" / "cache.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# -- Thread safety ------------------------------------------------------------
_lock = threading.Lock()
_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA cache_size=-8000")
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                ticker    TEXT PRIMARY KEY,
                data      TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS prices (
                ticker    TEXT PRIMARY KEY,
                data      TEXT NOT NULL,
                cached_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fund_ts  ON fundamentals(cached_at);
            CREATE INDEX IF NOT EXISTS idx_price_ts ON prices(cached_at);
        """)
        _conn.commit()
    return _conn


def _ts(data):
    return (data.get("cached_at")
            or data.get("fetched_at")
            or datetime.now(timezone.utc).isoformat())


# -- Fundamentals (7-day TTL) -------------------------------------------------

def get_fundamentals(ticker):
    with _lock:
        row = _get_conn().execute(
            "SELECT data FROM fundamentals WHERE ticker = ?", (ticker,)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def set_fundamentals(ticker, data):
    payload = json.dumps(data, default=str)
    with _lock:
        c = _get_conn()
        c.execute(
            "INSERT OR REPLACE INTO fundamentals (ticker, data, cached_at) VALUES (?, ?, ?)",
            (ticker, payload, _ts(data)),
        )
        c.commit()


# -- Prices (15-min TTL during market hours) ----------------------------------

def get_prices(ticker):
    with _lock:
        row = _get_conn().execute(
            "SELECT data FROM prices WHERE ticker = ?", (ticker,)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def set_prices(ticker, data):
    payload = json.dumps(data, default=str)
    with _lock:
        c = _get_conn()
        c.execute(
            "INSERT OR REPLACE INTO prices (ticker, data, cached_at) VALUES (?, ?, ?)",
            (ticker, payload, _ts(data)),
        )
        c.commit()


# -- Introspection ------------------------------------------------------------

def any_data_exists():
    with _lock:
        n = _get_conn().execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    return n > 0


def all_tickers():
    with _lock:
        rows = _get_conn().execute("SELECT ticker FROM prices").fetchall()
    return [r["ticker"] for r in rows]


def oldest_price_age_hours():
    """Hours since the most recently updated price entry was cached."""
    with _lock:
        row = _get_conn().execute(
            "SELECT MAX(cached_at) AS newest FROM prices"
        ).fetchone()
    if not row or not row["newest"]:
        return None
    try:
        dt = datetime.fromisoformat(str(row["newest"]))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


def oldest_fundamentals_age_days():
    """Days since the oldest fundamentals entry was cached."""
    with _lock:
        row = _get_conn().execute(
            "SELECT MIN(cached_at) AS oldest FROM fundamentals"
        ).fetchone()
    if not row or not row["oldest"]:
        return None
    try:
        dt = datetime.fromisoformat(str(row["oldest"]))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - dt).total_seconds() / 86400, 1)
    except Exception:
        return None


# -- One-time D/E normalisation (patch for old 150-style cached values) --------

def normalise_cached_de():
    """
    One-time migration: existing fundamentals rows may have debtToEquity stored
    as a percentage-integer (e.g. 150 for 1.5x) because fetcher.py used to store
    the raw yfinance value.  This patches every row where the stored value looks
    like the old format (> 10) and converts it to ratio form (/ 100).

    Safe to run repeatedly — values already in ratio form (≤ 10) are left alone.
    Returns the number of rows updated.
    """
    updated = 0
    with _lock:
        c = _get_conn()
        rows = c.execute("SELECT ticker, data FROM fundamentals").fetchall()
        for row in rows:
            try:
                data = json.loads(row["data"])
                changed = False
                for key in ("debt_to_equity", "debt_equity"):
                    v = data.get(key)
                    if v is not None:
                        try:
                            fv = float(v)
                            # Only patch values that look like the old % form.
                            # Real-world D/E ratio almost never exceeds 10x;
                            # anything above that is assumed to be the old ×100 form.
                            if fv > 10:
                                data[key] = round(fv / 100, 4)
                                changed = True
                        except (TypeError, ValueError):
                            pass
                if changed:
                    c.execute(
                        "UPDATE fundamentals SET data = ? WHERE ticker = ?",
                        (json.dumps(data, default=str), row["ticker"]),
                    )
                    updated += 1
        if updated:
            c.commit()
    return updated


# -- Migration from legacy JSON files -----------------------------------------

def migrate_from_json(instruments_dir=None, fundamentals_dir=None, prices_dir=None):
    """
    Import existing JSON cache files into SQLite.
    Safe to call multiple times. Returns count of records written.
    """
    count = 0

    # Old-style: cache/instruments/*.json  (single-layer, 6h TTL)
    if instruments_dir and Path(instruments_dir).exists():
        for path in sorted(Path(instruments_dir).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ticker = data.get("ticker") or path.stem.replace("_", ".")
                if not data.get("cached_at") and data.get("fetched_at"):
                    data["cached_at"] = data["fetched_at"]
                set_fundamentals(ticker, data)
                set_prices(ticker, data)
                count += 1
            except Exception:
                pass

    # New-style: separate fundamentals/ and prices/ directories
    if fundamentals_dir and Path(fundamentals_dir).exists():
        for path in sorted(Path(fundamentals_dir).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ticker = data.get("ticker") or path.stem.replace("_", ".")
                set_fundamentals(ticker, data)
                count += 1
            except Exception:
                pass

    if prices_dir and Path(prices_dir).exists():
        for path in sorted(Path(prices_dir).glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                ticker = data.get("ticker") or path.stem.replace("_", ".")
                set_prices(ticker, data)
                count += 1
            except Exception:
                pass

    return count
