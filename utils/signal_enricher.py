"""
Signal enricher — attaches surveillance signals to instrument dicts.

Called after scoring so that every instrument carries its own signals.
This lets the UI show badges and nudged scores without querying the
signals list separately on every card render.

Design: reads from cache only — no network calls here.
"""

import json
from pathlib import Path

CACHE_DIR   = Path(__file__).parent.parent / "cache"
SIGNALS_FILE = CACHE_DIR / "signals_history.json"
SURV_DIR    = CACHE_DIR / "surveillance"


def _load_signals() -> list[dict]:
    if SIGNALS_FILE.exists():
        try:
            return json.loads(SIGNALS_FILE.read_text()).get("signals", [])
        except Exception:
            pass
    return []


def _load_score_snapshot() -> dict:
    """Previous scan scores — used for drift arrows."""
    if SIGNALS_FILE.exists():
        try:
            return json.loads(SIGNALS_FILE.read_text()).get("score_snapshot", {})
        except Exception:
            pass
    return {}


def _load_news_mentions() -> dict:
    """Ticker → list of news items from the RSS cache."""
    p = SURV_DIR / "rss_news.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("ticker_mentions", {})
        except Exception:
            pass
    return {}


def _load_insider_data() -> dict:
    """Ticker → list of insider transactions from the cache."""
    p = SURV_DIR / "insider_buys.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _load_edgar_events() -> dict:
    """Ticker → list of recent 8-K filings."""
    p = SURV_DIR / "edgar_events.json"
    if p.exists():
        try:
            return json.loads(p.read_text()).get("events", {})
        except Exception:
            pass
    return {}


# ── Nudge calculation ─────────────────────────────────────────────────────────

def _compute_score_nudge(ticker: str, news_mentions: dict, insider_data: dict) -> tuple[float, list[str]]:
    """
    Returns (nudge_points, nudge_reasons).
    nudge_points can be positive or negative, clamped to ±10.
    """
    nudge = 0.0
    reasons = []

    # Insider cluster buy: +5
    cluster_sigs = insider_data.get("cluster_signals", [])
    if any(s.get("ticker") == ticker for s in cluster_sigs):
        nudge += 5.0
        reasons.append("+5 insider cluster buying")

    # News sentiment nudge: ±5 based on average sentiment
    mentions = news_mentions.get(ticker, [])
    if mentions:
        sentiments = [m.get("sentiment", 0) for m in mentions]
        avg = sum(sentiments) / len(sentiments)
        if avg < -0.3:
            pts = -5.0 if avg < -0.6 else -3.0
            nudge += pts
            reasons.append(f"{pts:+.0f} negative news sentiment ({len(mentions)} headlines)")
        elif avg > 0.3:
            pts = 3.0 if avg > 0.6 else 2.0
            nudge += pts
            reasons.append(f"+{pts:.0f} positive news sentiment ({len(mentions)} headlines)")

    return max(min(nudge, 10.0), -10.0), reasons


# ── Per-instrument badge builder ──────────────────────────────────────────────

def _build_badges(ticker: str, signals: list[dict], news_mentions: dict,
                  insider_data: dict, edgar_events: dict) -> list[dict]:
    """
    Returns a list of badge dicts for this ticker:
      {"icon": str, "label": str, "colour": str, "severity": str, "detail": str}
    """
    badges = []
    ticker_sigs = [s for s in signals if s.get("ticker") == ticker]

    for sig in ticker_sigs:
        stype = sig.get("type", "")
        sev   = sig.get("severity", "info")

        if stype == "score_drift":
            drift = sig.get("drift", 0)
            icon  = "▲" if drift > 0 else "▼"
            col   = "#2A6B44" if drift > 0 else "#8B2635"
            badges.append({"icon": icon, "label": f"{drift:+.0f} pts",
                           "colour": col, "severity": sev, "detail": sig.get("detail", "")})

        elif stype == "near_52w_low":
            badges.append({"icon": "◆", "label": "Near low",
                           "colour": "#2C4460", "severity": sev, "detail": sig.get("detail", "")})

        elif stype == "value_opportunity":
            badges.append({"icon": "●", "label": "Strong value",
                           "colour": "#1E5C38", "severity": sev, "detail": sig.get("detail", "")})

    # News sentiment badge
    mentions = news_mentions.get(ticker, [])
    if mentions:
        sentiments = [m.get("sentiment", 0) for m in mentions]
        avg = sum(sentiments) / len(sentiments)
        if avg < -0.3:
            col = "#8B2635"
            badges.append({"icon": "▼", "label": f"{len(mentions)} neg. headlines",
                           "colour": col, "severity": "high" if avg < -0.6 else "medium",
                           "detail": f'Latest: "{mentions[0]["title"][:60]}"'})
        elif avg > 0.3:
            badges.append({"icon": "▲", "label": f"{len(mentions)} pos. headlines",
                           "colour": "#2A6B44", "severity": "low",
                           "detail": f'Latest: "{mentions[0]["title"][:60]}"'})

    # Insider cluster badge
    cluster_sigs = insider_data.get("cluster_signals", [])
    if any(s.get("ticker") == ticker for s in cluster_sigs):
        badges.append({"icon": "◆", "label": "Insider buy",
                       "colour": "#9B6B1A", "severity": "medium",
                       "detail": "Multiple insiders bought shares in last 30 days."})

    # 8-K filing badge
    if edgar_events.get(ticker):
        badges.append({"icon": "◆", "label": "8-K filing",
                       "colour": "#B85C20", "severity": "medium",
                       "detail": f"Material event filed {edgar_events[ticker][0].get('date', 'recently')}."})

    return badges


# ── Main entry point ──────────────────────────────────────────────────────────

def enrich_with_signals(instruments: list[dict]) -> list[dict]:
    """
    Attach signal badges, score nudges, and drift arrows to every instrument.
    Reads from cache only — safe to call on every Streamlit rerun.

    Adds these keys to each instrument dict:
      signal_badges   list[dict]  — badges to render on card
      score_nudge     float       — points added/subtracted from base score
      score_nudge_reasons list    — plain-English explanation
      score_adjusted  float|None  — score + nudge (clamped 0–100)
      score_drift     float|None  — change vs previous scan (positive = improved)
      has_signals     bool        — True if any badge present
    """
    signals      = _load_signals()
    snapshot     = _load_score_snapshot()
    news_mentions = _load_news_mentions()
    insider_data = _load_insider_data()
    edgar_events = _load_edgar_events()

    enriched = []
    for inst in instruments:
        inst = dict(inst)  # don't mutate originals
        ticker = inst.get("ticker", "")
        score  = inst.get("score")

        # Score drift vs previous scan
        prev_score = snapshot.get(ticker)
        if score is not None and prev_score is not None:
            inst["score_drift"] = round(score - prev_score, 1)
        else:
            inst["score_drift"] = None

        # Nudge
        nudge, nudge_reasons = _compute_score_nudge(ticker, news_mentions, insider_data)
        inst["score_nudge"]         = round(nudge, 1)
        inst["score_nudge_reasons"] = nudge_reasons

        # Adjusted score
        if score is not None:
            inst["score_adjusted"] = round(max(min(score + nudge, 100), 0), 1)
        else:
            inst["score_adjusted"] = None

        # Badges
        badges = _build_badges(ticker, signals, news_mentions, insider_data, edgar_events)
        inst["signal_badges"] = badges
        inst["has_signals"]   = len(badges) > 0

        enriched.append(inst)

    return enriched


def get_changed_instruments(instruments: list[dict], min_drift: float = 5.0) -> list[dict]:
    """
    Return instruments whose score drifted by at least min_drift since last scan,
    sorted largest change first.
    """
    changed = [
        i for i in instruments
        if i.get("score_drift") is not None and abs(i["score_drift"]) >= min_drift
    ]
    return sorted(changed, key=lambda x: abs(x.get("score_drift", 0)), reverse=True)


def get_macro_context() -> dict:
    """
    Load macro indicators for the dashboard status bar.
    Returns the FRED cache dict or empty dict if not available.
    """
    p = SURV_DIR / "fred_macro.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def get_uk_macro_context() -> dict:
    p = SURV_DIR / "uk_macro.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}
