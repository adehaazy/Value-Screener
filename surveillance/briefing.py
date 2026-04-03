"""
Morning Briefing generator.

Produces a structured plain-English briefing from:
  - Latest signals (from utils/signals.py)
  - Macro context (FRED + ONS)
  - Top screener opportunities
  - Watchlist status

The briefing is persisted to cache/briefing.json so the app can show it
without re-running the full data pipeline.

No LLM used — all text is generated deterministically from data.
"""

import json
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path(__file__).parent.parent / "cache"
BRIEFING_FILE = CACHE_DIR / "briefing.json"


def _pct(v):
    if v is None:
        return "n/a"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def _rate(v):
    if v is None:
        return "n/a"
    return f"{v:.2f}%"


# ── Section builders ──────────────────────────────────────────────────────────

def _build_macro_section(macro_us: dict, macro_uk: dict) -> dict:
    """Build the macro context summary."""
    us_series = macro_us.get("series", {})
    uk_series = macro_uk.get("series", {})

    def _val(series_dict, key):
        return (series_dict.get(key) or {}).get("value")

    ffr      = _val(us_series, "DFF")
    dgs10    = _val(us_series, "DGS10")
    dgs2     = _val(us_series, "DGS2")
    t10y2y   = _val(us_series, "T10Y2Y")
    vix      = _val(us_series, "VIXCLS")
    hy       = _val(us_series, "BAMLH0A0HYM2")
    boe      = _val(uk_series, "BOE_BASE")
    gilt10   = _val(uk_series, "GILT_10Y")

    # Narrative headline
    curve_status = "inverted" if (t10y2y is not None and t10y2y < 0) else "normal"
    vix_status   = "elevated" if (vix is not None and vix > 25) else "calm" if (vix is not None and vix < 15) else "moderate"

    lines = []
    if ffr is not None:
        lines.append(f"Fed Funds: {_rate(ffr)}")
    if dgs10 is not None and dgs2 is not None:
        lines.append(f"US Treasuries: 2Y {_rate(dgs2)} / 10Y {_rate(dgs10)} (curve {curve_status})")
    if vix is not None:
        lines.append(f"VIX: {vix:.1f} ({vix_status} volatility)")
    if hy is not None:
        lines.append(f"HY Credit Spread: {hy:.0f}bps")
    if boe is not None:
        lines.append(f"BoE Base Rate: {_rate(boe)}")
    if gilt10 is not None:
        lines.append(f"UK 10Y Gilt: {_rate(gilt10)}")

    # Overall macro tone
    warnings = len(macro_us.get("signals", [])) + len(macro_uk.get("signals", []))
    if warnings >= 3:
        tone = "cautious"
        tone_detail = "Multiple macro stress indicators active. Consider quality bias and cash weighting."
    elif warnings >= 1:
        tone = "mixed"
        tone_detail = "Some macro headwinds present. Individual stock selection remains important."
    else:
        tone = "constructive"
        tone_detail = "Macro backdrop is relatively benign. No major stress signals active."

    return {
        "tone":        tone,
        "tone_detail": tone_detail,
        "metrics":     lines,
        "warnings":    warnings,
    }


def _build_opportunities_section(instruments: list[dict], top_n: int = 5) -> list[dict]:
    """Top scoring quality-passing instruments."""
    eligible = [
        inst for inst in instruments
        if inst.get("ok") and inst.get("score") is not None
        and inst.get("quality_passes", True) is not False
    ]
    eligible.sort(key=lambda x: x.get("score", 0), reverse=True)
    top = eligible[:top_n]

    return [
        {
            "ticker":  inst["ticker"],
            "name":    inst.get("name", inst["ticker"]),
            "score":   round(inst.get("score", 0), 1),
            "label":   inst.get("score_label", ""),
            "group":   inst.get("group", ""),
            "verdict": inst.get("verdict", ""),
            "pct_from_high": inst.get("pct_from_high"),
        }
        for inst in top
    ]


def _build_watchlist_section(instruments: list[dict], watchlist: list[str]) -> list[dict]:
    """Status of watchlist items."""
    inst_map = {inst["ticker"]: inst for inst in instruments if inst.get("ok")}
    result = []
    for ticker in watchlist:
        inst = inst_map.get(ticker)
        if not inst:
            continue
        result.append({
            "ticker":    ticker,
            "name":      inst.get("name", ticker),
            "score":     round(inst.get("score", 0), 1) if inst.get("score") else None,
            "label":     inst.get("score_label", ""),
            "ytd_pct":   inst.get("ytd_pct"),
            "yr1_pct":   inst.get("yr1_pct"),
            "pct_from_high": inst.get("pct_from_high"),
            "verdict":   inst.get("verdict", ""),
        })
    return result


def _build_signal_summary(signals: list[dict]) -> dict:
    """Group signals by type for the briefing header."""
    high    = [s for s in signals if s.get("severity") == "high"]
    medium  = [s for s in signals if s.get("severity") == "medium"]
    by_type = {}
    for s in signals:
        t = s.get("type", "other")
        by_type.setdefault(t, []).append(s)

    return {
        "total":   len(signals),
        "high":    len(high),
        "medium":  len(medium),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "top_3":   signals[:3],   # Most severe to show in header
    }


def _build_headline(macro: dict, opportunities: list, signals: dict, date_str: str) -> str:
    """Single sentence headline summarising the day."""
    tone = macro.get("tone", "mixed")
    n_opps = len([o for o in opportunities if o.get("score", 0) >= 70])
    n_alerts = signals.get("high", 0)

    parts = []
    if tone == "cautious":
        parts.append("Macro backdrop cautious")
    elif tone == "constructive":
        parts.append("Macro backdrop constructive")
    else:
        parts.append("Mixed macro signals")

    if n_opps > 0:
        parts.append(f"{n_opps} quality instrument{'s' if n_opps > 1 else ''} scoring 70+")

    if n_alerts > 0:
        parts.append(f"{n_alerts} high-priority alert{'s' if n_alerts > 1 else ''} require attention")

    return " · ".join(parts) + f" ({date_str})"


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_briefing(
    instruments: list[dict],
    signals: list[dict],
    surveillance_data: dict,
    watchlist: list[str] = None,
) -> dict:
    """
    Generate a complete morning briefing dict.
    Persists to cache/briefing.json for the app to display.

    Args:
        instruments:       scored instrument dicts
        signals:           output of signals.run_signals()
        surveillance_data: output of sources.run_all_sources()
        watchlist:         list of ticker strings

    Returns: briefing dict
    """
    now = datetime.now()
    date_str = now.strftime("%A %d %B %Y, %H:%M")

    macro_section  = _build_macro_section(
        surveillance_data.get("macro_us", {}),
        surveillance_data.get("macro_uk", {}),
    )
    opportunities  = _build_opportunities_section(instruments)
    watchlist_data = _build_watchlist_section(instruments, watchlist or [])
    signal_summary = _build_signal_summary(signals)
    headline       = _build_headline(macro_section, opportunities, signal_summary, date_str)

    # News highlights — top 5 market-moving headlines by absolute sentiment
    news_items = surveillance_data.get("news", {}).get("items", [])
    news_highlights = sorted(
        [n for n in news_items if abs(n.get("sentiment", 0)) > 0.2],
        key=lambda x: abs(x.get("sentiment", 0)),
        reverse=True,
    )[:5]

    briefing = {
        "generated_at":  now.isoformat(),
        "date_str":      date_str,
        "headline":      headline,
        "macro":         macro_section,
        "signal_summary": signal_summary,
        "signals":       signals,
        "opportunities": opportunities,
        "watchlist":     watchlist_data,
        "news_highlights": [
            {
                "title":     n["title"],
                "feed":      n.get("feed", ""),
                "sentiment": n.get("sentiment", 0),
                "link":      n.get("link", ""),
            }
            for n in news_highlights
        ],
    }

    CACHE_DIR.mkdir(exist_ok=True)
    BRIEFING_FILE.write_text(json.dumps(briefing, default=str, indent=2))
    return briefing


def load_briefing() -> dict | None:
    """Load the most recently generated briefing from disk."""
    if BRIEFING_FILE.exists():
        try:
            return json.loads(BRIEFING_FILE.read_text())
        except Exception:
            pass
    return None
