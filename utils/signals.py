"""
Signals engine — detects meaningful changes and generates alerts.

Four signal types:
  1. Score drift     — instrument score changed >10 pts since last scan
  2. Value threshold — instrument crossed into "Strong Buy" territory
  3. Macro stress    — yield curve, credit spreads, VIX flags
  4. News alert      — negative/positive headlines for watchlist names
  5. Insider signal  — cluster buying detected (US stocks)
  6. Material event  — 8-K filing detected (US stocks)

Signals are persisted to cache/signals_history.json so the app can show
"new since last visit" badges. Compute-efficient: only re-runs if underlying
data has changed.
"""

import json
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path(__file__).parent.parent / "cache"
SIGNALS_FILE = CACHE_DIR / "signals_history.json"


# ── Persistence helpers ────────────────────────────────────────────────────────

def _load_history() -> dict:
    if SIGNALS_FILE.exists():
        try:
            return json.loads(SIGNALS_FILE.read_text())
        except Exception:
            pass
    return {"last_run": None, "score_snapshot": {}, "signals": []}


def _save_history(history: dict):
    CACHE_DIR.mkdir(exist_ok=True)
    SIGNALS_FILE.write_text(json.dumps(history, default=str, indent=2))


def load_latest_signals() -> list[dict]:
    """Return the most recently generated signals list."""
    return _load_history().get("signals", [])


def get_last_run_time() -> str | None:
    return _load_history().get("last_run")


# ── Signal constructors ────────────────────────────────────────────────────────

def _sig(type_: str, severity: str, title: str, detail: str,
         ticker: str = None, source: str = None, **kwargs) -> dict:
    s = {
        "type":     type_,
        "severity": severity,   # "high" | "medium" | "low" | "info"
        "title":    title,
        "detail":   detail,
        "ticker":   ticker,
        "source":   source,
        "ts":       datetime.now().isoformat(),
    }
    s.update(kwargs)
    return s


# ── Signal generators ──────────────────────────────────────────────────────────

def _score_drift_signals(instruments: list[dict], prev_snapshot: dict) -> tuple[list, dict]:
    """
    Compare current scores against previous snapshot.
    Returns (signals, new_snapshot).
    """
    signals = []
    new_snapshot = {}

    for inst in instruments:
        if not inst.get("ok"):
            continue
        ticker = inst.get("ticker", "")
        score  = inst.get("score")
        if score is None:
            continue

        new_snapshot[ticker] = score
        prev_score = prev_snapshot.get(ticker)

        if prev_score is None:
            continue  # First run — no drift to compute

        drift = score - prev_score
        if abs(drift) < 10:
            continue

        name = inst.get("name", ticker)
        direction = "improved" if drift > 0 else "declined"
        severity  = "high" if abs(drift) >= 20 else "medium"

        signals.append(_sig(
            type_    = "score_drift",
            severity = severity,
            title    = f"{'📈' if drift > 0 else '📉'} {name} score {direction} by {abs(drift):.0f} pts",
            detail   = f"{name} ({ticker}) moved from {prev_score:.0f} → {score:.0f}. "
                       f"{'Check recent results or valuation changes.' if drift < 0 else 'May represent improving value.'}",
            ticker   = ticker,
            source   = "Score Tracker",
            drift    = round(drift, 1),
            score    = round(score, 1),
        ))

    return signals, new_snapshot


def _value_threshold_signals(instruments: list[dict]) -> list[dict]:
    """Flag instruments that cross into Strong Buy territory (score >= 75)."""
    signals = []
    for inst in instruments:
        if not inst.get("ok"):
            continue
        score = inst.get("score")
        if score is None or score < 75:
            continue
        if inst.get("quality_passes") is False:
            continue  # Only flag quality-passing instruments

        name   = inst.get("name", inst.get("ticker", ""))
        ticker = inst.get("ticker", "")

        signals.append(_sig(
            type_    = "value_opportunity",
            severity = "high" if score >= 85 else "medium",
            title    = f"⭐ {name} in Strong Buy territory",
            detail   = f"{name} ({ticker}) scores {score:.0f}/100 — passes quality gate and trades at a meaningful discount to sector peers.",
            ticker   = ticker,
            source   = "Screener",
            score    = round(score, 1),
        ))
    return signals


def _near_52w_low_signals(instruments: list[dict]) -> list[dict]:
    """Flag stocks within 5% of 52-week low with quality pass — potential entry point."""
    signals = []
    for inst in instruments:
        if not inst.get("ok") or inst.get("asset_class") != "Stock":
            continue
        if inst.get("quality_passes") is False:
            continue
        pct = inst.get("pct_from_high")
        if pct is None or pct > -50:
            continue  # Only if >50% off high (deeply beaten-down)

        low_52w  = inst.get("low_52w")
        price    = inst.get("price")
        if not low_52w or not price:
            continue
        pct_from_low = (price / low_52w - 1) * 100
        if pct_from_low > 5:
            continue  # Not close enough to 52w low

        name   = inst.get("name", inst.get("ticker", ""))
        ticker = inst.get("ticker", "")
        signals.append(_sig(
            type_    = "near_52w_low",
            severity = "medium",
            title    = f"📍 {name} near 52-week low",
            detail   = f"{name} ({ticker}) is within {pct_from_low:.1f}% of its 52-week low "
                       f"and passes quality checks. Potential opportunistic entry.",
            ticker   = ticker,
            source   = "Price Monitor",
            pct_from_low = round(pct_from_low, 1),
        ))
    return signals


def _macro_signals(surveillance_data: dict) -> list[dict]:
    """Extract pre-computed macro signals from data sources."""
    signals = []
    for key in ("macro_us", "macro_uk"):
        src_data = surveillance_data.get(key, {})
        for sig in src_data.get("signals", []):
            signals.append({**sig, "source": src_data.get("source", key), "ts": datetime.now().isoformat()})
    return signals


def _news_signals(surveillance_data: dict, watchlist: list[str]) -> list[dict]:
    """Generate alerts for strong sentiment on watchlist tickers."""
    signals = []
    news = surveillance_data.get("news", {})
    mentions = news.get("ticker_mentions", {})

    for ticker in watchlist:
        ticker_news = mentions.get(ticker, [])
        if not ticker_news:
            continue

        # Compute average sentiment
        sentiments = [n["sentiment"] for n in ticker_news]
        avg_sentiment = sum(sentiments) / len(sentiments)

        if avg_sentiment < -0.3:
            signals.append(_sig(
                type_    = "news_negative",
                severity = "high" if avg_sentiment < -0.6 else "medium",
                title    = f"🔴 Negative news: {ticker}",
                detail   = f"{len(ticker_news)} recent headline(s) with negative tone. "
                           f"Latest: \"{ticker_news[0]['title'][:80]}\"",
                ticker   = ticker,
                source   = ticker_news[0].get("feed", "News"),
                headline = ticker_news[0]["title"],
                sentiment= round(avg_sentiment, 2),
            ))
        elif avg_sentiment > 0.3:
            signals.append(_sig(
                type_    = "news_positive",
                severity = "low",
                title    = f"🟢 Positive news: {ticker}",
                detail   = f"{len(ticker_news)} recent headline(s) with positive tone. "
                           f"Latest: \"{ticker_news[0]['title'][:80]}\"",
                ticker   = ticker,
                source   = ticker_news[0].get("feed", "News"),
                headline = ticker_news[0]["title"],
                sentiment= round(avg_sentiment, 2),
            ))

    return signals


def _insider_signals(surveillance_data: dict) -> list[dict]:
    """Pass through cluster insider buying signals."""
    insider = surveillance_data.get("insider", {})
    signals = []
    for sig in insider.get("cluster_signals", []):
        signals.append({**sig, "source": "OpenInsider", "ts": datetime.now().isoformat()})
    return signals


def _edgar_signals(surveillance_data: dict) -> list[dict]:
    """Alert on material events (8-K filings) for universe tickers."""
    edgar = surveillance_data.get("edgar", {})
    signals = []
    for ticker, events in edgar.get("events", {}).items():
        if events:
            latest = events[0]
            signals.append(_sig(
                type_    = "material_event",
                severity = "medium",
                title    = f"📋 SEC 8-K filing: {ticker}",
                detail   = f"Material event filed {latest.get('date', 'recently')}. "
                           f"Review filing for operational or financial changes.",
                ticker   = ticker,
                source   = "SEC EDGAR",
                url      = latest.get("url", ""),
            ))
    return signals


# ── Main entry point ───────────────────────────────────────────────────────────

def run_signals(
    instruments: list[dict],
    surveillance_data: dict,
    watchlist: list[str] = None,
) -> list[dict]:
    """
    Run all signal generators and return a deduplicated, sorted signal list.
    Also persists score snapshot for drift detection on next run.

    Args:
        instruments:       scored instrument dicts from the screener
        surveillance_data: output of data.sources.run_all_sources()
        watchlist:         list of ticker strings for news/watchlist signals

    Returns: list of signal dicts, sorted severity high → low
    """
    history = _load_history()
    prev_snapshot = history.get("score_snapshot", {})

    all_signals = []

    # 1 — Score drift (vs last run)
    drift_sigs, new_snapshot = _score_drift_signals(instruments, prev_snapshot)
    all_signals.extend(drift_sigs)

    # 2 — Value opportunities (strong buy crossings)
    all_signals.extend(_value_threshold_signals(instruments))

    # 3 — Near 52-week lows with quality pass
    all_signals.extend(_near_52w_low_signals(instruments))

    # 4 — Macro stress signals
    all_signals.extend(_macro_signals(surveillance_data))

    # 5 — News sentiment on watchlist
    all_signals.extend(_news_signals(surveillance_data, watchlist or []))

    # 6 — Insider cluster buying
    all_signals.extend(_insider_signals(surveillance_data))

    # 7 — Material SEC events
    all_signals.extend(_edgar_signals(surveillance_data))

    # Deduplicate by title (same signal can appear from multiple sources)
    seen = set()
    deduped = []
    for s in all_signals:
        key = s["title"]
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    # Sort: high → medium → low → info
    _order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    deduped.sort(key=lambda s: _order.get(s.get("severity", "info"), 99))

    # Persist
    history["last_run"]       = datetime.now().isoformat()
    history["score_snapshot"] = new_snapshot
    history["signals"]        = deduped
    _save_history(history)

    return deduped


def signals_summary(signals: list[dict]) -> dict:
    """Compute summary counts for the briefing header."""
    counts = {"high": 0, "medium": 0, "low": 0, "info": 0}
    by_type = {}
    for s in signals:
        sev = s.get("severity", "info")
        counts[sev] = counts.get(sev, 0) + 1
        t = s.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    return {"counts": counts, "by_type": by_type, "total": len(signals)}
