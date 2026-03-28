"""
Value Screener v3 — Personal Investment Research Tool
Quality at a fair price. UK · EU · US stocks · ETFs · Money Market funds.

Run: python3 -m streamlit run app.py
Or:  double-click "Start Value Screener.command" (Mac)
                  "Start Value Screener.bat"     (Windows)
"""

import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np

# ── Check for required packages ────────────────────────────────────────────────
try:
    import streamlit as st
except ImportError:
    print("ERROR: streamlit not installed. Run: pip install streamlit")
    sys.exit(1)

try:
    import yfinance as yf  # noqa: F401  (checked here so we can show friendly error)
except ImportError:
    st.error("⚠️ Required package missing. Close this window and re-run 'Start Value Screener'.")
    st.stop()

import pandas as pd

# ── Local modules ──────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from data.universe import UNIVERSE
from data.fetcher   import (fetch_one, compute_sector_medians,
                             save_scan_summary, load_scan_summary,
                             any_cache_exists, cache_age_hours,
                             _cache_is_fresh, _load_cache)   # public API usage
from utils.scoring  import (score_all, score_label, score_colour, score_bg,
                             DEFAULT_QUALITY_THRESHOLDS)
from utils.verdicts import add_verdicts
from utils.signals        import load_latest_signals, get_last_run_time, signals_summary
from utils.signal_enricher import (enrich_with_signals, get_changed_instruments,
                                    get_macro_context, get_uk_macro_context)
from surveillance.briefing import load_briefing
from utils.deep_analysis   import (run_deep_analysis, load_cached_analysis,
                                    cache_age_days, build_data_context)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG & GLOBAL CSS
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Value Screener",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Layout ── */
.block-container { padding: 1.5rem 2rem 2rem 2rem; }
div[data-testid="stSidebarContent"] { padding: 1rem 1rem; }

/* ── Instrument card ── */
.card {
    background: #161926;
    border: 1px solid #2a2f45;
    border-radius: 12px;
    padding: 18px 20px 14px 20px;
    margin-bottom: 14px;
    transition: border-color 0.2s;
}
.card:hover { border-color: #4a5080; }
.card-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;
}
.card-title { font-size: 1.05rem; font-weight: 600; color: #e8eaf6; }
.card-sub   { font-size: 0.78rem; color: #8890b0; margin-top: 2px; }
.card-score-box {
    border-radius: 8px;
    padding: 6px 12px;
    text-align: center;
    min-width: 72px;
    flex-shrink: 0;
}
.card-score-num { font-size: 1.5rem; font-weight: 800; line-height: 1; }
.card-score-lbl { font-size: 0.65rem; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 2px; }
.card-verdict   { font-size: 0.85rem; color: #b0b8d0; line-height: 1.5; margin: 10px 0 12px 0; }
.card-metrics   { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }

/* ── Metric pills ── */
.metric-pill {
    background: #1e2235;
    border-radius: 20px;
    padding: 3px 10px;
    font-size: 0.75rem;
    color: #9095b0;
}
.metric-pill b { color: #c8cee8; }
.metric-pill.good   { background: #0a2210; color: #4ede8a; }
.metric-pill.good b { color: #4ede8a; }
.metric-pill.warn   { background: #2a1800; color: #ffb74d; }
.metric-pill.warn b { color: #ffb74d; }
.metric-pill.bad    { background: #2a0a0a; color: #ff5252; }
.metric-pill.bad b  { color: #ff5252; }

/* ── Quality fail badge ── */
.quality-fail {
    background: #2a0a0a;
    color: #ff5252;
    border-radius: 6px;
    padding: 3px 8px;
    font-size: 0.72rem;
    display: inline-block;
    margin-bottom: 6px;
}

/* ── Section headers ── */
.section-header {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #5a6080;
    margin-bottom: 10px;
    margin-top: 4px;
}

/* ── Dashboard summary tiles ── */
.summary-tile {
    background: #161926;
    border: 1px solid #2a2f45;
    border-radius: 10px;
    padding: 16px 18px;
}
.summary-number { font-size: 2rem; font-weight: 700; line-height: 1; color: #e8eaf6; }
.summary-label  { font-size: 0.72rem; color: #8890b0; text-transform: uppercase; letter-spacing: 0.06em; }

/* ── Signal badges on cards ── */
.signal-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 0.70rem;
    font-weight: 600;
    margin-right: 4px;
    margin-bottom: 4px;
    cursor: default;
}
.signal-badge-row {
    display: flex;
    flex-wrap: wrap;
    gap: 2px;
    margin-bottom: 8px;
}

/* ── Macro status bar ── */
.macro-bar {
    background: #0e1120;
    border: 1px solid #2a2f45;
    border-radius: 8px;
    padding: 10px 16px;
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    align-items: center;
    margin-bottom: 16px;
}
.macro-item {
    display: flex;
    flex-direction: column;
    align-items: center;
}
.macro-item-val { font-size: 0.9rem; font-weight: 700; line-height: 1.2; }
.macro-item-lbl { font-size: 0.62rem; color: #5a6080; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 1px; }

/* ── Changed-since-scan banner ── */
.changed-banner {
    background: #101520;
    border: 1px solid #2a2f45;
    border-left: 4px solid #7986cb;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 16px;
    font-size: 0.85rem;
    color: #9095b0;
}
.changed-banner b { color: #c8cee8; }

/* ── Score breakdown table ── */
.breakdown-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 0;
    border-bottom: 1px solid #1e2235;
    font-size: 0.78rem;
    color: #9095b0;
}
.breakdown-row:last-child { border-bottom: none; }
.breakdown-bar-bg {
    background: #1e2235;
    border-radius: 4px;
    height: 6px;
    flex: 1;
    margin: 0 10px;
    overflow: hidden;
}
.breakdown-bar-fill { height: 100%; border-radius: 4px; }

/* ── Deep Analysis ── */
.da-section {
    background: #111420;
    border: 1px solid #2a2f45;
    border-radius: 10px;
    padding: 16px 20px;
    margin: 10px 0 6px 0;
}
.da-section-title {
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #7986cb;
    text-transform: uppercase;
    margin-bottom: 8px;
}
.da-score-row {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 6px;
}
.da-score-big {
    font-size: 2rem;
    font-weight: 800;
    line-height: 1;
}
.da-rating {
    font-size: 0.85rem;
    font-weight: 600;
    padding: 3px 10px;
    border-radius: 20px;
}
.da-confidence {
    font-size: 0.75rem;
    color: #8890b0;
    margin-left: 4px;
}
.da-bar-bg {
    background: #1e2235;
    border-radius: 4px;
    height: 8px;
    flex: 1;
    overflow: hidden;
    margin: 0 10px;
}
.da-bar-fill { height: 100%; border-radius: 4px; }
.da-component-row {
    display: flex;
    align-items: center;
    padding: 5px 0;
    border-bottom: 1px solid #1e2235;
    font-size: 0.8rem;
    color: #9095b0;
    gap: 8px;
}
.da-component-row:last-child { border-bottom: none; }
.da-just {
    font-size: 0.78rem;
    color: #8890b0;
    line-height: 1.5;
    margin-top: 6px;
    padding-top: 6px;
    border-top: 1px solid #1e2235;
}
.da-risk-tag {
    display: inline-block;
    background: #2a1a1a;
    color: #ff7043;
    border: 1px solid #ff704344;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    margin: 2px 3px 2px 0;
}
.da-driver-tag {
    display: inline-block;
    background: #0a2e1a;
    color: #4ede8a;
    border: 1px solid #4ede8a44;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    margin: 2px 3px 2px 0;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENT STATE (disk)
# ══════════════════════════════════════════════════════════════════════════════

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _load_json(filename: str, default):
    p = CACHE_DIR / filename
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return default
    return default


def _save_json(filename: str, data):
    (CACHE_DIR / filename).write_text(json.dumps(data, default=str, indent=2))


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INIT
# ══════════════════════════════════════════════════════════════════════════════

def _init_state():
    if "instruments" not in st.session_state:
        st.session_state.instruments = []
    if "sector_medians" not in st.session_state:
        st.session_state.sector_medians = {}
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = _load_json("watchlist.json", [])
    if "prefs" not in st.session_state:
        st.session_state.prefs = _load_json("prefs.json", {
            # Display filters
            "groups":    ["🇬🇧 UK Stocks", "📦 ETFs & Index Funds"],
            "min_score": 0,
            "min_yield": 0.0,
            "max_pe":    100,
            "max_ter":   1.5,
            # Quality gate (stocks)
            "min_roe":           10,   # % e.g. 10 = 10%
            "max_de":            2,    # ratio e.g. 2 = 2.0x
            "min_profit_margin": 2,    # % e.g. 2 = 2%
            "require_pos_fcf":   True,
            # Stock valuation weights (relative importance, 0–100)
            "wt_pe":       30,
            "wt_pb":       20,
            "wt_evebitda": 20,
            "wt_divyield": 15,
            "wt_52w":      15,
            # ETF weights
            "wt_etf_aum":    35,
            "wt_etf_ter":    35,
            "wt_etf_ret":    20,
            "wt_etf_mom":    10,
            # Money market weights
            "wt_mm_yield":   60,
            "wt_mm_aum":     25,
            "wt_mm_ter":     15,
        })
    if "scoring_changed" not in st.session_state:
        st.session_state.scoring_changed = False  # True when weights changed but not rescored
    if "last_fetch" not in st.session_state:
        st.session_state.last_fetch = None
    if "page" not in st.session_state:
        st.session_state.page = "home"
    if "toast" not in st.session_state:
        st.session_state.toast = None          # (message, type) or None
    if "show_excluded" not in st.session_state:
        st.session_state.show_excluded = False  # toggle for quality-fail stocks
    if "show_flagged_only" not in st.session_state:
        st.session_state.show_flagged_only = False  # filter to signal-flagged instruments only
    if "wl_search_result" not in st.session_state:
        st.session_state.wl_search_result = None    # dict or "not_found" or "error:<msg>"
    if "wl_refreshing" not in st.session_state:
        st.session_state.wl_refreshing = set()      # tickers currently being refreshed
    if "da_extra" not in st.session_state:
        st.session_state.da_extra = {}              # {ticker: extra_context_text}


_init_state()


# ══════════════════════════════════════════════════════════════════════════════
# FORMAT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _f(v):
    """Safely coerce to float, returning None for anything non-numeric."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else f   # NaN → None
    except (TypeError, ValueError):
        return None


def _fmt_pct(v, d=1):
    v = _f(v)
    if v is None:
        return "—"
    # Avoid formatting -0.0 as "-0.0%"
    if abs(v) < 0.05:
        return "0.0%"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{d}f}%"


def _fmt_ratio(v, d=1):
    v = _f(v)
    if v is None:
        return "—"
    return f"{v:.{d}f}x"


def _fmt_price(v, cur=""):
    v = _f(v)
    if v is None:
        return "—"
    return f"{cur}{v:,.2f}"


def _fmt_aum(v):
    v = _f(v)
    if v is None:
        return "—"
    if v >= 1e9:
        return f"${v/1e9:.1f}bn"
    if v >= 1e6:
        return f"${v/1e6:.0f}m"
    return f"${v:,.0f}"


def _pill(label, value, cls=""):
    return f'<span class="metric-pill {cls}"><b>{value}</b> {label}</span>'


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def _build_quality_thresholds():
    p = st.session_state.prefs
    return {
        "min_roe":             p.get("min_roe", 10) / 100,            # slider %, convert to decimal
        "max_debt_equity":     p.get("max_de",   2),                   # ratio
        "min_profit_margin":   p.get("min_profit_margin", 2) / 100,   # slider %, convert to decimal
        "require_positive_fcf": p.get("require_pos_fcf", True),
    }


def _build_scoring_weights() -> dict:
    """
    Returns per-asset-class weight dicts from user prefs.
    These are passed into the scoring functions which already normalise by sum(wts).
    """
    p = st.session_state.prefs
    return {
        "stock": {
            "pe":       p.get("wt_pe",       30),
            "pb":       p.get("wt_pb",       20),
            "evebitda": p.get("wt_evebitda", 20),
            "divyield": p.get("wt_divyield", 15),
            "w52":      p.get("wt_52w",      15),
        },
        "etf": {
            "aum": p.get("wt_etf_aum", 35),
            "ter": p.get("wt_etf_ter", 35),
            "ret": p.get("wt_etf_ret", 20),
            "mom": p.get("wt_etf_mom", 10),
        },
        "mm": {
            "yield": p.get("wt_mm_yield", 60),
            "aum":   p.get("wt_mm_aum",   25),
            "ter":   p.get("wt_mm_ter",   15),
        },
    }


def load_all_data(groups: list, progress_cb=None) -> tuple:
    """Fetch all instruments, score them, compute sector medians."""
    raw = []
    total_tickers = sum(len(UNIVERSE[g]["tickers"]) for g in groups if g in UNIVERSE)
    done = 0

    for group in groups:
        if group not in UNIVERSE:
            continue
        meta = UNIVERSE[group]
        for ticker, name in meta["tickers"].items():
            inst = fetch_one(ticker, name, meta["asset_class"], group)
            raw.append(inst)
            done += 1
            if progress_cb:
                progress_cb(done / max(total_tickers, 1),
                            f"Loading {group} — {name}")

    sector_medians = compute_sector_medians(raw)
    qt = _build_quality_thresholds()
    sw = _build_scoring_weights()
    scored = score_all(raw, sector_medians, qt, sw)
    scored = add_verdicts(scored, sector_medians)
    scored = enrich_with_signals(scored)
    return scored, sector_medians


def _auto_load_from_cache(groups: list):
    """Load instruments from local cache without hitting Yahoo Finance."""
    raw = []
    for group in groups:
        if group not in UNIVERSE:
            continue
        meta = UNIVERSE[group]
        for ticker, name in meta["tickers"].items():
            if _cache_is_fresh(ticker):
                inst = _load_cache(ticker)
                inst["name"]        = name
                inst["group"]       = group
                inst["asset_class"] = meta["asset_class"]
                inst.setdefault("ok", True)   # ensure ok flag exists on old cache files
                raw.append(inst)

    if not raw:
        return False

    sector_medians = compute_sector_medians(raw)
    qt = _build_quality_thresholds()
    sw = _build_scoring_weights()
    scored = score_all(raw, sector_medians, qt, sw)
    scored = add_verdicts(scored, sector_medians)
    scored = enrich_with_signals(scored)

    st.session_state.instruments   = scored
    st.session_state.sector_medians = sector_medians
    return True


# Auto-load on startup from cache (no fetch required)
if not st.session_state.instruments and any_cache_exists():
    groups = st.session_state.prefs.get("groups", list(UNIVERSE.keys())[:2])
    _auto_load_from_cache(groups)


# ══════════════════════════════════════════════════════════════════════════════
# FILTERS
# ══════════════════════════════════════════════════════════════════════════════

def apply_filters(instruments: list, include_excluded=False) -> list:
    """
    Apply sidebar filters to instrument list.
    include_excluded=True returns only quality-failed stocks (for the toggle).
    """
    p = st.session_state.prefs
    passing, excluded = [], []

    for inst in instruments:
        if not inst.get("ok"):
            continue

        # Quality-failed stocks go to excluded bucket regardless of other filters
        if inst.get("asset_class") == "Stock" and not inst.get("quality_passes", True):
            excluded.append(inst)
            continue

        s   = _f(inst.get("score"))
        div = _f(inst.get("div_yield"))
        pe  = _f(inst.get("pe"))
        ter = _f(inst.get("ter"))
        max_ter_decimal = p.get("max_ter", 1.5) / 100

        if s   is not None and s   < p.get("min_score", 0):                   continue
        if div is not None and div < p.get("min_yield",  0):                  continue
        if pe  is not None and p.get("max_pe", 100) < 100 and pe > p.get("max_pe", 100): continue
        if ter is not None and ter > max_ter_decimal:                          continue

        passing.append(inst)

    passing  = sorted(passing,  key=lambda x: (_f(x.get("score")) or 0), reverse=True)
    excluded = sorted(excluded, key=lambda x: x.get("name", ""))

    return excluded if include_excluded else passing


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 📊 Value Screener")
    st.caption("Quality · Fair Price · Long-term")
    st.divider()

    # ── Navigation ──────────────────────────────────────────────────────────
    # Show alert badge on Signals nav button if there are high-severity signals
    _latest_signals = load_latest_signals()
    _high_count = sum(1 for s in _latest_signals if s.get("severity") == "high")
    _signals_label = f"🚨  Signals  ({_high_count} new)" if _high_count > 0 else "🚨  Signals"

    _scoring_changed = st.session_state.scoring_changed
    _settings_label  = "⚙️  Settings  ●" if _scoring_changed else "⚙️  Settings"

    pages = {
        "🏠  Dashboard":   "home",
        "🔍  Find Ideas":  "screener",
        "⭐  My Holdings": "watchlist",
        "📈  Compare":     "compare",
        _signals_label:    "signals",
        "📰  Briefing":    "briefing",
        _settings_label:   "settings",
    }
    for label, key in pages.items():
        active = st.session_state.page == key
        if st.button(label, key=f"nav_{key}",
                     type="primary" if active else "secondary",
                     use_container_width=True):
            st.session_state.page = key
            st.rerun()

    st.divider()

    # ── Universe + Load ──────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Markets to screen</div>', unsafe_allow_html=True)

    chosen_groups = st.multiselect(
        "Asset classes",
        list(UNIVERSE.keys()),
        default=st.session_state.prefs.get("groups", ["🇬🇧 UK Stocks", "📦 ETFs & Index Funds"]),
        label_visibility="collapsed",
    )
    # FIX Bug 12: use set comparison so order differences don't falsely trigger a save
    if set(chosen_groups) != set(st.session_state.prefs.get("groups", [])):
        st.session_state.prefs["groups"] = chosen_groups
        _save_json("prefs.json", st.session_state.prefs)

    fetch_label = "🔄  Refresh Data" if st.session_state.instruments else "⬇️  Load Data"
    if st.button(fetch_label, type="primary", use_container_width=True):
        if chosen_groups:
            prog = st.progress(0, text="Starting…")
            def _cb(pct, msg):
                prog.progress(pct, text=msg)
            scored, sm = load_all_data(chosen_groups, progress_cb=_cb)
            prog.empty()
            st.session_state.instruments    = scored
            st.session_state.sector_medians = sm
            st.session_state.last_fetch     = datetime.now().strftime("%H:%M  %d %b %Y")
            ok = [x for x in scored if x.get("ok")]
            save_scan_summary({
                "total": len(ok),
                "stocks_passing_quality": sum(
                    1 for x in ok
                    if x.get("asset_class") == "Stock" and x.get("quality_passes")
                ),
                "strong_value":  sum(1 for x in ok if (_f(x.get("score")) or 0) >= 75),
                "top_picks": [
                    {"ticker": x["ticker"], "name": x["name"],
                     "score": x.get("score"), "verdict": x.get("verdict", "")}
                    for x in sorted(ok, key=lambda r: _f(r.get("score")) or 0, reverse=True)[:5]
                ],
                "fetched_at": datetime.now().isoformat(),
            })
            st.rerun()
        else:
            st.warning("Choose at least one market above.")

    age = cache_age_hours()
    if age is not None:
        st.caption(f"Data is {age:.0f}h old · {'fresh' if age < 6 else 'consider refreshing'}")
    else:
        st.caption("No data loaded yet")

    st.divider()

    # ── Filters (only shown on Find Ideas page) ──────────────────────────────
    current_page = st.session_state.page
    if current_page == "screener":
        st.markdown('<div class="section-header">Filters</div>', unsafe_allow_html=True)
        p = st.session_state.prefs

        min_score = st.slider("Minimum score",            0,   100, int(p.get("min_score", 0)),   5,
                              help="Only show instruments scoring at least this")
        min_yield = st.slider("Minimum yield (%)",        0.0,  8.0, float(p.get("min_yield", 0.0)), 0.5,
                              help="Minimum dividend or distribution yield")
        max_pe    = st.slider("Max P/E (stocks)",         5,   100, int(p.get("max_pe",  100)),   5,
                              help="Filter out expensive stocks. Set to 100 to show all.")
        max_ter   = st.slider("Max fund cost / TER (%)",  0.05, 1.5, float(p.get("max_ter", 1.5)), 0.05,
                              help="Maximum annual fee for ETFs and money market funds")

        changed = (min_score != p.get("min_score") or min_yield != p.get("min_yield")
                   or max_pe != p.get("max_pe") or max_ter != p.get("max_ter"))
        if changed:
            p["min_score"] = min_score
            p["min_yield"] = min_yield
            p["max_pe"]    = max_pe
            p["max_ter"]   = max_ter
            _save_json("prefs.json", p)

        st.divider()
        # ── Quality gate settings ────────────────────────────────────────────
        with st.expander("⚙️  Quality gate (stocks only)"):
            st.caption("Stocks must pass ALL of these to appear in results.")
            # FIX Bug 7: slider now 0–10 (ratio), stored as ratio, no unit confusion
            min_roe = st.slider("Minimum ROE (%)",     0, 30, int(p.get("min_roe", 10)), 1,
                                help="Return on Equity — how efficiently the business uses your money")
            max_de  = st.slider("Max Debt/Equity",     0, 10, int(p.get("max_de",   2)), 1,
                                help="Financial leverage. 2 = manageable, 5+ = high risk.")
            if min_roe != p.get("min_roe") or max_de != p.get("max_de"):
                p["min_roe"] = min_roe
                p["max_de"]  = max_de
                _save_json("prefs.json", p)

    elif current_page == "home":
        st.markdown('<div class="section-header">Quick settings</div>', unsafe_allow_html=True)
        st.caption("Switch to Find Ideas for full filters")
    # On watchlist / compare / signals / briefing pages, sidebar stays clean — no filter noise


# ══════════════════════════════════════════════════════════════════════════════
# TOAST NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _show_toast():
    """Render and clear any pending toast notification."""
    if st.session_state.toast:
        msg, kind = st.session_state.toast
        if kind == "success":
            st.toast(msg, icon="✅")
        elif kind == "info":
            st.toast(msg, icon="ℹ️")
        elif kind == "warning":
            st.toast(msg, icon="⚠️")
        st.session_state.toast = None


_show_toast()


# ══════════════════════════════════════════════════════════════════════════════
# SCORE BREAKDOWN COMPONENT
# ══════════════════════════════════════════════════════════════════════════════

def _render_score_breakdown(inst: dict):
    """Render a compact score breakdown table inside an expander."""
    components = inst.get("score_components", {})
    if not components:
        st.caption("Score breakdown not available.")
        return

    rows_html = ""
    for label, item in components.items():
        score  = item.get("score")
        weight = item.get("weight", 0)
        if score is None:
            bar_html = '<div class="breakdown-bar-bg"><div class="breakdown-bar-fill" style="width:0%;background:#555"></div></div>'
            score_str = "no data"
            label_col = "#666"
        else:
            pct   = max(min(score, 100), 0)
            col   = score_colour(score)
            bar_html = (f'<div class="breakdown-bar-bg">'
                        f'<div class="breakdown-bar-fill" style="width:{pct:.0f}%;background:{col}"></div>'
                        f'</div>')
            score_str = f"{score:.0f}/100"
            label_col = "#9095b0"

        rows_html += (f'<div class="breakdown-row">'
                      f'<span style="min-width:160px;color:{label_col}">{label}</span>'
                      f'{bar_html}'
                      f'<span style="min-width:60px;text-align:right;color:{label_col}">{score_str}</span>'
                      f'<span style="min-width:42px;text-align:right;color:#555">{weight}%</span>'
                      f'</div>')

    note = ""
    if inst.get("sector_relative"):
        note = '<div style="font-size:0.7rem;color:#555;margin-top:6px">Valuation scored relative to sector peers</div>'
    st.markdown(f'<div style="padding:4px 0">{rows_html}{note}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# MACRO STATUS BAR
# ══════════════════════════════════════════════════════════════════════════════

def _render_macro_bar():
    """
    One-line macro context bar shown at the top of the dashboard.
    Reads from surveillance cache — silent if no surveillance has run yet.
    """
    macro_us = get_macro_context()
    macro_uk = get_uk_macro_context()
    if not macro_us and not macro_uk:
        return  # No surveillance data yet — don't show anything

    s_us = macro_us.get("series", {})
    s_uk = macro_uk.get("series", {})

    def _val(series, key):
        return (series.get(key) or {}).get("value")

    items = []

    ffr    = _val(s_us, "DFF")
    dgs10  = _val(s_us, "DGS10")
    t10y2y = _val(s_us, "T10Y2Y")
    vix    = _val(s_us, "VIXCLS")
    hy     = _val(s_us, "BAMLH0A0HYM2")
    boe    = _val(s_uk, "BOE_BASE")
    gilt   = _val(s_uk, "GILT_10Y")

    # Colour logic
    def rate_col(v):  return "#e8eaf6" if v is not None else "#555"
    def curve_col(v): return "#ff5252" if (v is not None and v < 0) else "#4ede8a" if (v is not None and v > 0.5) else "#ffb74d"
    def vix_col(v):   return "#ff5252" if (v is not None and v > 30) else "#ffb74d" if (v is not None and v > 20) else "#4ede8a"
    def hy_col(v):    return "#ff5252" if (v is not None and v > 500) else "#ffb74d" if (v is not None and v > 350) else "#4ede8a"

    if ffr is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(ffr)}">{ffr:.2f}%</div><div class="macro-item-lbl">Fed Funds</div></div>')
    if boe is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(boe)}">{boe:.2f}%</div><div class="macro-item-lbl">BoE Rate</div></div>')
    if dgs10 is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(dgs10)}">{dgs10:.2f}%</div><div class="macro-item-lbl">US 10Y</div></div>')
    if gilt is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(gilt)}">{gilt:.2f}%</div><div class="macro-item-lbl">UK Gilt 10Y</div></div>')
    if t10y2y is not None:
        label = "⚠ Inverted" if t10y2y < 0 else "Yield Curve"
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{curve_col(t10y2y)}">{t10y2y:+.2f}%</div><div class="macro-item-lbl">{label}</div></div>')
    if vix is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{vix_col(vix)}">{vix:.1f}</div><div class="macro-item-lbl">VIX</div></div>')
    if hy is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{hy_col(hy)}">{hy:.0f}bps</div><div class="macro-item-lbl">HY Spread</div></div>')

    if not items:
        return

    # Overall tone dot
    all_signals = macro_us.get("signals", []) + macro_uk.get("signals", [])
    high_count  = sum(1 for s in all_signals if s.get("severity") == "high")
    tone_col    = "#ff5252" if high_count >= 2 else "#ffb74d" if high_count == 1 else "#4ede8a"
    tone_lbl    = "Cautious" if high_count >= 2 else "Mixed" if high_count == 1 else "Constructive"
    tone_item   = (f'<div class="macro-item" style="border-right:1px solid #2a2f45;padding-right:20px;margin-right:4px">'
                   f'<div class="macro-item-val" style="color:{tone_col}">● {tone_lbl}</div>'
                   f'<div class="macro-item-lbl">Macro Backdrop</div></div>')

    bar_html = '<div class="macro-bar">' + tone_item + "".join(items) + "</div>"
    st.markdown(bar_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# INSTRUMENT CARD RENDERER
# ══════════════════════════════════════════════════════════════════════════════

# Per-page render counter — incremented each time a ticker's card is rendered.
# The screener renders each instrument twice (once in "All" tab, once in its
# group tab), so we need a suffix to avoid duplicate Streamlit widget keys.
_render_counter: dict = {}


def render_card(inst: dict, show_add_watchlist=True):
    """Render a full instrument verdict card."""
    ticker  = inst.get("ticker", "unknown")
    _render_counter[ticker] = _render_counter.get(ticker, 0) + 1
    _ks = f"{ticker}_{_render_counter[ticker]}"   # unique key suffix
    score   = _f(inst.get("score"))
    passes  = inst.get("quality_passes", True)
    ac      = inst.get("asset_class", "")
    verdict = inst.get("verdict", "—")
    name    = inst.get("name", ticker)
    group   = inst.get("group", "")
    sector  = inst.get("sector", "")
    cur     = inst.get("currency", "")
    is_wl   = ticker in {w["ticker"] for w in st.session_state.watchlist}

    # Score box
    bg           = score_bg(score)    if passes else "#1a1a2a"
    colour       = score_colour(score) if passes else "#888"
    rating_label = score_label(score)  if passes else "Not scored"
    score_display = f"{score:.0f}" if score is not None else "—"

    # Subtitle: "UK Stocks  ·  Technology"
    group_short = group.split(" ", 1)[-1].strip() if group else ""
    sub_parts   = [p for p in [group_short, sector] if p and p not in ("—", "Unknown", "")]
    subtitle    = "  ·  ".join(sub_parts[:2])

    # ── Metric pills ──────────────────────────────────────────────────────────
    pills_html = ""
    if ac == "Stock":
        pe  = _f(inst.get("pe"))
        pb  = _f(inst.get("pb"))
        div = _f(inst.get("div_yield"))
        roe = _f(inst.get("roe"))
        de  = _f(inst.get("debt_equity"))
        sm  = st.session_state.sector_medians.get(sector, {})
        sm_pe = _f(sm.get("pe"))

        if pe is not None:
            if sm_pe:
                pe_str = f"{pe:.1f}x (sector {sm_pe:.1f}x)"
                cls = "good" if pe < sm_pe * 0.9 else "bad" if pe > sm_pe * 1.15 else ""
            else:
                pe_str = f"{pe:.1f}x"
                cls = "good" if pe < 15 else "bad" if pe > 30 else ""
            pills_html += _pill("P/E", pe_str, cls)

        if pb is not None:
            cls = "good" if pb < 2 else "bad" if pb > 4 else ""
            pills_html += _pill("P/B", f"{pb:.1f}x", cls)

        if roe is not None:
            cls = "good" if roe >= 0.15 else "warn" if roe >= 0.10 else "bad"
            pills_html += _pill("ROE", f"{roe*100:.1f}%", cls)

        if div and div > 0:
            cls = "good" if div >= 3 else ""
            pills_html += _pill("Yield", f"{div:.1f}%", cls)

        if de is not None:
            cls = "good" if de < 0.5 else "warn" if de < 1.5 else "bad"
            pills_html += _pill("D/E", f"{de:.1f}x", cls)

        pct = _f(inst.get("pct_from_high"))
        if pct is not None and pct < -5:
            cls = "good" if pct < -20 else "warn" if pct < -10 else ""
            pills_html += _pill("vs 52w high", f"{pct:.1f}%", cls)

    elif ac == "ETF":
        ter = _f(inst.get("ter"))
        aum = _f(inst.get("aum"))
        ret = _f(inst.get("yr1_pct"))
        div = _f(inst.get("div_yield"))

        if ter is not None:
            cls = "good" if ter < 0.002 else "warn" if ter < 0.004 else "bad"
            pills_html += _pill("TER", f"{ter*100:.2f}%", cls)
        if aum is not None:
            cls = "good" if aum >= 2e9 else "warn" if aum >= 500e6 else "bad"
            pills_html += _pill("AUM", _fmt_aum(aum), cls)
        if ret is not None:
            cls = "good" if ret > 8 else "bad" if ret < 0 else ""
            pills_html += _pill("1yr return", _fmt_pct(ret), cls)
        if div and div > 0:
            pills_html += _pill("Yield", f"{div:.1f}%")

    elif ac == "Money Market":
        div = _f(inst.get("div_yield"))
        ter = _f(inst.get("ter"))
        aum = _f(inst.get("aum"))
        # ter is decimal (e.g. 0.002), div_yield is % (e.g. 3.5)
        net = (div - ter * 100) if (div is not None and ter is not None) else div

        if net is not None:
            cls = "good" if net >= 4 else "warn" if net >= 2.5 else "bad"
            pills_html += _pill("Net yield", f"{net:.1f}%", cls)
        if ter is not None:
            cls = "good" if ter < 0.001 else "warn" if ter < 0.003 else "bad"
            pills_html += _pill("TER", f"{ter*100:.2f}%", cls)
        if aum is not None:
            cls = "good" if aum >= 1e9 else "warn"
            pills_html += _pill("AUM", _fmt_aum(aum), cls)

    # ── Quality fail badge ────────────────────────────────────────────────────
    quality_badge = ""
    if not passes and ac == "Stock":
        quality_badge = '<div><span class="quality-fail">⛔ Does not pass quality filter</span></div>'

    # ── Signal badges ─────────────────────────────────────────────────────────
    badges_html = ""
    badges = inst.get("signal_badges", [])
    if badges:
        badge_parts = []
        for b in badges:
            col = b.get("colour", "#7986cb")
            bg  = col + "22"   # 13% opacity background
            badge_parts.append(
                f'<span class="signal-badge" style="background:{bg};color:{col};border:1px solid {col}44" '
                f'title="{b.get("detail","")}">{b.get("icon","")} {b.get("label","")}</span>'
            )
        badges_html = '<div class="signal-badge-row">' + "".join(badge_parts) + "</div>"

    # ── Score nudge note ──────────────────────────────────────────────────────
    nudge = inst.get("score_nudge", 0)
    nudge_html = ""
    if nudge and abs(nudge) >= 1 and score is not None:
        nudge_col = "#4ede8a" if nudge > 0 else "#ff9100"
        nudge_html = (f'<span style="font-size:0.7rem;color:{nudge_col};margin-left:6px">'
                      f'({nudge:+.0f} signal adj.)</span>')

    # ── Price + YTD inline ────────────────────────────────────────────────────
    price = _f(inst.get("price"))
    ytd   = _f(inst.get("ytd_pct"))

    ytd_html = ""
    if ytd is not None:
        c = "#4ede8a" if ytd > 0 else "#ff5252" if ytd < 0 else "#8890b0"
        ytd_html = f'<span style="font-size:0.75rem;color:{c};margin-left:6px">{_fmt_pct(ytd)} YTD</span>'

    price_html = ""
    if price:
        price_html = f'<span style="font-size:0.75rem;color:#8890b0">{cur}&nbsp;{price:,.2f}</span>'

    # NOTE: no leading spaces — Streamlit/CommonMark treats 4-space-indented lines as code blocks
    card_html = (
        f'<div class="card">'
        f'<div class="card-header">'
        f'<div>'
        f'<div class="card-title">{name}{ytd_html}</div>'
        f'<div class="card-sub">{ticker}  ·  {subtitle}&nbsp;&nbsp;{price_html}</div>'
        f'</div>'
        f'<div class="card-score-box" style="background:{bg}">'
        f'<div class="card-score-num" style="color:{colour}">{score_display}</div>'
        f'<div class="card-score-lbl" style="color:{colour}">{rating_label}{nudge_html}</div>'
        f'</div>'
        f'</div>'
        f'{quality_badge}'
        f'{badges_html}'
        f'<div class="card-verdict">{verdict}</div>'
        f'<div class="card-metrics">{pills_html}</div>'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    # ── Score breakdown + Watchlist actions ───────────────────────────────────
    # FIX Bug 1: stable keys using ticker string only
    action_col, breakdown_col = st.columns([2, 3])

    with action_col:
        if show_add_watchlist:
            if is_wl:
                if st.button("⭐ Remove",     key=f"rm_wl_{_ks}", use_container_width=True):
                    st.session_state.watchlist = [
                        w for w in st.session_state.watchlist if w["ticker"] != ticker
                    ]
                    _save_json("watchlist.json", st.session_state.watchlist)
                    st.session_state.toast = (f"Removed {name} from watchlist", "info")
                    st.rerun()
            else:
                if st.button("+ Watchlist",   key=f"add_wl_{_ks}", use_container_width=True):
                    entry = {
                        "ticker":           ticker,
                        "name":             name,
                        "group":            group,
                        "asset_class":      inst.get("asset_class", "Stock"),
                        "added_at":         datetime.now().strftime("%d %b %Y"),
                        "price_when_added": price,
                        "notes":            "",
                        "conviction":       "medium",
                    }
                    st.session_state.watchlist.append(entry)
                    _save_json("watchlist.json", st.session_state.watchlist)
                    # FIX UX: toast confirmation instead of silent rerun
                    st.session_state.toast = (f"{name} added to watchlist", "success")
                    st.rerun()

    with breakdown_col:
        # FIX UX: score breakdown inline per card
        if inst.get("score_components"):
            with st.expander("Score breakdown", expanded=False, key=f"bd_{_ks}"):
                _render_score_breakdown(inst)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: HOME / DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def page_home():
    _render_counter.clear()
    st.markdown("# Good to see you, Ade.")

    instruments = st.session_state.instruments
    age         = cache_age_hours()

    # ── Empty state ────────────────────────────────────────────────────────────
    if not instruments:
        st.markdown(
            '<div style="text-align:center;padding:60px 20px;color:#8890b0">'
            '<div style="font-size:3rem;margin-bottom:16px">📊</div>'
            '<div style="font-size:1.2rem;font-weight:600;color:#c8cee8;margin-bottom:8px">Welcome to your Value Screener</div>'
            '<div style="font-size:0.9rem;line-height:1.6">Select the markets you want to watch in the sidebar,<br>then click <b>Load Data</b> to get started.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Summary tiles ──────────────────────────────────────────────────────────
    ok           = [x for x in instruments if x.get("ok")]
    stocks       = [x for x in ok if x.get("asset_class") == "Stock"]
    quality_pass = [x for x in stocks if x.get("quality_passes")]
    strong_value = [x for x in ok if (_f(x.get("score")) or 0) >= 75]
    wl_count     = len(st.session_state.watchlist)
    flagged      = [x for x in ok if x.get("has_signals")]

    age_str = f"Data updated {age:.0f}h ago" if age is not None else "Loaded from cache"
    last_surv = get_last_run_time()
    surv_str  = ""
    if last_surv:
        try:
            surv_dt  = datetime.fromisoformat(last_surv)
            surv_str = f"  ·  Surveillance {surv_dt.strftime('%H:%M %d %b')}"
        except Exception:
            pass
    st.caption(f"{age_str}{surv_str}  ·  {datetime.now().strftime('%A %d %B %Y')}")
    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Macro status bar ──────────────────────────────────────────────────────
    _render_macro_bar()

    st.markdown('<div style="height:0.25rem"></div>', unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    flagged_col = "#ff9100" if flagged else "#e8eaf6"
    tiles = [
        (c1, str(len(ok)),            "Instruments screened",         "#e8eaf6"),
        (c2, str(len(strong_value)),  "Strong value signals",         "#00c853"),
        (c3, str(len(quality_pass)),  "Stocks passing quality",       "#e8eaf6"),
        (c4, str(wl_count),           "On your watchlist",            "#e8eaf6"),
        (c5, str(len(flagged)),       "Flagged by surveillance",      flagged_col),
    ]
    for col, num, lbl, num_colour in tiles:
        with col:
            st.markdown(
                f'<div class="summary-tile">'
                f'<div class="summary-number" style="color:{num_colour}">{num}</div>'
                f'<div class="summary-label">{lbl}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div style="height:1.2rem"></div>', unsafe_allow_html=True)

    # ── Changed since last scan ────────────────────────────────────────────────
    changed = get_changed_instruments(ok, min_drift=8.0)
    if changed:
        st.markdown('<div class="section-header">Changed since last scan</div>', unsafe_allow_html=True)
        lines = []
        for inst in changed[:6]:
            drift = inst.get("score_drift", 0)
            name  = inst.get("name", inst.get("ticker", ""))
            score = inst.get("score")
            arrow = "▲" if drift > 0 else "▼"
            col   = "#4ede8a" if drift > 0 else "#ff5252"
            score_str = f"{score:.0f}" if score is not None else "—"
            lines.append(
                f'<span style="margin-right:20px">'
                f'<b style="color:#c8cee8">{name}</b> '
                f'<span style="color:{col}">{arrow} {abs(drift):.0f} pts</span> '
                f'<span style="color:#555">→ {score_str}</span>'
                f'</span>'
            )
        st.markdown(
            '<div class="changed-banner">'
            + "".join(lines) +
            '</div>',
            unsafe_allow_html=True,
        )
    elif last_surv:
        st.markdown(
            '<div class="changed-banner">✓ <b>Nothing material changed</b> since last surveillance run — all clear.</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Top picks — 2 column layout ────────────────────────────────────────────
    # FIX UX: 2 columns max so cards aren't cramped
    top = sorted(
        [x for x in ok if _f(x.get("score")) is not None],
        key=lambda x: _f(x.get("score")) or 0, reverse=True
    )[:4]

    if top:
        st.markdown('<div class="section-header">Top value picks right now</div>', unsafe_allow_html=True)
        pairs = [top[i:i+2] for i in range(0, len(top), 2)]
        for pair in pairs:
            cols = st.columns(2)
            for j, inst in enumerate(pair):
                with cols[j]:
                    render_card(inst, show_add_watchlist=True)

    # ── Watchlist snapshot ─────────────────────────────────────────────────────
    if st.session_state.watchlist and instruments:
        st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)
        st.markdown('<div class="section-header">Your watchlist — latest readings</div>',
                    unsafe_allow_html=True)
        wl_tickers  = {w["ticker"] for w in st.session_state.watchlist}
        wl_insts    = [x for x in ok if x["ticker"] in wl_tickers]
        wl_sorted   = sorted(wl_insts, key=lambda x: _f(x.get("score")) or 0, reverse=True)

        pairs = [wl_sorted[:2][i:i+2] for i in range(0, len(wl_sorted[:2]), 2)]
        for pair in pairs:
            cols = st.columns(2)
            for j, inst in enumerate(pair):
                with cols[j]:
                    render_card(inst, show_add_watchlist=False)

        if len(wl_sorted) > 2:
            if st.button(f"→  See all {len(wl_sorted)} watchlist items", key="goto_wl"):
                st.session_state.page = "watchlist"
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SCREENER (Find Ideas)
# ══════════════════════════════════════════════════════════════════════════════

def page_screener():
    _render_counter.clear()
    st.markdown("# 🔍 Find Ideas")

    instruments = st.session_state.instruments
    if not instruments:
        st.info("👈  Choose your markets in the sidebar and click **Load Data** to begin.")
        return

    filtered = apply_filters(instruments, include_excluded=False)
    excluded = apply_filters(instruments, include_excluded=True)
    ok_all   = [x for x in instruments if x.get("ok")]

    # ── Stats bar ──────────────────────────────────────────────────────────────
    stocks_passing = [x for x in filtered if x.get("asset_class") == "Stock"]
    funds_passing  = [x for x in filtered if x.get("asset_class") != "Stock"]
    flagged_count  = sum(1 for x in filtered if x.get("has_signals"))
    sc1, sc2, sc3, sc4, sc5 = st.columns(5)
    sc1.metric("Showing",               len(filtered),       f"of {len(ok_all)} loaded")
    sc2.metric("Stocks (quality pass)", len(stocks_passing))
    sc3.metric("Funds / ETFs",          len(funds_passing))
    sc4.metric("Excluded (quality fail)", len(excluded),
               help="Stocks filtered out by the quality gate. Toggle below to view them.")
    sc5.metric("Flagged by surveillance", flagged_count,
               help="Instruments with active signals — news, score drift, insider buying, filings.")

    if not filtered and not excluded:
        st.warning("Nothing matches your current filters — try loosening them in the sidebar.")
        return

    # ── Flagged-only toggle ────────────────────────────────────────────────────
    if flagged_count > 0:
        flag_col, _ = st.columns([2, 3])
        with flag_col:
            flag_label = (
                f"🚨  Showing flagged only ({flagged_count})"
                if st.session_state.show_flagged_only
                else f"🚨  Show flagged only ({flagged_count})"
            )
            if st.button(flag_label, key="toggle_flagged",
                         type="primary" if st.session_state.show_flagged_only else "secondary"):
                st.session_state.show_flagged_only = not st.session_state.show_flagged_only
                st.rerun()

    # Apply flagged filter on top of existing filters
    display_list = (
        [x for x in filtered if x.get("has_signals")]
        if st.session_state.show_flagged_only
        else filtered
    )

    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Group tabs ─────────────────────────────────────────────────────────────
    groups_present = sorted({x.get("group", "") for x in display_list if x.get("group")})
    tab_labels     = ["All"] + groups_present
    tabs           = st.tabs(tab_labels)

    def render_group(insts):
        if not insts:
            st.info("Nothing here with the current filters.")
            return
        pairs = [insts[i:i+2] for i in range(0, len(insts), 2)]
        for pair in pairs:
            cols = st.columns(2)
            for j, inst in enumerate(pair):
                with cols[j]:
                    render_card(inst)

    with tabs[0]:
        render_group(display_list)
    for i, grp in enumerate(groups_present):
        with tabs[i + 1]:
            render_group([x for x in display_list if x.get("group") == grp])

    # ── FIX UX: quality-failed stocks hidden by default with toggle ────────────
    if excluded:
        st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)
        st.divider()
        toggle_label = (
            f"▼  Hide {len(excluded)} excluded stocks (failed quality filter)"
            if st.session_state.show_excluded
            else f"▶  Show {len(excluded)} excluded stocks (failed quality filter)"
        )
        if st.button(toggle_label, key="toggle_excluded"):
            st.session_state.show_excluded = not st.session_state.show_excluded
            st.rerun()

        if st.session_state.show_excluded:
            st.caption(
                "These stocks did not pass the quality gate (ROE, debt, profit margin). "
                "They are shown here for reference only — a low price alone doesn't make them attractive."
            )
            pairs = [excluded[i:i+2] for i in range(0, len(excluded), 2)]
            for pair in pairs:
                cols = st.columns(2)
                for j, inst in enumerate(pair):
                    with cols[j]:
                        render_card(inst)


# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# WATCHLIST SEARCH HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _do_watchlist_search(query: str):
    """
    Look up a ticker (or try to resolve a company name) via yfinance.
    Stores the result in st.session_state.wl_search_result.
    """
    import yfinance as yf

    # Normalise: uppercase, strip whitespace
    ticker = query.upper().strip()

    with st.spinner(f"Looking up {ticker} …"):
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            # yfinance returns an empty / minimal dict for bad tickers
            name = info.get("longName") or info.get("shortName") or info.get("name")
            if not name:
                # Nothing useful — try treating query as a name search via yfinance Search API
                # (available in yfinance >= 0.2.x; degrade gracefully on older versions)
                try:
                    results = yf.Search(query, max_results=5)
                    quotes = getattr(results, "quotes", []) or []
                    if quotes:
                        best = quotes[0]
                        ticker = best.get("symbol", ticker)
                        name   = best.get("longname") or best.get("shortname") or ticker
                        t      = yf.Ticker(ticker)
                        info   = t.info or {}
                except (AttributeError, Exception):
                    pass  # yf.Search not available — fall through to not_found

            if not name:
                st.session_state.wl_search_result = "not_found"
                return

            # Determine asset class heuristically
            qt = info.get("quoteType", "").upper()
            if qt in ("ETF", "MUTUALFUND"):
                asset_class = "ETF"
            elif qt == "EQUITY":
                asset_class = "Stock"
            else:
                asset_class = qt.title() or "Unknown"

            # Determine group
            exchange = info.get("exchange", "")
            currency = info.get("currency", "")
            if ticker.endswith(".L"):
                group = "🇬🇧 UK Stocks"
            elif ticker.endswith((".DE", ".PA", ".AS", ".MC", ".MI", ".SW",
                                   ".ST", ".CO", ".HE", ".OL")):
                group = "🇪🇺 EU Stocks"
            elif asset_class == "ETF":
                group = "📦 ETFs & Index Funds"
            else:
                group = "🇺🇸 US Stocks"

            from data.fetcher import _float as _ff
            div_raw = _ff(info.get("dividendYield"))
            if div_raw is None:
                div_yield = None
            elif div_raw > 1.0:
                div_yield = round(min(div_raw, 99.0), 2)
            else:
                div_yield = round(div_raw * 100, 2)

            hist = t.history(period="1y")
            price    = _ff(hist["Close"].iloc[-1])  if not hist.empty else None
            high_52w = _ff(hist["Close"].max())     if not hist.empty else None
            low_52w  = _ff(hist["Close"].min())     if not hist.empty else None
            yr1_ret  = None
            if not hist.empty and len(hist) > 10:
                yr1_ret = round((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 1)

            result = {
                "ticker":      ticker,
                "name":        name,
                "asset_class": asset_class,
                "group":       group,
                "sector":      info.get("sector") or info.get("fundFamily") or "—",
                "industry":    info.get("industry", "—"),
                "currency":    currency,
                "exchange":    exchange,
                "price":       round(price, 2) if price else None,
                "high_52w":    round(high_52w, 2) if high_52w else None,
                "low_52w":     round(low_52w, 2)  if low_52w  else None,
                "yr1_pct":     yr1_ret,
                "pe":          _ff(info.get("trailingPE")),
                "pb":          _ff(info.get("priceToBook")),
                "div_yield":   div_yield,
                "market_cap":  _ff(info.get("marketCap")),
                "ok":          True,
            }
            st.session_state.wl_search_result = result

        except Exception as exc:
            st.session_state.wl_search_result = f"error:{exc}"


def _render_search_result():
    """Render the search result card with an Add to Watchlist button."""
    result = st.session_state.wl_search_result

    if result == "not_found":
        st.warning("No instrument found for that query. Try the exact ticker symbol (e.g. AAPL, HSBA.L).")
        if st.button("Clear", key="wl_sr_clear_notfound"):
            st.session_state.wl_search_result = None
            st.rerun()
        return

    if isinstance(result, str) and result.startswith("error:"):
        st.error(f"Lookup failed: {result[6:]}. Please check the ticker and try again.")
        if st.button("Clear", key="wl_sr_clear_error"):
            st.session_state.wl_search_result = None
            st.rerun()
        return

    if not isinstance(result, dict):
        return

    ticker    = result["ticker"]
    name      = result["name"]
    currency  = result.get("currency", "")
    price     = _f(result.get("price"))
    pe        = _f(result.get("pe"))
    pb        = _f(result.get("pb"))
    div_yield = _f(result.get("div_yield"))
    yr1_ret   = _f(result.get("yr1_pct"))
    sector    = result.get("sector", "—")
    group     = result.get("group", "—")
    mktcap    = _f(result.get("market_cap"))

    already_in_wl = ticker in {w["ticker"] for w in st.session_state.watchlist}

    pe_span    = (f'<span><b style="color:#c8cee8">P/E</b> {pe:.1f}x</span>' if pe else '')
    pb_span    = (f'<span><b style="color:#c8cee8">P/B</b> {pb:.1f}x</span>' if pb else '')
    yield_span = (f'<span><b style="color:#c8cee8">Yield</b> {div_yield:.2f}%</span>' if div_yield else '')
    ret_span   = (f'<span><b style="color:#c8cee8">1yr</b> {_fmt_pct(yr1_ret)}</span>' if yr1_ret is not None else '')
    cap_span   = (f'<span><b style="color:#c8cee8">Mkt cap</b> {_fmt_aum(mktcap)}</span>' if mktcap else '')
    price_disp = _fmt_price(price, currency + ' ') if price else '—'
    st.markdown(
        f'<div style="background:#1a1f35;border:1px solid #3a4060;border-radius:10px;padding:16px 20px;margin-bottom:12px">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
        f'<div>'
        f'<span style="font-size:1.1rem;font-weight:700;color:#e8eaf6">{name}</span>'
        f'<span style="font-size:0.85rem;color:#8890b0;margin-left:10px">{ticker}</span>'
        f'<span style="font-size:0.75rem;background:#2a3050;color:#9095c0;border-radius:4px;padding:2px 7px;margin-left:8px">{group}</span>'
        f'</div>'
        f'<div style="font-size:1.1rem;font-weight:600;color:#c8cee8">{price_disp}</div>'
        f'</div>'
        f'<div style="margin-top:10px;display:flex;gap:18px;flex-wrap:wrap;font-size:0.82rem;color:#9095b0">'
        f'<span><b style="color:#c8cee8">Sector</b> {sector}</span>'
        f'{pe_span}{pb_span}{yield_span}{ret_span}{cap_span}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    act_c1, act_c2, _ = st.columns([2, 2, 4])
    with act_c1:
        if already_in_wl:
            st.success(f"✓ Already on watchlist")
        else:
            if st.button(f"⭐ Add {ticker} to watchlist", key="wl_sr_add", use_container_width=True):
                entry = {
                    "ticker":           ticker,
                    "name":             name,
                    "group":            group,
                    "asset_class":      result.get("asset_class", "Stock"),
                    "price_when_added": price,
                    "added_at":         datetime.now().strftime("%Y-%m-%d"),
                    "notes":            "",
                }
                st.session_state.watchlist.append(entry)
                _save_json("watchlist.json", st.session_state.watchlist)
                st.session_state.toast = (f"{name} added to watchlist", "success")
                st.session_state.wl_search_result = None
                st.rerun()
    with act_c2:
        if st.button("✕ Clear result", key="wl_sr_clear", use_container_width=True):
            st.session_state.wl_search_result = None
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# DEEP ANALYSIS RENDERER
# ══════════════════════════════════════════════════════════════════════════════

_NO_RISKS_HTML = '<span style="color:#555">No specific risks identified</span>'


def _render_deep_analysis(inst: dict):
    """
    Render the full deep analysis section inside a watchlist expander.
    Handles: cached result display, run/re-run controls, extra-context input.
    """
    ticker = inst["ticker"]
    name   = inst.get("name", ticker)

    # ── Colour helpers ────────────────────────────────────────────────────────
    def _score_col(s, mx):
        pct = s / mx if mx else 0
        if pct >= 0.8: return "#00c853"
        if pct >= 0.6: return "#ffd600"
        if pct >= 0.4: return "#ff9100"
        return "#ff1744"

    def _rating_col(r):
        r = (r or "").lower()
        if "exceptional" in r: return "#00c853"
        if "strong"      in r: return "#ffd600"
        if "moderate"    in r: return "#ff9100"
        return "#ff1744"

    def _conf_icon(c):
        c = (c or "").lower()
        if "high"   in c: return "●●●"
        if "medium" in c: return "●●○"
        return "●○○"

    def _bar(score, max_score, colour):
        pct = max(0, min(score / max_score * 100, 100)) if max_score else 0
        return (
            f'<div class="da-bar-bg">'
            f'<div class="da-bar-fill" style="width:{pct:.0f}%;background:{colour}"></div>'
            f'</div>'
        )

    # ── Component renderer ────────────────────────────────────────────────────
    def _render_component(title, section, max_score, keys_maxes):
        """Render one scoring section as a block."""
        total  = section.get("total", 0)
        just   = section.get("justification", "")
        col    = _score_col(total, max_score)

        rows = ""
        for label, sub_key, sub_max in keys_maxes:
            val = section.get(sub_key, 0) or 0
            sc  = _score_col(val, sub_max)
            rows += (
                f'<div class="da-component-row">'
                f'<span style="min-width:160px">{label}</span>'
                f'{_bar(val, sub_max, sc)}'
                f'<span style="min-width:50px;text-align:right;color:{sc}">{val}/{sub_max}</span>'
                f'</div>'
            )

        just_html = f'<div class="da-just">{just}</div>' if just else ""

        st.markdown(
            f'<div class="da-section">'
            f'<div class="da-section-title">{title}'
            f'  <span style="float:right;color:{col};font-size:1rem;font-weight:800">{total}/{max_score}</span>'
            f'</div>'
            f'{rows}'
            f'{just_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── Check for cached result ───────────────────────────────────────────────
    cached = load_cached_analysis(ticker)
    age    = cache_age_days(ticker)

    st.markdown("---")
    st.markdown("#### 🔬 Deep Analysis")

    # Status line
    if cached:
        age_str = f"{age:.1f} days ago" if age is not None else "recently"
        st.caption(f"Last analysed {age_str} · {cached.get('confidence','—')} confidence · Scores reflect data available at time of analysis")
    else:
        st.caption("No analysis run yet. Add any extra context below, then click Analyse.")

    # Extra-context input
    extra_key = f"da_extra_{ticker}"
    extra_val = st.session_state.da_extra.get(ticker, "")
    new_extra = st.text_area(
        "Extra context (optional)",
        value=extra_val,
        key=extra_key,
        height=100,
        placeholder=(
            "Paste earnings transcript excerpts, recent news, management commentary, "
            "analyst notes, or your own observations here. Leave blank to analyse on "
            "quantitative data alone."
        ),
        label_visibility="collapsed",
    )
    if new_extra != extra_val:
        st.session_state.da_extra[ticker] = new_extra

    # Run controls
    btn_c1, btn_c2, _ = st.columns([2, 2, 4])
    with btn_c1:
        run_label = "🔬 Re-analyse" if cached else "🔬 Analyse"
        run_clicked = st.button(run_label, key=f"da_run_{ticker}", use_container_width=True,
                                type="primary")
    with btn_c2:
        if cached and st.button("🗑 Clear analysis", key=f"da_clear_{ticker}",
                                use_container_width=True):
            try:
                from utils.deep_analysis import _cache_file
                _cache_file(ticker).unlink(missing_ok=True)
            except Exception:
                pass
            st.session_state.toast = ("Analysis cleared", "info")
            st.rerun()

    # ── Run analysis ──────────────────────────────────────────────────────────
    if run_clicked:
        extra = st.session_state.da_extra.get(ticker, "")
        with st.spinner(f"Analysing {name} — this takes 15–30 seconds …"):
            try:
                cached = run_deep_analysis(inst, extra_context=extra)
                st.session_state.toast = (f"Deep analysis complete for {name}", "success")
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
                return
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return

    if not cached:
        return

    # ── Render the result ─────────────────────────────────────────────────────
    overall = cached.get("overall_score", 0)
    rating  = cached.get("final_assessment", {}).get("rating", "—")
    conf    = cached.get("confidence", "—")
    rat_col = _rating_col(rating)
    ov_col  = _score_col(overall, 100)

    # Header: big score + rating badge
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:16px;margin:12px 0 8px 0">'
        f'<div class="da-score-big" style="color:{ov_col}">{overall}</div>'
        f'<div>'
        f'<span class="da-rating" style="background:{rat_col}22;color:{rat_col};border:1px solid {rat_col}44">'
        f'{rating}</span>'
        f'<span class="da-confidence"> {_conf_icon(conf)} {conf} confidence</span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Summary
    summary = cached.get("final_assessment", {}).get("summary", "")
    if summary:
        st.markdown(
            f'<div style="font-size:0.85rem;color:#c8cee8;line-height:1.6;'
            f'margin-bottom:12px;padding:12px 14px;background:#161926;'
            f'border-radius:8px;border-left:3px solid {rat_col}">{summary}</div>',
            unsafe_allow_html=True,
        )

    # Five scoring components
    col_a, col_b = st.columns(2)
    with col_a:
        _render_component("Competitive Moat", cached.get("moat", {}), 25, [
            ("Type & Strength",  "type_strength", 10),
            ("Durability",       "durability",    10),
            ("Evidence",         "evidence",       5),
        ])
        _render_component("Business Quality", cached.get("business_quality", {}), 15, [
            ("Revenue quality",  "revenue_quality", 10),
            ("Growth quality",   "growth_quality",   5),
        ])
        _render_component("Financial Strength", cached.get("financial_strength", {}), 15, [
            ("Balance sheet",    "balance_sheet",      5),
            ("Cash flow",        "cash_flow",           5),
            ("Returns on capital","returns_on_capital", 5),
        ])
    with col_b:
        _render_component("Management", cached.get("management", {}), 15, [
            ("Capital allocation","capital_allocation", 7),
            ("Communication",    "communication",       4),
            ("Alignment",        "alignment",           4),
        ])
        _render_component("Valuation", cached.get("valuation", {}), 20, [
            ("Discount to value","discount_to_value",  15),
            ("Downside protection","downside_protection", 5),
        ])

        # Risk factors
        risk   = cached.get("risk_factors", {})
        r_sc   = risk.get("score", 0)
        r_col  = _score_col(r_sc, 10)
        r_tags = "".join(
            f'<span class="da-risk-tag">{r}</span>'
            for r in (risk.get("key_risks") or [])
        )
        st.markdown(
            f'<div class="da-section">'
            f'<div class="da-section-title">Risk Factors'
            f'  <span style="float:right;color:{r_col};font-size:1rem;font-weight:800">{r_sc}/10</span>'
            f'</div>'
            f'<div style="margin-top:6px">{r_tags if r_tags else _NO_RISKS_HTML}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Key drivers + failure modes
    fa = cached.get("final_assessment", {})
    drivers = fa.get("key_drivers", [])
    failures = fa.get("failure_modes", [])

    if drivers or failures:
        fd_c1, fd_c2 = st.columns(2)
        with fd_c1:
            if drivers:
                tags = "".join(f'<span class="da-driver-tag">{d}</span>' for d in drivers)
                st.markdown(
                    f'<div class="da-section"><div class="da-section-title">Key Drivers</div>'
                    f'<div style="margin-top:6px">{tags}</div></div>',
                    unsafe_allow_html=True,
                )
        with fd_c2:
            if failures:
                tags = "".join(f'<span class="da-risk-tag">{f}</span>' for f in failures)
                st.markdown(
                    f'<div class="da-section"><div class="da-section-title">Failure Modes</div>'
                    f'<div style="margin-top:6px">{tags}</div></div>',
                    unsafe_allow_html=True,
                )


# SINGLE-TICKER REFRESH HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _refresh_single_ticker(wl_entry: dict):
    """
    Force-fetch fresh data for one ticker, score it, and splice the result
    back into st.session_state.instruments. Works even if the ticker wasn't
    previously in the loaded instruments (e.g. added via search to a group
    that hasn't been bulk-loaded).
    """
    ticker     = wl_entry["ticker"]
    name       = wl_entry.get("name", ticker)
    group      = wl_entry.get("group", "🇺🇸 US Stocks")
    asset_class = wl_entry.get("asset_class")

    # Infer asset_class from group if not stored on the entry
    if not asset_class:
        for g, meta in UNIVERSE.items():
            if g == group:
                asset_class = meta["asset_class"]
                break
        if not asset_class:
            if "ETF" in group or "Index" in group:
                asset_class = "ETF"
            elif "Money" in group:
                asset_class = "Money Market"
            else:
                asset_class = "Stock"

    with st.spinner(f"Fetching live data for {ticker} …"):
        raw = fetch_one(ticker, name, asset_class, group, force_refresh=True)

    if not raw.get("ok"):
        st.error(f"Could not fetch data for {ticker}: {raw.get('error', 'unknown error')}")
        return

    # Score this single instrument using current settings
    sm = st.session_state.sector_medians or {}
    qt = _build_quality_thresholds()
    sw = _build_scoring_weights()

    from utils.scoring import score_instrument
    scored = score_instrument(raw, sm, qt, sw)

    # Add verdicts for this one instrument
    from utils.verdicts import add_verdicts
    scored_list = add_verdicts([scored], sm)
    scored = scored_list[0] if scored_list else scored

    # Signal enrichment (reads from cache — fast)
    from utils.signal_enricher import enrich_with_signals
    enriched_list = enrich_with_signals([scored])
    scored = enriched_list[0] if enriched_list else scored

    # Splice back into session instruments — replace if exists, append if new
    existing = st.session_state.instruments
    updated  = [inst for inst in existing if inst["ticker"] != ticker]
    updated.append(scored)
    st.session_state.instruments = updated

    # Also update sector medians if this is a new stock sector
    if asset_class == "Stock" and raw.get("sector"):
        from data.fetcher import compute_sector_medians
        st.session_state.sector_medians = compute_sector_medians(
            [i for i in updated if i.get("ok")]
        )

    st.session_state.toast = (f"{name} refreshed with live data", "success")


# PAGE: WATCHLIST (My Holdings)
# ══════════════════════════════════════════════════════════════════════════════

def page_watchlist():
    _render_counter.clear()
    st.markdown("# ⭐ My Holdings & Watchlist")

    # ── Search & Add any instrument ───────────────────────────────────────────
    st.markdown("### 🔍 Search & Add Any Instrument")
    st.caption("Enter any ticker symbol (e.g. NVDA, HSBA.L, SIE.DE) or a company name to look it up and add it to your watchlist.")

    search_col, btn_col = st.columns([4, 1])
    with search_col:
        search_query = st.text_input(
            "Ticker or company name",
            key="wl_search_input",
            placeholder="e.g. AAPL, TSLA, HSBA.L, SIE.DE …",
            label_visibility="collapsed",
        )
    with btn_col:
        search_clicked = st.button("Search", key="wl_search_btn", use_container_width=True)

    if search_clicked and search_query.strip():
        _do_watchlist_search(search_query.strip())

    # Show pending search result if one exists
    if st.session_state.get("wl_search_result"):
        _render_search_result()

    st.markdown("---")

    watchlist = st.session_state.watchlist
    if not watchlist:
        st.markdown(
            '<div style="text-align:center;padding:40px 20px;color:#8890b0">'
            '<div style="font-size:2rem;margin-bottom:12px">⭐</div>'
            '<div style="font-size:1rem;color:#c8cee8;margin-bottom:6px">Your watchlist is empty</div>'
            '<div style="font-size:0.85rem">Use <b>Search</b> above to find any stock, ETF, or fund and add it here. '
            'Or go to <b>Find Ideas</b> and click <b>+ Watchlist</b> on any instrument.</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    instruments = st.session_state.instruments
    wl_tickers  = {w["ticker"]: w for w in watchlist}
    live_data   = {
        x["ticker"]: x
        for x in instruments
        if x.get("ok") and x["ticker"] in wl_tickers
    }

    # FIX UX: improved missing-data message tells user exactly what to do
    missing = [t for t in wl_tickers if t not in live_data]
    if missing:
        missing_groups = {wl_tickers[t].get("group", "that market") for t in missing}
        st.info(
            f"{len(missing)} watchlist item(s) have no live data. "
            f"To see them, load **{', '.join(missing_groups)}** from the sidebar."
        )

    for wl_entry in watchlist:
        ticker      = wl_entry["ticker"]
        added_price = _f(wl_entry.get("price_when_added"))

        if ticker not in live_data:
            with st.expander(f"{wl_entry.get('name', ticker)} ({ticker}) — no data loaded",
                             expanded=False):
                st.caption(f"Load {wl_entry.get('group', 'the relevant market')} in the sidebar to see all holdings, or fetch this one individually:")
                miss_c1, miss_c2 = st.columns([2, 2])
                with miss_c1:
                    if st.button("🔄 Fetch now", key=f"refresh_miss_{ticker}",
                                 use_container_width=True,
                                 help="Fetch live data for this ticker only — no full reload needed"):
                        _refresh_single_ticker(wl_entry)
                        st.rerun()
                with miss_c2:
                    if st.button("Remove", key=f"rmwl_miss_{ticker}", use_container_width=True):
                        st.session_state.watchlist = [
                            w for w in st.session_state.watchlist if w["ticker"] != ticker
                        ]
                        _save_json("watchlist.json", st.session_state.watchlist)
                        st.rerun()
            continue

        inst   = live_data[ticker]
        score  = _f(inst.get("score"))
        label  = score_label(score) if inst.get("quality_passes", True) else "Not scored"
        price  = _f(inst.get("price"))

        change_str = ""
        if price and added_price and added_price > 0:
            chg    = (price / added_price - 1) * 100
            sign   = "+" if chg > 0 else ""
            colour = "#4ede8a" if chg > 0 else "#ff5252"
            change_str = (
                f'<span style="color:{colour};font-weight:600">'
                f'{sign}{chg:.1f}% since added</span>'
            )

        header = (
            f"{inst['name']} ({ticker})  ·  {score:.0f}/100 — {label}"
            if score is not None
            else f"{inst['name']} ({ticker})"
        )

        with st.expander(header, expanded=False):
            render_card(inst, show_add_watchlist=False)

            mc1, mc2, mc3 = st.columns(3)
            mc1.markdown(f"**Added:** {wl_entry.get('added_at', '—')}")
            if added_price:
                mc2.markdown(
                    f"**Price when added:** {inst.get('currency','')} {added_price:,.2f}"
                )
            if change_str:
                mc3.markdown(change_str, unsafe_allow_html=True)

            notes = st.text_area(
                "Notes",
                value=wl_entry.get("notes", ""),
                key=f"notes_{ticker}",
                label_visibility="collapsed",
                placeholder="Add your research notes here…",
            )
            if notes != wl_entry.get("notes", ""):
                for w in st.session_state.watchlist:
                    if w["ticker"] == ticker:
                        w["notes"] = notes
                _save_json("watchlist.json", st.session_state.watchlist)

            btn_c1, btn_c2 = st.columns([2, 2])
            with btn_c1:
                if st.button("🔄 Refresh data", key=f"refresh_{ticker}",
                             use_container_width=True,
                             help="Pull fresh data from Yahoo Finance for this stock only"):
                    _refresh_single_ticker(wl_entry)
                    st.rerun()
            with btn_c2:
                if st.button("Remove from watchlist", key=f"rm_{ticker}",
                             use_container_width=True):
                    st.session_state.watchlist = [
                        w for w in st.session_state.watchlist if w["ticker"] != ticker
                    ]
                    _save_json("watchlist.json", st.session_state.watchlist)
                    st.session_state.toast = (f"Removed {inst['name']} from watchlist", "info")
                    st.rerun()

            # Deep qualitative analysis
            _render_deep_analysis(inst)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: COMPARE
# ══════════════════════════════════════════════════════════════════════════════

def page_compare():
    _render_counter.clear()
    st.markdown("# 📈 Compare")

    instruments = st.session_state.instruments
    if not instruments:
        st.info("👈  Load data from the sidebar first.")
        return

    ok      = [x for x in instruments if x.get("ok")]
    options = {f"{x['ticker']}  —  {x['name']}": x for x in ok}

    # FIX UX: pre-populate with top 2 watchlist items if available
    wl_tickers = [w["ticker"] for w in st.session_state.watchlist]
    default_labels = [
        lbl for lbl in options
        if lbl.split("  —  ")[0].strip() in wl_tickers
    ][:2]

    selected_labels = st.multiselect(
        "Pick 2–4 instruments to compare",
        list(options.keys()),
        default=default_labels,
        max_selections=4,
        placeholder="Type a name or ticker to search…",
    )

    if len(selected_labels) < 2:
        st.info("Select at least 2 instruments above to compare them side by side.")
        return

    selected = [options[lbl] for lbl in selected_labels]

    # Verdict cards side by side
    cols = st.columns(len(selected))
    for i, inst in enumerate(selected):
        with cols[i]:
            render_card(inst, show_add_watchlist=True)

    st.divider()
    st.markdown("#### Detailed metrics")

    def _roe_fmt(inst):
        v = _f(inst.get("roe"))
        return f"{v*100:.1f}%" if v is not None else "—"

    def _pm_fmt(inst):
        v = _f(inst.get("profit_margin"))
        return f"{v*100:.1f}%" if v is not None else "—"

    def _ter_fmt(inst):
        v = _f(inst.get("ter"))
        return f"{v*100:.2f}%" if v is not None else "—"

    def row(label, fn):
        data = {"Metric": label}
        for inst in selected:
            try:
                data[inst["ticker"]] = fn(inst)
            except Exception:
                data[inst["ticker"]] = "—"
        return data

    rows = [
        row("Price",             lambda i: _fmt_price(_f(i.get("price")), i.get("currency","")+" ")),
        row("YTD return",        lambda i: _fmt_pct(_f(i.get("ytd_pct")))),
        row("1yr return",        lambda i: _fmt_pct(_f(i.get("yr1_pct")))),
        row("vs 52-week high",   lambda i: _fmt_pct(_f(i.get("pct_from_high")))),
        row("Dividend / yield",  lambda i: f"{_f(i.get('div_yield')):.1f}%" if _f(i.get('div_yield')) is not None else "—"),
        row("P/E ratio",         lambda i: _fmt_ratio(_f(i.get("pe")))),
        row("P/B ratio",         lambda i: _fmt_ratio(_f(i.get("pb")))),
        row("EV/EBITDA",         lambda i: _fmt_ratio(_f(i.get("ev_ebitda")))),
        row("Return on Equity",  _roe_fmt),
        row("Profit margin",     _pm_fmt),
        row("Debt / Equity",     lambda i: _fmt_ratio(_f(i.get("debt_equity")))),
        row("Fund cost (TER)",   _ter_fmt),
        row("Fund size (AUM)",   lambda i: _fmt_aum(_f(i.get("aum")))),
        row("Sector",            lambda i: i.get("sector", "—")),
        row("Quality gate",      lambda i: "✅ Pass" if i.get("quality_passes") else ("❌ Fail" if i.get("asset_class")=="Stock" else "N/A")),
        row("Value score",       lambda i: f"{_f(i.get('score')):.0f}/100" if _f(i.get("score")) is not None else "—"),
    ]

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=560)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def _severity_colour(sev: str) -> str:
    return {"high": "#ff5252", "medium": "#ffb74d", "low": "#4ede8a", "info": "#7986cb"}.get(sev, "#888")

def _severity_icon(sev: str) -> str:
    return {"high": "🔴", "medium": "🟡", "low": "🟢", "info": "🔵"}.get(sev, "⚪")

def _type_label(t: str) -> str:
    return {
        "score_drift":      "Score Change",
        "value_opportunity":"Value Signal",
        "near_52w_low":     "Price Alert",
        "macro_warning":    "Macro Risk",
        "macro_positive":   "Macro Tailwind",
        "macro_info":       "Macro Context",
        "news_negative":    "Negative News",
        "news_positive":    "Positive News",
        "insider_buying":   "Insider Buy",
        "material_event":   "SEC Filing",
    }.get(t, t.replace("_", " ").title())


def page_signals():
    st.markdown("# 🚨 Signals & Alerts")

    signals = load_latest_signals()
    last_run = get_last_run_time()

    # ── Run surveillance button ────────────────────────────────────────────────
    col_title, col_btn = st.columns([3, 1])
    with col_title:
        if last_run:
            try:
                dt = datetime.fromisoformat(last_run)
                st.caption(f"Last surveillance run: {dt.strftime('%a %d %b %Y, %H:%M')}")
            except Exception:
                st.caption(f"Last run: {last_run}")
        else:
            st.caption("No surveillance run yet. Click Run Surveillance to generate signals.")

    with col_btn:
        if st.button("▶  Run Surveillance", type="primary", use_container_width=True,
                     key="run_surv_btn"):
            with st.spinner("Running surveillance — this takes 2–5 minutes on first run…"):
                try:
                    import sys
                    sys.path.insert(0, str(Path(__file__).parent))
                    from surveillance.run_surveillance import run as _run_surveillance
                    briefing = _run_surveillance(force=False, verbose=False)
                    st.session_state.toast = (
                        f"Surveillance complete — {len(load_latest_signals())} signals generated",
                        "success"
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Surveillance error: {e}")

    if not signals:
        st.info("""
        **No signals yet.**  Click **▶ Run Surveillance** above to:
        - Fetch macro data (FRED, BoE)
        - Pull RSS headlines and score sentiment
        - Check SEC insider transactions
        - Compare scores against your last scan
        """)
        return

    # ── Summary pills ──────────────────────────────────────────────────────────
    summary = signals_summary(signals)
    counts  = summary.get("counts", {})
    s1, s2, s3, s4 = st.columns(4)
    for col, sev, label in [
        (s1, "high",   "High Priority"),
        (s2, "medium", "Medium"),
        (s3, "low",    "Low / Positive"),
        (s4, "info",   "Informational"),
    ]:
        n = counts.get(sev, 0)
        col.markdown(
            f'<div class="summary-tile">'
            f'<div class="summary-number" style="color:{_severity_colour(sev)}">{n}</div>'
            f'<div class="summary-label">{label}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)

    # ── Filter by severity ─────────────────────────────────────────────────────
    filter_sev = st.radio(
        "Filter by severity",
        ["All", "High only", "High + Medium"],
        horizontal=True, label_visibility="collapsed",
        key="sig_filter",
    )
    filtered_signals = signals
    if filter_sev == "High only":
        filtered_signals = [s for s in signals if s.get("severity") == "high"]
    elif filter_sev == "High + Medium":
        filtered_signals = [s for s in signals if s.get("severity") in ("high", "medium")]

    if not filtered_signals:
        st.info("No signals at this severity level.")
        return

    st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)

    # ── Signal cards ───────────────────────────────────────────────────────────
    for sig in filtered_signals:
        sev    = sig.get("severity", "info")
        stype  = sig.get("type", "")
        ticker = sig.get("ticker", "")
        col    = _severity_colour(sev)
        icon   = _severity_icon(sev)
        type_lbl = _type_label(stype)

        source_str = f" · {sig['source']}" if sig.get("source") else ""
        ticker_str = f" · {ticker}" if ticker else ""

        st.markdown(
            f'<div class="card" style="border-left:4px solid {col}">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div>'
            f'<div class="card-title">{icon} {sig.get("title","")}</div>'
            f'<div class="card-sub">{type_lbl}{ticker_str}{source_str}</div>'
            f'</div>'
            f'<div style="background:{col}22;border-radius:6px;padding:4px 10px;font-size:0.72rem;color:{col};white-space:nowrap">'
            f'{sev.upper()}'
            f'</div>'
            f'</div>'
            f'<div class="card-verdict" style="margin-top:10px">{sig.get("detail","")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # Link to filing if available
        if sig.get("url"):
            st.markdown(f"[View filing →]({sig['url']})", unsafe_allow_html=False)

    st.caption(f"Showing {len(filtered_signals)} of {len(signals)} total signals")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: BRIEFING
# ══════════════════════════════════════════════════════════════════════════════

def page_briefing():
    st.markdown("# 📰 Morning Briefing")

    briefing = load_briefing()

    col_title, col_btn = st.columns([3, 1])
    with col_btn:
        if st.button("▶  Generate Briefing", type="primary", use_container_width=True,
                     key="gen_briefing_btn"):
            with st.spinner("Running full surveillance and generating briefing…"):
                try:
                    from surveillance.run_surveillance import run as _run_surveillance
                    _run_surveillance(force=False, verbose=False)
                    briefing = load_briefing()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    if not briefing:
        with col_title:
            st.caption("No briefing generated yet.")
        st.info("""
        **Your morning briefing will appear here** — a plain-English market summary covering:
        - 📊 Macro backdrop (rates, yield curve, VIX, credit spreads)
        - ⭐ Top value opportunities from your screener
        - 👁️ Your watchlist at a glance
        - 📰 Market-moving headlines
        - 🚨 Alerts requiring attention

        Click **Generate Briefing** to run the surveillance engine.
        """)
        return

    with col_title:
        st.caption(f"Generated: {briefing.get('date_str', '')}")

    # ── Headline ───────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:#161926;border:1px solid #2a2f45;border-radius:10px;'
        f'padding:18px 20px;margin-bottom:16px;font-size:1rem;color:#c8cee8;line-height:1.6">'
        f'<b>Today\'s Summary</b><br>{briefing.get("headline","")}</div>',
        unsafe_allow_html=True,
    )

    # ── Macro section ──────────────────────────────────────────────────────────
    macro = briefing.get("macro", {})
    tone  = macro.get("tone", "mixed")
    tone_colours = {"constructive": "#4ede8a", "mixed": "#ffb74d", "cautious": "#ff5252"}
    tone_col = tone_colours.get(tone, "#888")

    with st.expander(f"📊 Macro — {tone.title()} backdrop", expanded=True):
        st.markdown(
            f'<div style="color:{tone_col};margin-bottom:8px">{macro.get("tone_detail","")}</div>',
            unsafe_allow_html=True,
        )
        metrics = macro.get("metrics", [])
        if metrics:
            n_cols = min(3, len(metrics))
            cols = st.columns(n_cols)
            for i, metric_str in enumerate(metrics):
                if ":" in metric_str:
                    lbl, val = metric_str.split(":", 1)
                    cols[i % n_cols].metric(lbl.strip(), val.strip())

    # ── High-priority signals ──────────────────────────────────────────────────
    signal_summary = briefing.get("signal_summary", {})
    high_sigs = [s for s in briefing.get("signals", []) if s.get("severity") == "high"]
    if high_sigs:
        with st.expander(f"🚨 High-priority alerts ({len(high_sigs)})", expanded=True):
            for sig in high_sigs:
                col = _severity_colour(sig.get("severity", "high"))
                st.markdown(
                    f'<div style="border-left:3px solid {col};padding:8px 12px;'
                    f'margin-bottom:8px;background:#1e2235;border-radius:4px">'
                    f'<b style="color:#e8eaf6">{sig["title"]}</b><br>'
                    f'<span style="color:#9095b0;font-size:0.85rem">{sig.get("detail","")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Top opportunities ──────────────────────────────────────────────────────
    opportunities = briefing.get("opportunities", [])
    if opportunities:
        with st.expander(f"⭐ Top value picks ({len(opportunities)})", expanded=True):
            pairs = [opportunities[i:i+2] for i in range(0, len(opportunities), 2)]
            for pair in pairs:
                cols = st.columns(2)
                for j, opp in enumerate(pair):
                    with cols[j]:
                        score_col = score_colour(_f(opp.get("score")))
                        st.markdown(
                            f'<div class="card">'
                            f'<div class="card-header">'
                            f'<div><div class="card-title">{opp.get("name","")}</div>'
                            f'<div class="card-sub">{opp.get("ticker","")} · {opp.get("group","")}</div></div>'
                            f'<div class="card-score-box" style="background:{score_bg(_f(opp.get("score")))}">'
                            f'<div class="card-score-num" style="color:{score_col}">{opp.get("score","—")}</div>'
                            f'<div class="card-score-lbl" style="color:{score_col}">{opp.get("label","")}</div>'
                            f'</div></div>'
                            f'<div class="card-verdict">{opp.get("verdict","")}</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

    # ── Watchlist ──────────────────────────────────────────────────────────────
    wl_data = briefing.get("watchlist", [])
    if wl_data:
        with st.expander(f"👁️ Your watchlist ({len(wl_data)} items)", expanded=False):
            for item in wl_data:
                score_val = _f(item.get("score"))
                score_col = score_colour(score_val) if score_val else "#888"
                ytd_str   = _fmt_pct(item.get("ytd_pct"))
                yr1_str   = _fmt_pct(item.get("yr1_pct"))
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:8px 0;'
                    f'border-bottom:1px solid #1e2235">'
                    f'<div><b style="color:#e8eaf6">{item.get("name","")}</b> '
                    f'<span style="color:#555">{item.get("ticker","")}</span></div>'
                    f'<div style="display:flex;gap:16px;align-items:center">'
                    f'<span style="color:#9095b0;font-size:0.8rem">YTD {ytd_str}</span>'
                    f'<span style="color:#9095b0;font-size:0.8rem">1Y {yr1_str}</span>'
                    f'<span style="color:{score_col};font-weight:600">{item.get("score","—")}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    # ── News highlights ────────────────────────────────────────────────────────
    news_items = briefing.get("news_highlights", [])
    if news_items:
        with st.expander(f"📰 Market headlines ({len(news_items)})", expanded=False):
            for item in news_items:
                sent = item.get("sentiment", 0)
                col  = "#4ede8a" if sent > 0.2 else "#ff5252" if sent < -0.2 else "#9095b0"
                icon = "▲" if sent > 0.2 else "▼" if sent < -0.2 else "─"
                link = item.get("link", "")
                title = item.get("title", "")
                feed  = item.get("feed", "")
                if link:
                    st.markdown(
                        f'<div style="padding:6px 0;border-bottom:1px solid #1e2235">'
                        f'<span style="color:{col}">{icon} </span>'
                        f'<a href="{link}" target="_blank" style="color:#c8cee8;text-decoration:none">{title}</a>'
                        f'<span style="color:#555;font-size:0.75rem"> · {feed}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="padding:6px 0;border-bottom:1px solid #1e2235">'
                        f'<span style="color:{col}">{icon} </span>'
                        f'<span style="color:#c8cee8">{title}</span>'
                        f'<span style="color:#555;font-size:0.75rem"> · {feed}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS (Scoring Logic)
# ══════════════════════════════════════════════════════════════════════════════

def page_settings():
    _render_counter.clear()
    st.markdown("# ⚙️ Scoring Settings")
    st.caption(
        "Adjust how instruments are scored. Changes take effect when you click "
        "**Apply & Rescore** — no data is re-fetched, scoring is instant."
    )

    p   = st.session_state.prefs
    changed = False  # tracks whether any value changed this render

    # ── Helper: weight bar visual ─────────────────────────────────────────────
    def _weight_bar(vals: list, labels: list):
        """Tiny horizontal stacked bar showing relative weight distribution."""
        total = sum(vals) or 1
        segments = ""
        colours = ["#7986cb", "#4dd0e1", "#81c784", "#ffb74d", "#f06292"]
        for i, (v, lbl) in enumerate(zip(vals, labels)):
            pct = v / total * 100
            col = colours[i % len(colours)]
            segments += (
                f'<div title="{lbl}: {pct:.0f}%" style="flex:{v};background:{col};'
                f'height:8px;min-width:2px"></div>'
            )
        st.markdown(
            f'<div style="display:flex;gap:1px;border-radius:4px;overflow:hidden;margin-bottom:4px">{segments}</div>',
            unsafe_allow_html=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1: STOCK QUALITY GATE
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("🔬 Stock Quality Gate — who gets scored", expanded=True):
        st.markdown(
            "Stocks **must pass all of these** to receive a valuation score. "
            "A cheap stock in a poor business is not a value investment — "
            "these filters enforce that principle."
        )
        st.markdown("---")

        qc1, qc2 = st.columns(2)
        with qc1:
            new_roe = st.slider(
                "Minimum Return on Equity (ROE %)",
                0, 30, int(p.get("min_roe", 10)), 1,
                help="How efficiently the business generates profit from shareholder funds. "
                     "10% is a reasonable floor for a quality business.",
            )
            new_pm = st.slider(
                "Minimum Profit Margin (%)",
                0, 20, int(p.get("min_profit_margin", 2)), 1,
                help="What percentage of revenue becomes profit. "
                     "2% is a low bar — raising it filters out thin-margin businesses.",
            )
        with qc2:
            new_de = st.slider(
                "Maximum Debt / Equity ratio",
                0, 10, int(p.get("max_de", 2)), 1,
                help="Financial leverage. 1x = manageable, 2x = moderate, 5x+ = high risk. "
                     "Banks and utilities naturally run higher — expect some to fail this.",
            )
            new_fcf = st.toggle(
                "Require positive free cash flow",
                value=p.get("require_pos_fcf", True),
                help="Free cash flow = cash the business actually generates after capital spending. "
                     "Negative FCF can indicate a business burning cash — turn off if you want "
                     "to see growth companies or capital-intensive industrials.",
            )

        if new_roe != p.get("min_roe") or new_de != p.get("max_de") \
                or new_pm != p.get("min_profit_margin") \
                or new_fcf != p.get("require_pos_fcf"):
            p["min_roe"]           = new_roe
            p["max_de"]            = new_de
            p["min_profit_margin"] = new_pm
            p["require_pos_fcf"]   = new_fcf
            changed = True

        st.caption(
            f"Current gate: ROE ≥ {new_roe}%  ·  D/E ≤ {new_de}x  ·  "
            f"Margin ≥ {new_pm}%  ·  FCF {'positive required' if new_fcf else 'not required'}"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 2: STOCK VALUATION WEIGHTS
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("📊 Stock Valuation — what matters most", expanded=True):
        st.markdown(
            "These five factors combine to produce the valuation score for stocks that "
            "pass the quality gate. Adjust the **relative importance** of each — "
            "the engine normalises them automatically so they don't need to sum to 100."
        )
        st.markdown("---")

        sc1, sc2 = st.columns(2)
        with sc1:
            new_wt_pe = st.slider(
                "P/E ratio importance",
                0, 100, p.get("wt_pe", 30), 5,
                help="Price-to-Earnings — the most widely used valuation metric. "
                     "Scored vs your sector's median P/E, not an arbitrary absolute.",
            )
            new_wt_pb = st.slider(
                "P/B ratio importance",
                0, 100, p.get("wt_pb", 20), 5,
                help="Price-to-Book — useful for asset-heavy businesses like banks and insurers. "
                     "Less meaningful for tech/service companies with few tangible assets.",
            )
            new_wt_ev = st.slider(
                "EV/EBITDA importance",
                0, 100, p.get("wt_evebitda", 20), 5,
                help="Enterprise Value / Earnings before interest, tax, depreciation. "
                     "Cuts through capital structure differences — useful for cross-border comparisons.",
            )
        with sc2:
            new_wt_dy = st.slider(
                "Dividend yield importance",
                0, 100, p.get("wt_divyield", 15), 5,
                help="Higher yield = more income return. Set to 0 if you're screening for "
                     "growth stocks that reinvest rather than pay dividends.",
            )
            new_wt_52 = st.slider(
                "Discount to 52-week high importance",
                0, 100, p.get("wt_52w", 15), 5,
                help="How far below its recent peak is the stock trading? "
                     "A contrarian signal — stocks near lows may be oversold opportunities, "
                     "but can also be falling for good reasons. Use alongside the quality gate.",
            )

        # Visual weight bar
        wvals  = [new_wt_pe, new_wt_pb, new_wt_ev, new_wt_dy, new_wt_52]
        wlabls = ["P/E", "P/B", "EV/EBITDA", "Dividend yield", "52w discount"]
        _weight_bar(wvals, wlabls)
        total_w = sum(wvals)
        if total_w == 0:
            st.warning("⚠ All weights are zero — stocks cannot be scored.")
        else:
            # Show effective percentages
            pcts = "  ·  ".join(
                f"**{l}** {v/total_w*100:.0f}%" for l, v in zip(wlabls, wvals) if v > 0
            )
            st.caption(f"Effective split: {pcts}")

        if (new_wt_pe != p.get("wt_pe") or new_wt_pb != p.get("wt_pb")
                or new_wt_ev != p.get("wt_evebitda") or new_wt_dy != p.get("wt_divyield")
                or new_wt_52 != p.get("wt_52w")):
            p["wt_pe"]       = new_wt_pe
            p["wt_pb"]       = new_wt_pb
            p["wt_evebitda"] = new_wt_ev
            p["wt_divyield"] = new_wt_dy
            p["wt_52w"]      = new_wt_52
            changed = True

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 3: ETF WEIGHTS
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("📦 ETF & Index Fund scoring weights", expanded=False):
        st.markdown(
            "ETFs are scored on four factors. The defaults prioritise fund size and low cost "
            "equally — adjust if you care more about recent performance or momentum."
        )
        st.markdown("---")

        ec1, ec2 = st.columns(2)
        with ec1:
            new_etf_aum = st.slider(
                "Fund size (AUM) importance",
                0, 100, p.get("wt_etf_aum", 35), 5,
                help="Larger funds are more liquid and less likely to be closed. "
                     "£500m–£10bn+ range is scored.",
            )
            new_etf_ter = st.slider(
                "Annual cost (TER) importance",
                0, 100, p.get("wt_etf_ter", 35), 5,
                help="Total Expense Ratio — the annual fee drag on returns. "
                     "0% = max score, 0.5%+ = min score.",
            )
        with ec2:
            new_etf_ret = st.slider(
                "1-year return importance",
                0, 100, p.get("wt_etf_ret", 20), 5,
                help="Recent performance. Lower this if you don't want past returns "
                     "to drive selection — they're not a reliable predictor.",
            )
            new_etf_mom = st.slider(
                "Price momentum importance",
                0, 100, p.get("wt_etf_mom", 10), 5,
                help="How close to 52-week high — higher = stronger trend. "
                     "Unlike stocks (contrarian), for ETFs you typically want momentum.",
            )

        evals  = [new_etf_aum, new_etf_ter, new_etf_ret, new_etf_mom]
        elbls  = ["AUM", "TER", "1yr return", "Momentum"]
        _weight_bar(evals, elbls)
        etotal = sum(evals)
        if etotal > 0:
            epcts = "  ·  ".join(f"**{l}** {v/etotal*100:.0f}%" for l, v in zip(elbls, evals) if v > 0)
            st.caption(f"Effective split: {epcts}")

        if (new_etf_aum != p.get("wt_etf_aum") or new_etf_ter != p.get("wt_etf_ter")
                or new_etf_ret != p.get("wt_etf_ret") or new_etf_mom != p.get("wt_etf_mom")):
            p["wt_etf_aum"] = new_etf_aum
            p["wt_etf_ter"] = new_etf_ter
            p["wt_etf_ret"] = new_etf_ret
            p["wt_etf_mom"] = new_etf_mom
            changed = True

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 4: MONEY MARKET WEIGHTS
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("💰 Money Market & Short Duration weights", expanded=False):
        st.markdown(
            "Money market funds are primarily about income — yield dominates. "
            "Adjust if safety (fund size) or cost (TER) matters more to you."
        )
        st.markdown("---")

        mc1, mc2, mc3 = st.columns(3)
        with mc1:
            new_mm_yield = st.slider(
                "Yield importance", 0, 100, p.get("wt_mm_yield", 60), 5,
                help="Distribution yield — the income return. Scored on 0–5% range.",
            )
        with mc2:
            new_mm_aum = st.slider(
                "Fund size importance", 0, 100, p.get("wt_mm_aum", 25), 5,
                help="Larger funds are safer and more stable. £100m–£5bn range.",
            )
        with mc3:
            new_mm_ter = st.slider(
                "Annual cost importance", 0, 100, p.get("wt_mm_ter", 15), 5,
                help="TER eats directly into your yield — important for money market funds.",
            )

        mvals = [new_mm_yield, new_mm_aum, new_mm_ter]
        mlbls = ["Yield", "Fund size", "TER"]
        _weight_bar(mvals, mlbls)
        mtotal = sum(mvals)
        if mtotal > 0:
            mpcts = "  ·  ".join(f"**{l}** {v/mtotal*100:.0f}%" for l, v in zip(mlbls, mvals) if v > 0)
            st.caption(f"Effective split: {mpcts}")

        if (new_mm_yield != p.get("wt_mm_yield") or new_mm_aum != p.get("wt_mm_aum")
                or new_mm_ter != p.get("wt_mm_ter")):
            p["wt_mm_yield"] = new_mm_yield
            p["wt_mm_aum"]   = new_mm_aum
            p["wt_mm_ter"]   = new_mm_ter
            changed = True

    # ═══════════════════════════════════════════════════════════════════════
    # APPLY BUTTON
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown("---")

    if changed:
        _save_json("prefs.json", p)
        st.session_state.scoring_changed = True

    apply_col, reset_col, _ = st.columns([2, 2, 4])

    with apply_col:
        apply_disabled = not (st.session_state.instruments)
        if st.button(
            "✅  Apply & Rescore",
            type="primary",
            use_container_width=True,
            disabled=apply_disabled,
            help="Rescore all loaded instruments with your new settings. Instant — no data fetch needed." if not apply_disabled
                 else "Load data first (sidebar) before rescoring.",
        ):
            instruments_raw = [
                {k: v for k, v in inst.items()
                 if k not in ("score", "score_components", "quality_passes",
                              "quality_reasons", "quality_flags", "data_quality",
                              "sector_relative", "verdict", "signal_badges",
                              "score_nudge", "score_adjusted", "score_drift", "has_signals")}
                for inst in st.session_state.instruments
            ]
            sm = st.session_state.sector_medians
            qt = _build_quality_thresholds()
            sw = _build_scoring_weights()
            rescored = score_all(instruments_raw, sm, qt, sw)
            rescored = add_verdicts(rescored, sm)
            rescored = enrich_with_signals(rescored)
            st.session_state.instruments    = rescored
            st.session_state.scoring_changed = False
            st.session_state.toast = ("Rescored with new settings", "success")
            st.rerun()

    with reset_col:
        if st.button("↩  Reset to defaults", use_container_width=True):
            defaults = {
                "min_roe": 10, "max_de": 2, "min_profit_margin": 2, "require_pos_fcf": True,
                "wt_pe": 30, "wt_pb": 20, "wt_evebitda": 20, "wt_divyield": 15, "wt_52w": 15,
                "wt_etf_aum": 35, "wt_etf_ter": 35, "wt_etf_ret": 20, "wt_etf_mom": 10,
                "wt_mm_yield": 60, "wt_mm_aum": 25, "wt_mm_ter": 15,
            }
            for k, v in defaults.items():
                p[k] = v
            _save_json("prefs.json", p)
            st.session_state.scoring_changed = True
            st.session_state.toast = ("Settings reset to defaults — click Apply & Rescore", "info")
            st.rerun()

    if apply_disabled:
        st.info("👈  Load data from the sidebar first, then click Apply & Rescore.")
    elif st.session_state.scoring_changed:
        st.warning("⚠ Settings changed — click **Apply & Rescore** to update scores.")
    else:
        st.success("✓ Scores are up to date with current settings.")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

page = st.session_state.page
if   page == "home":      page_home()
elif page == "screener":  page_screener()
elif page == "watchlist": page_watchlist()
elif page == "compare":   page_compare()
elif page == "signals":   page_signals()
elif page == "briefing":  page_briefing()
elif page == "settings":  page_settings()
else:
    st.session_state.page = "home"
    st.rerun()
