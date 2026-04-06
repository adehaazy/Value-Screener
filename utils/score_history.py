"""
utils/score_history.py — 5-year score history via yfinance.

Architecture
------------
SQLite table `score_history` in cache/cache.db:

  ticker   TEXT  — instrument ticker
  date     TEXT  — ISO date (YYYY-MM-DD)
  score    REAL  — screener score 0–100
  price    REAL  — closing price on that date
  source   TEXT  — "live" (daily snapshot) | "backfill" (historical)

Backfill strategy (FREE, no API key):
  - yfinance downloads up to 5 years of daily OHLCV for each ticker
  - We can't re-run the full scoring model against historical fundamentals
    (those aren't freely available at daily granularity)
  - So the backfill computes a *price-momentum proxy score*:
      50 pts base + momentum vs 52w range (0–30 pts) + ytd drift (0–20 pts)
  - This is clearly labelled "price-based proxy" in the UI — it shows
    trajectory and mean-reversion signals, not the full quality-weighted score
  - Live daily snapshots use the REAL score from the screener

Live snapshots:
  - Called from app.py after each successful data fetch
  - Stores the real scored value alongside today's price
  - Deduplicates by (ticker, date) — safe to call repeatedly

Public API
----------
  init_history_db()
  snapshot_scores(instruments)           — call after every fetch
  get_score_history(ticker, days=365)    -> pd.DataFrame [date, score, price, source]
  backfill_ticker(ticker, years=5)       -> int rows written
  backfill_all(tickers, years=5, ...)    — batch backfill with rate-limit
  has_history(ticker)                    -> bool
  history_date_range(ticker)             -> (earliest_date, latest_date) | (None, None)
"""

from __future__ import annotations

import sqlite3
import threading
import time
import logging
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Sequence

import pandas as pd

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "cache" / "cache.db"
_lock    = threading.Lock()
_conn: sqlite3.Connection | None = None


# ── DB connection & init ──────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def init_history_db():
    """Create the score_history table if it doesn't exist."""
    with _lock:
        c = _get_conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS score_history (
                ticker  TEXT NOT NULL,
                date    TEXT NOT NULL,
                score   REAL,
                price   REAL,
                source  TEXT DEFAULT 'live',
                PRIMARY KEY (ticker, date)
            );
            CREATE INDEX IF NOT EXISTS idx_sh_ticker ON score_history(ticker);
            CREATE INDEX IF NOT EXISTS idx_sh_date   ON score_history(date);
        """)
        c.commit()


# ── Live snapshots ─────────────────────────────────────────────────────────────

def snapshot_scores(instruments: list[dict]):
    """
    Called after every successful screener fetch.  Stores today's real score
    and price for each scored instrument.  Safe to call multiple times per day
    (deduplicates by PRIMARY KEY).
    """
    init_history_db()
    today = date.today().isoformat()
    rows = []
    for inst in instruments:
        ticker = inst.get("ticker")
        score  = inst.get("score")
        price  = inst.get("price")
        if ticker and score is not None:
            rows.append((ticker, today, float(score),
                         float(price) if price else None, "live"))
    if not rows:
        return
    with _lock:
        c = _get_conn()
        c.executemany(
            """INSERT OR REPLACE INTO score_history (ticker, date, score, price, source)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        c.commit()
    logger.info(f"Snapshotted {len(rows)} scores for {today}")


# ── Historical retrieval ──────────────────────────────────────────────────────

def get_score_history(ticker: str, days: int = 365) -> pd.DataFrame:
    """
    Return a DataFrame with columns [date, score, price, source] for `ticker`,
    covering the last `days` calendar days.  Returns empty DataFrame if no data.
    """
    init_history_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    with _lock:
        rows = _get_conn().execute(
            """SELECT date, score, price, source FROM score_history
               WHERE ticker = ? AND date >= ?
               ORDER BY date""",
            (ticker, cutoff),
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["date", "score", "price", "source"])
    df = pd.DataFrame([dict(r) for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    return df


def has_history(ticker: str) -> bool:
    init_history_db()
    with _lock:
        n = _get_conn().execute(
            "SELECT COUNT(*) FROM score_history WHERE ticker = ?", (ticker,)
        ).fetchone()[0]
    return n > 0


def history_date_range(ticker: str) -> tuple[str | None, str | None]:
    init_history_db()
    with _lock:
        row = _get_conn().execute(
            "SELECT MIN(date), MAX(date) FROM score_history WHERE ticker = ?", (ticker,)
        ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


# ── Price-momentum proxy score ────────────────────────────────────────────────

def _proxy_score(close: float, high_52w: float, low_52w: float,
                 open_price: float) -> float:
    """
    Compute a price-based proxy score (0–100) for historical backfill rows.
    This is NOT the real quality-weighted score — it's a mean-reversion proxy
    showing where the stock sat in its 52-week range on each historical date.

    Components:
      Base:             50 pts
      52w range pos:    0–30 pts (low end of range = more pts, contrarian)
      YTD drift:        0–20 pts (based on momentum sign)
    """
    score = 50.0

    # 52-week range position (contrarian: cheaper = higher score)
    if high_52w > low_52w:
        range_pos = (close - low_52w) / (high_52w - low_52w)  # 0 = at low, 1 = at high
        # Contrarian: at 52w low → 30 pts, at 52w high → 0 pts
        score += 30.0 * (1 - range_pos)

    # Momentum component (YTD return vs open of year)
    if open_price and open_price > 0:
        ytd = (close / open_price - 1) * 100
        # Slight upward drift adds pts, large drawdown reduces
        mom = max(-20.0, min(20.0, ytd))
        score += 10.0 + (mom * 0.5)  # centre at 10, range 0–20

    return round(max(0.0, min(100.0, score)), 1)


# ── yfinance backfill ─────────────────────────────────────────────────────────

def backfill_ticker(ticker: str, years: int = 5) -> int:
    """
    Download up to `years` of daily OHLCV from yfinance and write proxy scores
    to score_history.  Skips dates already present.  Returns rows written.

    Uses the free yfinance library — no API key required.
    Rate: ~1 request per ticker, usually completes in <2s.
    """
    init_history_db()
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError("yfinance not installed. Run: pip install yfinance")

    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=years * 365)

    try:
        data = yf.download(
            ticker,
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.warning(f"yfinance download failed for {ticker}: {e}")
        return 0

    if data is None or data.empty:
        logger.warning(f"No yfinance data for {ticker}")
        return 0

    # Get existing dates to skip
    with _lock:
        existing = {
            r[0] for r in _get_conn().execute(
                "SELECT date FROM score_history WHERE ticker = ?", (ticker,)
            ).fetchall()
        }

    # Compute rolling 52-week window for each row
    data = data.copy()
    close_col = "Close"
    if close_col not in data.columns:
        close_col = data.columns[3] if len(data.columns) > 3 else data.columns[0]

    closes = data[close_col].dropna()
    if closes.empty:
        return 0

    # Rolling 252-day window for 52w high/low
    roll_high = closes.rolling(252, min_periods=20).max()
    roll_low  = closes.rolling(252, min_periods=20).min()
    # Year-start open: approximate with rolling 365-day first value
    year_open = closes.expanding().apply(
        lambda x: x.iloc[max(0, len(x) - 252)], raw=True
    )

    rows = []
    for idx in closes.index:
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
        if date_str in existing:
            continue
        close = float(closes.loc[idx])
        hi    = float(roll_high.loc[idx]) if not pd.isna(roll_high.loc[idx]) else close
        lo    = float(roll_low.loc[idx])  if not pd.isna(roll_low.loc[idx])  else close
        op    = float(year_open.loc[idx]) if not pd.isna(year_open.loc[idx]) else close
        score = _proxy_score(close, hi, lo, op)
        rows.append((ticker, date_str, score, close, "backfill"))

    if not rows:
        return 0

    with _lock:
        c = _get_conn()
        c.executemany(
            """INSERT OR IGNORE INTO score_history (ticker, date, score, price, source)
               VALUES (?, ?, ?, ?, ?)""",
            rows,
        )
        c.commit()

    logger.info(f"Backfilled {len(rows)} rows for {ticker}")
    return len(rows)


def backfill_all(
    tickers: Sequence[str],
    years: int = 5,
    delay_secs: float = 0.3,
    on_progress=None,
) -> dict[str, int]:
    """
    Batch-backfill all tickers.  Skips tickers that already have backfill data.

    Parameters
    ----------
    tickers      : list of ticker strings
    years        : how many years of history to download (default 5)
    delay_secs   : sleep between requests to avoid rate-limiting (default 0.3s)
    on_progress  : optional callback(ticker, done, total) for progress reporting

    Returns dict {ticker: rows_written}
    """
    init_history_db()
    results = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        # Skip if already has backfill data
        with _lock:
            has_backfill = _get_conn().execute(
                "SELECT 1 FROM score_history WHERE ticker = ? AND source = 'backfill' LIMIT 1",
                (ticker,),
            ).fetchone()
        if has_backfill:
            results[ticker] = 0
            if on_progress:
                on_progress(ticker, i + 1, total)
            continue

        try:
            n = backfill_ticker(ticker, years=years)
            results[ticker] = n
        except Exception as e:
            logger.warning(f"backfill_all: {ticker} failed — {e}")
            results[ticker] = -1

        if on_progress:
            on_progress(ticker, i + 1, total)

        if delay_secs > 0:
            time.sleep(delay_secs)

    return results
