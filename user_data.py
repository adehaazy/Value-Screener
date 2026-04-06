"""
user_data.py — Per-user data persistence layer.

Replaces flat JSON files (watchlist.json, holdings.json, prefs.json) with
per-user rows in auth.db.  Falls back gracefully to the legacy JSON files
for the single-user case (user_id=None), ensuring backwards compatibility
during rollout.

Public API
----------
  load_watchlist(user_id)           -> list[dict]
  save_watchlist(user_id, items)
  load_holdings(user_id)            -> list[dict]
  save_holdings(user_id, items)
  load_prefs(user_id)               -> dict
  save_prefs(user_id, prefs)
  load_custom_tickers(user_id)      -> list[dict]
  add_custom_ticker(user_id, ...)
  remove_custom_ticker(user_id, ticker)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from database import get_db, DB_PATH

logger = logging.getLogger(__name__)

# Legacy fallback paths (single-user era)
_CACHE_DIR = Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

_DEFAULT_PREFS: dict = {
    # Display filters
    "groups":            ["UK Stocks", "ETFs & Index Funds"],
    "min_score":         0,
    "min_yield":         0.0,
    "max_pe":            100,
    "max_ter":           1.5,
    # Quality gate (stocks)
    "min_roe":           10,
    "max_de":            2,
    "min_profit_margin": 2,
    "require_pos_fcf":   True,
    # Stock valuation weights
    "wt_pe":             30,
    "wt_pb":             20,
    "wt_evebitda":       20,
    "wt_divyield":       15,
    "wt_52w":            15,
    "wt_pfcf":           20,
    "wt_roic":           20,
    # ETF weights
    "wt_etf_aum":        35,
    "wt_etf_ter":        35,
    "wt_etf_ret":        20,
    "wt_etf_mom":        10,
    # Money market weights
    "wt_mm_yield":       60,
    "wt_mm_aum":         25,
    "wt_mm_ter":         15,
}


# ── Legacy JSON helpers (fallback) ────────────────────────────────────────────

def _legacy_load(filename: str, default: Any) -> Any:
    p = _CACHE_DIR / filename
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return default


def _legacy_save(filename: str, data: Any):
    (_CACHE_DIR / filename).write_text(json.dumps(data, default=str, indent=2))


# ── Watchlist ─────────────────────────────────────────────────────────────────

def load_watchlist(user_id: str | None) -> list[dict]:
    """Return watchlist items for this user."""
    if not user_id:
        return _legacy_load("watchlist.json", [])
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT data FROM user_watchlist WHERE user_id = ? ORDER BY added_at",
                (user_id,),
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]
    except Exception as e:
        logger.warning(f"load_watchlist DB error: {e}, falling back to legacy")
        return _legacy_load("watchlist.json", [])


def save_watchlist(user_id: str | None, items: list[dict]):
    """Overwrite the watchlist for this user."""
    if not user_id:
        _legacy_save("watchlist.json", items)
        return
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM user_watchlist WHERE user_id = ?", (user_id,))
            for item in items:
                ticker = item.get("ticker", "")
                name = item.get("name", ticker)
                conn.execute(
                    """INSERT OR REPLACE INTO user_watchlist (user_id, ticker, name, data)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, ticker, name, json.dumps(item, default=str)),
                )
    except Exception as e:
        logger.warning(f"save_watchlist DB error: {e}, falling back to legacy")
        _legacy_save("watchlist.json", items)


def add_to_watchlist(user_id: str | None, item: dict):
    """Add a single item; no-op if ticker already present."""
    items = load_watchlist(user_id)
    ticker = item.get("ticker", "")
    if any(i.get("ticker") == ticker for i in items):
        return
    items.append(item)
    save_watchlist(user_id, items)


def remove_from_watchlist(user_id: str | None, ticker: str):
    """Remove by ticker."""
    items = [i for i in load_watchlist(user_id) if i.get("ticker") != ticker]
    save_watchlist(user_id, items)


# ── Holdings ──────────────────────────────────────────────────────────────────

def load_holdings(user_id: str | None) -> list[dict]:
    if not user_id:
        return _legacy_load("holdings.json", [])
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT data FROM user_holdings WHERE user_id = ? ORDER BY added_at",
                (user_id,),
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]
    except Exception as e:
        logger.warning(f"load_holdings DB error: {e}, falling back to legacy")
        return _legacy_load("holdings.json", [])


def save_holdings(user_id: str | None, items: list[dict]):
    if not user_id:
        _legacy_save("holdings.json", items)
        return
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM user_holdings WHERE user_id = ?", (user_id,))
            for item in items:
                ticker = item.get("ticker", "")
                name = item.get("name", ticker)
                conn.execute(
                    """INSERT OR REPLACE INTO user_holdings (user_id, ticker, name, data)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, ticker, name, json.dumps(item, default=str)),
                )
    except Exception as e:
        logger.warning(f"save_holdings DB error: {e}, falling back to legacy")
        _legacy_save("holdings.json", items)


def add_to_holdings(user_id: str | None, item: dict):
    items = load_holdings(user_id)
    ticker = item.get("ticker", "")
    if any(i.get("ticker") == ticker for i in items):
        return
    items.append(item)
    save_holdings(user_id, items)


def remove_from_holdings(user_id: str | None, ticker: str):
    items = [i for i in load_holdings(user_id) if i.get("ticker") != ticker]
    save_holdings(user_id, items)


# ── Preferences ───────────────────────────────────────────────────────────────

def load_prefs(user_id: str | None) -> dict:
    """Return user prefs, falling back to defaults for missing keys."""
    if not user_id:
        stored = _legacy_load("prefs.json", {})
    else:
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)
                ).fetchone()
            stored = json.loads(row["data"]) if row else {}
        except Exception as e:
            logger.warning(f"load_prefs DB error: {e}, falling back to legacy")
            stored = _legacy_load("prefs.json", {})

    # Merge with defaults so new keys are always present
    merged = dict(_DEFAULT_PREFS)
    merged.update(stored)
    return merged


def save_prefs(user_id: str | None, prefs: dict):
    if not user_id:
        _legacy_save("prefs.json", prefs)
        return
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO user_prefs (user_id, data, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                       data = excluded.data,
                       updated_at = CURRENT_TIMESTAMP""",
                (user_id, json.dumps(prefs, default=str)),
            )
    except Exception as e:
        logger.warning(f"save_prefs DB error: {e}, falling back to legacy")
        _legacy_save("prefs.json", prefs)


# ── Custom tickers ────────────────────────────────────────────────────────────

def load_custom_tickers(user_id: str | None) -> list[dict]:
    """Return tickers the user has manually added beyond the built-in universe."""
    if not user_id:
        return _legacy_load("custom_tickers.json", [])
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT ticker, name, group_name, asset_class, added_at
                   FROM user_custom_tickers WHERE user_id = ?
                   ORDER BY added_at""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"load_custom_tickers DB error: {e}")
        return _legacy_load("custom_tickers.json", [])


def add_custom_ticker(
    user_id: str | None,
    ticker: str,
    name: str = "",
    group_name: str = "Custom",
    asset_class: str = "Stock",
) -> bool:
    """Add a custom ticker. Returns True on success, False if already exists."""
    ticker = ticker.upper().strip()
    if not user_id:
        items = _legacy_load("custom_tickers.json", [])
        if any(i["ticker"] == ticker for i in items):
            return False
        items.append({"ticker": ticker, "name": name or ticker,
                      "group_name": group_name, "asset_class": asset_class})
        _legacy_save("custom_tickers.json", items)
        return True
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO user_custom_tickers
                   (user_id, ticker, name, group_name, asset_class)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, ticker, name or ticker, group_name, asset_class),
            )
        return True
    except Exception as e:
        logger.warning(f"add_custom_ticker DB error: {e}")
        return False


def remove_custom_ticker(user_id: str | None, ticker: str):
    ticker = ticker.upper().strip()
    if not user_id:
        items = [i for i in _legacy_load("custom_tickers.json", [])
                 if i["ticker"] != ticker]
        _legacy_save("custom_tickers.json", items)
        return
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM user_custom_tickers WHERE user_id = ? AND ticker = ?",
                (user_id, ticker),
            )
    except Exception as e:
        logger.warning(f"remove_custom_ticker DB error: {e}")


# ── Migration: import existing JSON files into DB for a user ──────────────────

def migrate_legacy_data_for_user(user_id: str):
    """
    One-time migration: copy existing flat JSON cache files into the DB
    for a given user.  Safe to call multiple times — skips already-present items.
    """
    wl = _legacy_load("watchlist.json", None)
    if wl is not None:
        for item in wl:
            ticker = item.get("ticker", "")
            if ticker:
                try:
                    with get_db() as conn:
                        conn.execute(
                            """INSERT OR IGNORE INTO user_watchlist
                               (user_id, ticker, name, data) VALUES (?, ?, ?, ?)""",
                            (user_id, ticker, item.get("name", ticker),
                             json.dumps(item, default=str)),
                        )
                except Exception:
                    pass

    hl = _legacy_load("holdings.json", None)
    if hl is not None:
        for item in hl:
            ticker = item.get("ticker", "")
            if ticker:
                try:
                    with get_db() as conn:
                        conn.execute(
                            """INSERT OR IGNORE INTO user_holdings
                               (user_id, ticker, name, data) VALUES (?, ?, ?, ?)""",
                            (user_id, ticker, item.get("name", ticker),
                             json.dumps(item, default=str)),
                        )
                except Exception:
                    pass

    pr = _legacy_load("prefs.json", None)
    if pr is not None:
        save_prefs(user_id, pr)

    logger.info(f"Legacy data migrated for user {user_id}")
