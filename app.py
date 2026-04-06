"""
Value Screener v3 — Personal Investment Research Tool
Quality at a fair price. UK · EU · US stocks · ETFs · Money Market funds.

Run: python3 -m streamlit run app.py
Or:  double-click "Start Value Screener.command" (Mac)
                  "Start Value Screener.bat"     (Windows)
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

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
    st.error("Required package missing. Close this window and re-run 'Start Value Screener'.")
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
from utils.helpers  import (_f, _fmt_pct, _fmt_ratio, _fmt_price, _fmt_aum)  # shared helpers
from utils.verdicts import add_verdicts
from utils.signals        import load_latest_signals, get_last_run_time, signals_summary
from utils.signal_enricher import (enrich_with_signals, get_changed_instruments,
                                    get_macro_context, get_uk_macro_context)
from surveillance.briefing import load_briefing
from utils.deep_analysis   import (run_deep_analysis, load_cached_analysis,
                                    cache_age_days, build_data_context)
from utils.news_fetcher    import (get_signals_from_news, get_market_mood,
                                    get_sector_news_for_briefing, fetch_news_for_ticker)
from user_data import (
    load_watchlist, save_watchlist, add_to_watchlist, remove_from_watchlist,
    load_holdings, save_holdings, add_to_holdings, remove_from_holdings,
    load_prefs, save_prefs,
    load_custom_tickers, add_custom_ticker, remove_custom_ticker,
    migrate_legacy_data_for_user,
)
from utils.score_history import snapshot_scores, init_history_db
init_history_db()  # ensure table exists on startup


# ══════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG & GLOBAL CSS
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Value Screener",
    page_icon=str(Path(__file__).parent / "assets" / "icon.svg"),
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════════════════════════════════════
# LOGIN GATE
# ══════════════════════════════════════════════════════════════════════════════

def _check_login():
    """Show a password gate before the app loads. Password stored in st.secrets."""
    if st.session_state.get("authenticated"):
        return True

    # ── Centred login card ────────────────────────────────────────────────────
    st.markdown(
        '<style>'
        '@import url("https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=Inter:wght@400;500;600&display=swap");'
        'body,.stApp{background:#F0F0EE!important;-webkit-font-smoothing:antialiased}'
        'header[data-testid="stHeader"]{display:none}'
        '[data-testid="stSidebar"]{display:none}'
        '.login-wrap{display:flex;align-items:center;justify-content:center;min-height:90vh;background:#F0F0EE}'
        '.login-card{background:#FFFFFF;border:1px solid #D4D4D2;border-radius:0;'
        'padding:48px 44px 40px 44px;width:100%;max-width:400px;text-align:center}'
        '.login-rule{width:40px;height:2px;background:#1A3A5C;margin:0 auto 28px auto}'
        '.login-title{font-family:"Playfair Display",Georgia,serif;font-size:28px;font-weight:700;'
        'color:#1A1A1A;margin-bottom:6px;letter-spacing:-0.3px;line-height:1.1}'
        '.login-sub{font-family:"Inter",-apple-system,sans-serif;font-size:11px;font-weight:600;'
        'color:#777777;margin-bottom:0;letter-spacing:0.08em;text-transform:uppercase}'
        '.stButton>button{border-radius:0!important;font-family:"Inter",sans-serif!important;'
        'font-size:11px!important;font-weight:600!important;text-transform:uppercase!important;'
        'letter-spacing:0.08em!important;background:#1A3A5C!important;border:none!important}'
        '.stTextInput input{border-radius:0!important;border:1px solid #D4D4D2!important;'
        'font-family:"Inter",sans-serif!important;font-size:13px!important}'
        '.stTextInput input:focus{border-color:#1A3A5C!important;box-shadow:none!important}'
        '</style>'
        '<div class="login-wrap"><div class="login-card">'
        '<div class="login-rule"></div>'
        '<div class="login-title">Value Screener</div>'
        '<div class="login-sub">Quality &middot; Fair Price &middot; Long-term</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submitted = st.form_submit_button("Sign in", use_container_width=True, type="primary")

    if submitted:
        correct = st.secrets.get("APP_PASSWORD", "")
        if password == correct and correct != "":
            st.session_state.authenticated = True
            st.session_state.user_name = st.secrets.get("APP_USERNAME", "")
            st.rerun()
        else:
            st.error("Incorrect password — please try again.")

    return False

if not _check_login():
    st.stop()

st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════════════════════
   VALUE SCREENER — BBC/FT Editorial Design Language
   Palette: warm grey canvas · deep ink blue accent · no colour signals
   Typography: Playfair Display serif display + Inter sans UI
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── Google Fonts import ── */
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700;900&family=Inter:wght@300;400;500;600;700&display=swap');

/* ── CSS Custom Properties ── */
:root {
  --vs-bg:          #F0F0EE;
  --vs-bg-subtle:   #E8E8E6;
  --vs-bg-card:     #FFFFFF;
  --vs-bg-raised:   #F8F8F6;
  --vs-accent:      #1A3A5C;
  --vs-accent-dark: #122d48;
  --vs-ink:         #1A1A1A;
  --vs-ink-mid:     #444444;
  --vs-ink-soft:    #777777;
  --vs-ink-faint:   #AAAAAA;
  --vs-rule:        #D4D4D2;
  --vs-rule-soft:   #E0E0DE;
  --vs-serif:       'Playfair Display', Georgia, 'Times New Roman', serif;
  --vs-sans:        'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --vs-radius:      0px;
  --vs-radius-lg:   0px;
  --vs-shadow:      none;
  --vs-shadow-md:   none;
  --vs-transition:  all 0.15s ease;
}

/* ── Global Streamlit resets ── */
body, .stApp {
  font-family: var(--vs-sans) !important;
  -webkit-font-smoothing: antialiased !important;
  background-color: var(--vs-bg) !important;
}

/* ── Hide sidebar ── */
[data-testid="stSidebar"] { display: none !important; }

/* ── Layout ── */
.block-container {
  padding-top: 0 !important;
  padding-left: 40px !important;
  padding-right: 40px !important;
  max-width: 1200px !important;
}
[data-testid="stMainBlockContainer"] {
  padding-top: 0 !important;
}
.vs-topnav + div,
.vs-topnav + [data-testid="stVerticalBlock"] {
  margin-top: 0 !important;
  padding-top: 0 !important;
}
[data-testid="manage-app-button"],
[class*="manage-app"],
.st-emotion-cache-h4xjwg,
iframe[src*="statuspage"] {
  display: none !important;
}

/* ── Remove all rounding everywhere ── */
.stApp, .stButton > button, .stTextInput > div > input,
.stSelectbox > div, .stMultiSelect > div, .stExpander,
.stMetric, div[data-testid="metric-container"],
div[data-testid="stMarkdownContainer"] *,
[data-baseweb="select"] > div, [data-baseweb="tag"],
[data-baseweb="input"], [data-baseweb="base-input"],
.stTabs [data-baseweb="tab"],
.stProgress, .stAlert, .stDataFrame {
  border-radius: 0 !important;
}

/* ── Remove Streamlit header bar ── */
header[data-testid="stHeader"] { display: none !important; }

/* ── Top nav bar ── */
.vs-topnav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: #FFFFFF;
  border-bottom: 1px solid #D4D4D2;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 40px;
  margin-left: -40px;
  margin-right: -40px;
  margin-bottom: 0;
  width: calc(100% + 80px);
  box-sizing: border-box;
}
.vs-topnav-wordmark {
  font-family: var(--vs-serif);
  font-size: 18px;
  font-weight: 700;
  color: #1A1A1A;
  letter-spacing: -0.3px;
  text-decoration: none;
  flex-shrink: 0;
}
.vs-topnav-links {
  display: flex;
  align-items: center;
  gap: 0;
  flex: 1;
  justify-content: center;
}
.vs-topnav-link {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #444444;
  padding: 0 20px;
  height: 56px;
  display: flex;
  align-items: center;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  text-decoration: none;
  transition: color 0.1s;
  border-top: none;
  border-left: none;
  border-right: none;
  background: none;
  white-space: nowrap;
}
.vs-topnav-link:hover { color: #1A1A1A !important; }
.vs-topnav-link.active {
  color: #1A3A5C !important;
  border-bottom: 3px solid #1A3A5C !important;
}
.vs-topnav-settings {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #444444;
  cursor: pointer;
  flex-shrink: 0;
}
.vs-topnav-settings-dot { color: #1A3A5C; }

/* ── Hero band (Home only) ── */
.vs-hero {
  background: #1A3A5C;
  padding: 36px 40px 32px;
  border-bottom: 3px solid rgba(0,0,0,0.2);
  margin-left: -40px;
  margin-right: -40px;
  width: calc(100% + 80px);
  box-sizing: border-box;
  margin-bottom: 0;
  margin-top: 0;
}
.vs-hero-greeting {
  font-family: var(--vs-serif);
  font-size: 38px;
  font-weight: 700;
  color: #FFFFFF;
  letter-spacing: -0.5px;
  line-height: 1.1;
  margin-bottom: 6px;
}
.vs-hero-timestamp {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(255,255,255,0.78);
  margin-bottom: 28px;
}
.vs-hero-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.15);
}
.vs-hero-stat {
  background: rgba(255,255,255,0.09);
  padding: 20px 24px;
}
.vs-hero-stat-val {
  font-family: var(--vs-serif);
  font-size: 32px;
  font-weight: 700;
  color: #FFFFFF;
  line-height: 1;
  margin-bottom: 6px;
}
.vs-hero-stat-val.positive { color: #a8d8b0; }
.vs-hero-stat-lbl {
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(255,255,255,0.78);
}

/* ── Section headers (BBC-style) ── */
.vs-section-header {
  padding-top: 32px;
  margin-bottom: 0;
}
.vs-section-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  border-bottom: 2px solid #1A1A1A;
  padding-bottom: 6px;
  margin-bottom: 1px;
}
.vs-section-rule {
  height: 1px;
  background: #D4D4D2;
  margin-bottom: 20px;
}
.vs-section-title {
  font-family: var(--vs-sans);
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #1A1A1A;
}
.vs-section-link {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #777777;
  text-decoration: none;
  cursor: pointer;
}
.vs-section-link:hover { color: #1A3A5C !important; }

/* Keep old section-header for sidebar/legacy usage */
.section-header {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #777777;
  margin-bottom: 12px;
  margin-top: 4px;
}

/* ── Summary stat bar ── */
.vs-statbar {
  display: flex;
  border: 1px solid #D4D4D2;
  margin-bottom: 20px;
}
.vs-statbar-cell {
  background: #FFFFFF;
  padding: 16px 24px;
  border-right: 1px solid #D4D4D2;
  flex: 1;
}
.vs-statbar-cell:last-child { border-right: none; }
.vs-statbar-val {
  font-family: var(--vs-serif);
  font-size: 26px;
  font-weight: 700;
  color: #1A1A1A;
  line-height: 1;
  margin-bottom: 5px;
}
.vs-statbar-lbl {
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: #777777;
}

/* ── Instrument card ── */
.card {
  background: #FFFFFF;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 24px;
  margin-bottom: 1px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.card:hover { border-color: #AAAAAA; }
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.card-name {
  font-family: var(--vs-serif);
  font-size: 22px;
  font-weight: 700;
  color: #1A1A1A;
  letter-spacing: -0.2px;
  line-height: 1.15;
  margin-bottom: 6px;
}
.card-ticker-line {
  font-family: var(--vs-sans);
  font-size: 13px;
  color: #1A1A1A;
  margin-bottom: 2px;
}
.card-ticker-line .ticker { font-weight: 700; }
.card-ticker-line .price  { font-weight: 600; color: #444444; }
.card-market-line {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 400;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #777777;
}
.card-score-block {
  border-left: 3px solid #1A3A5C;
  padding-left: 12px;
  min-width: 80px;
  flex-shrink: 0;
}
.card-score-block.low { border-left-color: #D4D4D2; }
.card-score-num {
  font-family: var(--vs-serif);
  font-size: 34px;
  font-weight: 700;
  color: #1A1A1A;
  line-height: 1;
}
.card-score-block.low .card-score-num { color: #444444; }
.card-score-lbl {
  font-family: var(--vs-sans);
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #777777;
  margin-top: 3px;
}

/* ── Card bullets ── */
.card-bullets {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0;
}
.card-bullet {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-family: var(--vs-sans);
  font-size: 12.5px;
  color: #444444;
  line-height: 1.45;
}
.card-bullet-icon {
  width: 14px;
  height: 14px;
  border: 1px solid #1A3A5C;
  color: #1A3A5C;
  font-family: var(--vs-sans);
  font-size: 8px;
  font-weight: 700;
  border-radius: 0 !important;
  flex-shrink: 0;
  margin-top: 2px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.card-bullet strong { color: #1A1A1A; }

/* ── Card footer ── */
.card-footer {
  border-top: 1px solid #D4D4D2;
  padding-top: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-ytd {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 600;
  color: #444444;
}
.card-ytd-val { font-weight: 700; color: #1A1A1A; }
.card-tag {
  font-family: var(--vs-sans);
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #1A3A5C;
  border: 1px solid #1A3A5C;
  background: transparent;
  padding: 3px 8px;
  border-radius: 0 !important;
}

/* ── Metric pills ── */
.card-metrics { display: flex; flex-wrap: wrap; gap: 6px; }
.metric-pill {
  background: #FFFFFF;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 4px 10px;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  color: #444444;
}
.metric-pill b { color: #1A1A1A; }
.metric-pill.good   { background: #FFFFFF; border-color: #D4D4D2; color: #444444; }
.metric-pill.good b { color: #1A1A1A; }
.metric-pill.warn   { background: #FFFFFF; border-color: #D4D4D2; color: #444444; }
.metric-pill.warn b { color: #1A1A1A; }
.metric-pill.bad    { background: #FFFFFF; border-color: #D4D4D2; color: #777777; }
.metric-pill.bad b  { color: #444444; }

/* ── Quality fail badge ── */
.quality-fail {
  background: transparent;
  color: #777777;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 3px 9px;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  display: inline-block;
  margin-bottom: 8px;
}
.risk-flag {
  background: transparent;
  color: #9B6B00;
  border: 1px solid #E8D0A0;
  border-radius: 0 !important;
  padding: 3px 9px;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  display: inline-block;
  margin: 2px 4px 2px 0;
}
.risk-flag.distress {
  color: #8B2020;
  border-color: #E8C0C0;
}

/* ── Signal badges on cards ── */
.signal-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 0 !important;
  padding: 2px 8px;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.05em;
  margin-right: 4px;
  margin-bottom: 4px;
  cursor: default;
  background: transparent !important;
  color: #1A3A5C !important;
  border: 1px solid #1A3A5C !important;
}
.signal-badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}

/* ── Dashboard summary tiles ── */
.summary-tile {
  background: #FFFFFF;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 18px 20px 16px 20px;
}
.summary-number {
  font-family: var(--vs-serif);
  font-size: 2.2rem;
  font-weight: 700;
  line-height: 1;
  color: #1A1A1A;
  letter-spacing: -0.02em;
}
.summary-label {
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  color: #777777;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-top: 5px;
}

/* ── Macro status bar ── */
.macro-bar {
  background: #FFFFFF;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 12px 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  align-items: center;
  margin-bottom: 20px;
}
.macro-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.macro-item-val {
  font-family: var(--vs-sans);
  font-size: 0.88rem;
  font-weight: 600;
  color: #1A1A1A;
  line-height: 1.2;
}
.macro-item-lbl {
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  color: #777777;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-top: 2px;
}

/* ── Changed-since-scan banner ── */
.changed-banner {
  background: #FFFFFF;
  border: 1px solid #D4D4D2;
  border-left: 3px solid #1A3A5C;
  border-radius: 0 !important;
  padding: 14px 18px;
  margin-bottom: 18px;
  font-family: var(--vs-sans);
  font-size: 13px;
  color: #444444;
}
.changed-banner b { color: #1A1A1A; font-weight: 600; }

/* ── Score breakdown table ── */
.breakdown-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 0;
  border-bottom: 1px solid #D4D4D2;
  font-family: var(--vs-sans);
  font-size: 12px;
  color: #444444;
}
.breakdown-row:last-child { border-bottom: none; }
.breakdown-bar-bg {
  background: #F0F0EE;
  border-radius: 0 !important;
  height: 4px;
  flex: 1;
  margin: 0 12px;
  overflow: hidden;
}
.breakdown-bar-fill { height: 100%; border-radius: 0 !important; background: #1A3A5C; }

/* ── Deep Analysis ── */
.da-section {
  background: #F8F8F6;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 18px 22px;
  margin: 10px 0 8px 0;
}
.da-section-title {
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.10em;
  color: #1A3A5C;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.da-score-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
}
.da-score-big {
  font-family: var(--vs-serif);
  font-size: 2.1rem;
  font-weight: 700;
  line-height: 1;
  color: #1A1A1A;
  letter-spacing: -0.02em;
}
.da-rating {
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 10px;
  border-radius: 0 !important;
  border: 1px solid #1A3A5C;
  color: #1A3A5C;
  background: transparent;
}
.da-confidence {
  font-family: var(--vs-sans);
  font-size: 11px;
  font-weight: 400;
  color: #777777;
  margin-left: 4px;
}
.da-bar-bg {
  background: #F0F0EE;
  border-radius: 0 !important;
  height: 5px;
  flex: 1;
  overflow: hidden;
  margin: 0 12px;
}
.da-bar-fill { height: 100%; border-radius: 0 !important; background: #1A3A5C; }
.da-component-row {
  display: flex;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid #D4D4D2;
  font-family: var(--vs-sans);
  font-size: 12px;
  color: #444444;
  gap: 10px;
}
.da-component-row:last-child { border-bottom: none; }
.da-just {
  font-family: var(--vs-sans);
  font-size: 12.5px;
  color: #444444;
  line-height: 1.55;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #D4D4D2;
}
.da-risk-tag {
  display: inline-block;
  background: transparent;
  color: #777777;
  border: 1px solid #D4D4D2;
  border-radius: 0 !important;
  padding: 2px 9px;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 2px 3px 2px 0;
}
.da-driver-tag {
  display: inline-block;
  background: transparent;
  color: #1A3A5C;
  border: 1px solid #1A3A5C;
  border-radius: 0 !important;
  padding: 2px 9px;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 2px 3px 2px 0;
}

/* ── Streamlit metric widget ── */
[data-testid="stMetric"] {
  background: #FFFFFF !important;
  border: 1px solid #D4D4D2 !important;
  border-radius: 0 !important;
  padding: 16px 20px !important;
  box-shadow: none !important;
}
[data-testid="stMetricLabel"] {
  color: #777777 !important;
  font-family: var(--vs-sans) !important;
  font-size: 10px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
}
[data-testid="stMetricValue"] {
  color: #1A1A1A !important;
  font-family: var(--vs-serif) !important;
  font-size: 1.8rem !important;
  font-weight: 700 !important;
}
[data-testid="stMetricDelta"] {
  font-size: 11px !important;
  font-weight: 600 !important;
  color: #444444 !important;
}

/* ── Buttons ── */
.stButton button {
  border-radius: 0 !important;
  font-family: var(--vs-sans) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  box-shadow: none !important;
}
.stButton button[kind="primary"] {
  background: #1A3A5C !important;
  border: none !important;
  color: #FFFFFF !important;
  padding: 10px 20px !important;
}
.stButton button[kind="primary"]:hover {
  background: #122d48 !important;
}
.stButton button[kind="secondary"],
.stButton button:not([kind]) {
  background: transparent !important;
  border: 1px solid #1A3A5C !important;
  color: #1A3A5C !important;
  padding: 9px 19px !important;
}
.stButton button[kind="secondary"]:hover,
.stButton button:not([kind]):hover {
  background: #1A3A5C !important;
  color: #FFFFFF !important;
}

/* ── Text inputs / text areas ── */
.stTextInput input, .stTextArea textarea {
  background: #FFFFFF !important;
  border: 1px solid #D4D4D2 !important;
  border-radius: 0 !important;
  color: #1A1A1A !important;
  font-family: var(--vs-sans) !important;
  font-size: 13px !important;
  padding: 8px 12px !important;
  box-shadow: none !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
  border-color: #1A3A5C !important;
  box-shadow: none !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
  color: #777777 !important;
}

/* ── Selectbox / Multiselect ── */
.stSelectbox [data-baseweb="select"] > div,
.stMultiSelect [data-baseweb="select"] > div {
  background: #FFFFFF !important;
  border: 1px solid #D4D4D2 !important;
  border-radius: 0 !important;
  color: #1A1A1A !important;
  font-family: var(--vs-sans) !important;
  font-size: 13px !important;
  box-shadow: none !important;
}
.stSelectbox [data-baseweb="select"] > div:focus-within,
.stMultiSelect [data-baseweb="select"] > div:focus-within {
  border-color: #1A3A5C !important;
  box-shadow: none !important;
}
.stMultiSelect span[data-baseweb="tag"] {
  background: transparent !important;
  color: #1A3A5C !important;
  border: 1px solid #1A3A5C !important;
  border-radius: 0 !important;
  font-size: 10px !important;
  font-weight: 600 !important;
}

/* ── Slider ── */
.stSlider [data-baseweb="slider"] [role="slider"] {
  background: #1A3A5C !important;
  border-color: #1A3A5C !important;
  border-radius: 0 !important;
}

/* ── Expanders ── */
.stExpander {
  border: 1px solid #D4D4D2 !important;
  border-radius: 0 !important;
  background: #FFFFFF !important;
  box-shadow: none !important;
}
.stExpander summary {
  background: #F8F8F6 !important;
  font-family: var(--vs-sans) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.06em !important;
  color: #1A1A1A !important;
  padding: 12px 16px !important;
}
.stExpander [data-testid="stExpanderDetails"] {
  padding: 16px !important;
  background: #FFFFFF !important;
}

/* ── Streamlit tabs ── */
.stTabs [data-baseweb="tab-list"] {
  border-bottom: 1px solid #D4D4D2 !important;
  gap: 0 !important;
  background: transparent !important;
  border-top: 1px solid #D4D4D2 !important;
}
.stTabs [data-baseweb="tab"] {
  font-family: var(--vs-sans) !important;
  font-size: 11px !important;
  font-weight: 600 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  color: #444444 !important;
  padding: 12px 20px !important;
  border-bottom: 3px solid transparent !important;
  background: transparent !important;
  border-radius: 0 !important;
}
.stTabs [aria-selected="true"] {
  color: #1A3A5C !important;
  border-bottom: 3px solid #1A3A5C !important;
  font-weight: 600 !important;
}

/* ── Alerts / info boxes — override all colour variants to monochrome ── */
.stAlert {
  border-radius: 0 !important;
  font-family: var(--vs-sans) !important;
  font-size: 13px !important;
  border: 1px solid #D4D4D2 !important;
  border-left: 3px solid #777777 !important;
  box-shadow: none !important;
  background: #FFFFFF !important;
  color: #444444 !important;
}
/* Remove coloured backgrounds from warning/error/info/success variants */
[data-testid="stAlert"] {
  background: #FFFFFF !important;
  border: 1px solid #D4D4D2 !important;
  border-left: 3px solid #777777 !important;
  border-radius: 0 !important;
  color: #444444 !important;
}
[data-testid="stAlert"] p,
[data-testid="stAlert"] span,
[data-testid="stAlert"] div {
  color: #444444 !important;
  font-family: var(--vs-sans) !important;
}
/* Hide the coloured icon in alerts */
[data-testid="stAlert"] [data-testid="stAlertIcon"] {
  display: none !important;
}

/* ── Streamlit dataframe / table ── */
.stDataFrame {
  border-radius: 0 !important;
  overflow: hidden !important;
  box-shadow: none !important;
  border: 1px solid #D4D4D2 !important;
}

/* ── Progress bar ── */
.stProgress > div > div { background: #1A3A5C !important; border-radius: 0 !important; }

/* ── Main content typography ── */
.stApp h1 {
  font-family: var(--vs-serif) !important;
  font-size: 38px !important;
  font-weight: 700 !important;
  color: #1A1A1A !important;
  letter-spacing: -0.5px !important;
  line-height: 1.1 !important;
}
.stApp h2 {
  font-family: var(--vs-sans) !important;
  font-size: 13px !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.08em !important;
  color: #1A1A1A !important;
}
.stApp h3 {
  font-family: var(--vs-serif) !important;
  font-size: 22px !important;
  font-weight: 700 !important;
  color: #1A1A1A !important;
  letter-spacing: -0.2px !important;
}
.stApp p, .stApp li, .stApp .stMarkdown {
  font-family: var(--vs-sans) !important;
  color: #444444 !important;
  font-size: 13px !important;
  line-height: 1.55 !important;
}
.stApp .stCaption { font-size: 11px !important; color: #777777 !important; font-family: var(--vs-sans) !important; }
.stApp hr { border-color: #D4D4D2 !important; }

/* ── Mobile responsive overrides ── */
@media (max-width: 768px) {
  /* Viewport meta — prevent zoom on input focus */
  /* (set via Streamlit's page config — cannot inject via CSS) */

  /* ── Page padding ── */
  .block-container {
    padding-left: 12px !important;
    padding-right: 12px !important;
    padding-bottom: 80px !important; /* space for sticky mobile nav */
  }

  /* ── Nav bar: wordmark + hamburger only; links hidden ── */
  .vs-topnav {
    padding: 0 12px !important;
    height: 48px !important;
    margin-left: -16px !important;
    margin-right: -16px !important;
    width: calc(100% + 32px) !important;
  }
  .vs-topnav-links { display: none !important; }
  .vs-topnav-settings { display: none !important; }
  .vs-topnav-wordmark { font-size: 14px !important; }

  /* ── Sticky bottom tab bar — Streamlit-compatible ── */
  /* This injects a fixed bottom bar with the 5 main nav items as large tap targets.
     The actual navigation triggers hidden Streamlit buttons via JS.
     Compromise: same nav JS as the hamburger, re-used for bottom bar clicks. */
  .vs-mobile-bottombar {
    display: flex !important;
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 58px;
    background: var(--vs-bg-card);
    border-top: 1px solid var(--vs-rule);
    z-index: 9999;
    align-items: stretch;
    justify-content: space-around;
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  .vs-mobile-tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    font-family: var(--vs-sans);
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--vs-ink-soft);
    border: none;
    background: none;
    padding: 6px 4px 4px;
    min-height: 44px; /* WCAG tap target */
    -webkit-tap-highlight-color: transparent;
    transition: color 0.12s;
  }
  .vs-mobile-tab.active { color: var(--vs-accent); }
  .vs-mobile-tab svg { width: 20px; height: 20px; stroke: currentColor; stroke-width: 1.5; fill: none; }
  .vs-mobile-tab span { margin-top: 2px; }

  /* ── Hero band ── */
  .vs-hero {
    padding: 20px 12px 16px !important;
    margin-left: -12px !important;
    margin-right: -12px !important;
    width: calc(100% + 24px) !important;
  }
  .vs-hero-greeting { font-size: 24px !important; }
  .vs-hero-timestamp { font-size: 10px !important; }
  .vs-hero-stats { grid-template-columns: repeat(2, 1fr) !important; gap: 8px !important; }
  .vs-hero-stat-val { font-size: 22px !important; }

  /* ── Stat bar: two-column wrap ── */
  .vs-statbar { flex-wrap: wrap !important; }
  .vs-statbar-cell { flex: 0 0 50% !important; border-right: none !important; border-bottom: 1px solid var(--vs-rule) !important; }
  .vs-statbar-cell:nth-child(odd) { border-right: 1px solid var(--vs-rule) !important; }
  .vs-statbar-cell:last-child { border-bottom: none !important; }
  .vs-statbar-val { font-size: 20px !important; }

  /* ── Cards: full width, comfortable touch padding ── */
  .card { padding: 16px !important; }
  .card-name { font-size: 17px !important; }
  .card-score-num { font-size: 26px !important; }
  .card-bullet { font-size: 12px !important; }
  .card-metrics { gap: 6px !important; }

  /* ── Buttons: minimum 44px tap targets ── */
  .stButton > button {
    min-height: 44px !important;
    font-size: 13px !important;
    padding: 10px 14px !important;
  }

  /* ── Inputs: prevent iOS zoom (font-size >= 16px) ── */
  input[type="text"], input[type="password"], input[type="email"],
  textarea, select {
    font-size: 16px !important;
  }

  /* ── Metric tiles ── */
  [data-testid="stMetric"] { padding: 10px 8px !important; }
  [data-testid="stMetricValue"] { font-size: 20px !important; }
  [data-testid="stMetricLabel"] { font-size: 11px !important; }

  /* ── Score breakdown: vertical stack ── */
  .breakdown-row { flex-direction: column !important; gap: 4px !important; }
  .breakdown-bar-bg { width: 100% !important; }

  /* ── Column gaps ── */
  [data-testid="stHorizontalBlock"] { gap: 8px !important; }

  /* ── Macro bar: compress ── */
  .vs-macro-bar { overflow-x: auto !important; -webkit-overflow-scrolling: touch !important; flex-wrap: nowrap !important; }
  .macro-item { min-width: 64px !important; }
  .macro-item-val { font-size: 14px !important; }

  /* ── Section headers ── */
  .vs-section-title { font-size: 10px !important; }
  .vs-section-link { font-size: 10px !important; }

  /* ── Page titles ── */
  .stMarkdown h1, .stMarkdown div[style*="font-size:38px"] {
    font-size: 28px !important;
    padding-top: 16px !important;
  }
}

@media (max-width: 480px) {
  .vs-hero-greeting { font-size: 20px !important; }
  .vs-hero-stats { grid-template-columns: repeat(2, 1fr) !important; }
  .block-container { padding-left: 8px !important; padding-right: 8px !important; }
  .card-name { font-size: 15px !important; }
}

/* ═══════════════════════════════════════════════════════════════════════════
   DARK MODE — CSS custom properties & component overrides
   ═══════════════════════════════════════════════════════════════════════════ */

html, html[data-theme="light"] {
  --bg: #F0F0EE; --surface: #FFFFFF; --ink: #1A1A1A;
  --ink-mid: #444444; --ink-light: #777777; --rule: #D4D4D2; --accent: #1A3A5C;
}
html[data-theme="dark"] {
  --bg: #0A0A0A; --surface: #1A1A1A; --ink: #E8E8E8;
  --ink-mid: #B8B8B8; --ink-light: #888888; --rule: #333333; --accent: #5B8AB8;
  /* remap existing --vs-* variables */
  --vs-bg: #0A0A0A; --vs-bg-card: #1A1A1A; --vs-bg-subtle: #111111;
  --vs-bg-raised: #1E1E1E; --vs-ink: #E8E8E8; --vs-ink-mid: #B8B8B8;
  --vs-ink-soft: #888888; --vs-ink-faint: #555555; --vs-rule: #333333;
  --vs-rule-soft: #2A2A2A; --vs-accent: #5B8AB8; --vs-accent-dark: #4A7AA0;
}

/* Dark: global background */
html[data-theme="dark"] .stApp,
html[data-theme="dark"] body { background-color: var(--vs-bg) !important; }

/* Dark: surface cards & panels */
html[data-theme="dark"] .card,
html[data-theme="dark"] .vs-statbar-cell,
html[data-theme="dark"] .summary-tile,
html[data-theme="dark"] .macro-bar,
html[data-theme="dark"] .changed-banner { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; }
html[data-theme="dark"] [data-testid="stMetric"] { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; }
html[data-theme="dark"] [data-testid="stAlert"] { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] [data-testid="stAlert"] p,
html[data-theme="dark"] [data-testid="stAlert"] span,
html[data-theme="dark"] [data-testid="stAlert"] div { color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .stExpander { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .stExpander summary { background: var(--vs-bg-subtle) !important; color: var(--vs-ink) !important; }
html[data-theme="dark"] .stExpander [data-testid="stExpanderDetails"] { background: var(--vs-bg-card) !important; }
html[data-theme="dark"] .da-section { background: var(--vs-bg-raised) !important; border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .stDataFrame { border-color: var(--vs-rule) !important; background: var(--vs-bg-card) !important; }

/* Dark: navigation */
html[data-theme="dark"] .vs-topnav { background: var(--vs-bg-card) !important; border-bottom-color: var(--vs-rule) !important; }
html[data-theme="dark"] .vs-topnav-wordmark { color: var(--vs-ink) !important; }
html[data-theme="dark"] .vs-topnav-link { color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .vs-topnav-link:hover { color: var(--vs-ink) !important; }
html[data-theme="dark"] .vs-topnav-link.active { color: var(--vs-accent) !important; border-bottom-color: var(--vs-accent) !important; }
html[data-theme="dark"] .vs-topnav-settings { color: var(--vs-ink-soft) !important; }

/* Dark: hero */
html[data-theme="dark"] .vs-hero { background: #0F2540 !important; }

/* Dark: typography */
html[data-theme="dark"] .card-name,
html[data-theme="dark"] .card-score-num,
html[data-theme="dark"] .vs-section-title,
html[data-theme="dark"] .stApp h1,
html[data-theme="dark"] .stApp h2,
html[data-theme="dark"] .stApp h3,
html[data-theme="dark"] .vs-statbar-val,
html[data-theme="dark"] .summary-number,
html[data-theme="dark"] [data-testid="stMetricValue"],
html[data-theme="dark"] .card-ytd-val { color: var(--vs-ink) !important; }

html[data-theme="dark"] .card-bullet,
html[data-theme="dark"] .stApp p,
html[data-theme="dark"] .stApp li,
html[data-theme="dark"] .card-ytd,
html[data-theme="dark"] [data-testid="stMetricDelta"] { color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .card-ticker-line { color: var(--vs-ink) !important; }
html[data-theme="dark"] .card-ticker-line .price { color: var(--vs-ink-mid) !important; }

html[data-theme="dark"] .card-market-line,
html[data-theme="dark"] .vs-statbar-lbl,
html[data-theme="dark"] .card-score-lbl,
html[data-theme="dark"] .summary-label,
html[data-theme="dark"] [data-testid="stMetricLabel"] { color: var(--vs-ink-soft) !important; }

/* Dark: borders */
html[data-theme="dark"] .vs-section-header-row { border-bottom-color: var(--vs-ink) !important; }
html[data-theme="dark"] .vs-section-rule { background: var(--vs-rule) !important; }
html[data-theme="dark"] .card-footer { border-top-color: var(--vs-rule) !important; }
html[data-theme="dark"] .vs-statbar { border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .vs-statbar-cell { border-right-color: var(--vs-rule) !important; }
html[data-theme="dark"] .stApp hr { border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .breakdown-row { border-bottom-color: var(--vs-rule) !important; color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .da-component-row { border-bottom-color: var(--vs-rule) !important; color: var(--vs-ink-mid) !important; }

/* Dark: accent elements */
html[data-theme="dark"] .card-score-block { border-left-color: var(--vs-accent) !important; }
html[data-theme="dark"] .card-score-block.low { border-left-color: var(--vs-rule) !important; }
html[data-theme="dark"] .card-bullet-icon { border-color: var(--vs-accent) !important; color: var(--vs-accent) !important; }
html[data-theme="dark"] .card-tag { color: var(--vs-accent) !important; border-color: var(--vs-accent) !important; }
html[data-theme="dark"] .signal-badge { color: var(--vs-accent) !important; border-color: var(--vs-accent) !important; }
html[data-theme="dark"] .da-rating { color: var(--vs-accent) !important; border-color: var(--vs-accent) !important; }
html[data-theme="dark"] .da-driver-tag { color: var(--vs-accent) !important; border-color: var(--vs-accent) !important; }
html[data-theme="dark"] .da-section-title { color: var(--vs-accent) !important; }
html[data-theme="dark"] .vs-section-link { color: var(--vs-accent) !important; }
html[data-theme="dark"] .breakdown-bar-fill,
html[data-theme="dark"] .da-bar-fill { background: var(--vs-accent) !important; }
html[data-theme="dark"] .breakdown-bar-bg,
html[data-theme="dark"] .da-bar-bg { background: var(--vs-bg-raised) !important; }

/* Dark: inputs */
html[data-theme="dark"] .stTextInput input,
html[data-theme="dark"] .stTextArea textarea { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; color: var(--vs-ink) !important; }
html[data-theme="dark"] .stSelectbox [data-baseweb="select"] > div,
html[data-theme="dark"] .stMultiSelect [data-baseweb="select"] > div { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; color: var(--vs-ink) !important; }
html[data-theme="dark"] .metric-pill { background: var(--vs-bg-card) !important; border-color: var(--vs-rule) !important; color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .metric-pill b { color: var(--vs-ink) !important; }
html[data-theme="dark"] .quality-fail { color: var(--vs-ink-soft) !important; border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .risk-flag { color: var(--vs-ink-mid) !important; border-color: var(--vs-rule) !important; }

/* Dark: buttons */
html[data-theme="dark"] .stButton button[kind="primary"] { background: var(--vs-accent) !important; }
html[data-theme="dark"] .stButton button[kind="secondary"],
html[data-theme="dark"] .stButton button:not([kind]) { border-color: var(--vs-accent) !important; color: var(--vs-accent) !important; }

/* Dark: tabs */
html[data-theme="dark"] .stTabs [data-baseweb="tab-list"] { border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .stTabs [data-baseweb="tab"] { color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .stTabs [aria-selected="true"] { color: var(--vs-accent) !important; border-bottom-color: var(--vs-accent) !important; }

/* Dark: misc */
html[data-theme="dark"] .da-just { color: var(--vs-ink-mid) !important; border-top-color: var(--vs-rule) !important; }
html[data-theme="dark"] .da-risk-tag { color: var(--vs-ink-soft) !important; border-color: var(--vs-rule) !important; }
html[data-theme="dark"] .da-score-big { color: var(--vs-ink) !important; }
html[data-theme="dark"] .da-confidence { color: var(--vs-ink-soft) !important; }
html[data-theme="dark"] .macro-item-val { color: var(--vs-ink) !important; }
html[data-theme="dark"] .macro-item-lbl { color: var(--vs-ink-soft) !important; }
html[data-theme="dark"] .changed-banner { color: var(--vs-ink-mid) !important; }
html[data-theme="dark"] .changed-banner b { color: var(--vs-ink) !important; }
html[data-theme="dark"] .stProgress > div { background: var(--vs-bg-raised) !important; }
html[data-theme="dark"] .stProgress > div > div { background: var(--vs-accent) !important; }

/* ═══════════════════════════════════════════════════════════════════════════
   HAMBURGER NAVIGATION — mobile drawer (< 1024px)
   ═══════════════════════════════════════════════════════════════════════════ */

/* Theme toggle button — desktop only */
.vs-theme-toggle-btn {
  display: none;
  background: none;
  border: 1px solid var(--vs-rule, #D4D4D2);
  cursor: pointer;
  padding: 4px 9px;
  color: var(--vs-ink-soft, #777777);
  align-items: center;
  gap: 5px;
  margin-left: 12px;
  flex-shrink: 0;
  font-family: var(--vs-sans);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  transition: all 150ms ease;
  border-radius: 0;
}
.vs-theme-toggle-btn:hover { border-color: var(--vs-accent, #1A3A5C); color: var(--vs-accent, #1A3A5C); }
html[data-theme="dark"] .vs-theme-toggle-btn { border-color: var(--vs-rule); color: var(--vs-ink-soft); }
html[data-theme="dark"] .vs-theme-toggle-btn:hover { border-color: var(--vs-accent); color: var(--vs-accent); }
@media (min-width: 1024px) { .vs-theme-toggle-btn { display: flex; } }

/* Hamburger button */
.vs-hamburger {
  display: none;
  background: none;
  border: none;
  cursor: pointer;
  padding: 6px 4px;
  color: var(--vs-ink, #1A1A1A);
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  margin-left: 8px;
}
html[data-theme="dark"] .vs-hamburger { color: var(--vs-ink); }
@media (max-width: 1023px) {
  .vs-hamburger { display: flex; }
  .vs-topnav-links { display: none !important; }
  .vs-topnav-settings { display: none !important; }
  .vs-topnav {
    padding: 0 16px !important;
    margin-left: -16px !important;
    margin-right: -16px !important;
    width: calc(100% + 32px) !important;
    height: 48px !important;
  }
  .vs-topnav-wordmark { font-size: 16px !important; }
}

/* Mobile nav drawer */
.vs-mobile-drawer {
  position: fixed;
  top: 0;
  right: -290px;
  width: 280px;
  height: 100vh;
  background: var(--vs-bg-card, #FFFFFF);
  border-left: 1px solid var(--vs-rule, #D4D4D2);
  box-shadow: -4px 0 16px rgba(0,0,0,0.15);
  z-index: 10000;
  transition: right 250ms ease-out;
  overflow-y: auto;
  padding: 24px 20px;
  box-sizing: border-box;
}
.vs-mobile-drawer.open { right: 0; }

.vs-drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--vs-rule, #D4D4D2);
}
.vs-drawer-wordmark {
  font-family: var(--vs-serif, 'Playfair Display', Georgia, serif);
  font-size: 16px;
  font-weight: 700;
  color: var(--vs-ink, #1A1A1A);
  letter-spacing: -0.3px;
}
.vs-drawer-close {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--vs-ink-soft, #777777);
  padding: 4px;
  display: flex;
  align-items: center;
}
.vs-drawer-navlink {
  display: flex;
  align-items: center;
  font-family: var(--vs-sans, 'Inter', sans-serif);
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--vs-ink, #1A1A1A);
  padding: 16px 0 16px 3px;
  border-bottom: 1px solid var(--vs-rule, #D4D4D2);
  cursor: pointer;
  background: none;
  border-left: 3px solid transparent;
  transition: all 150ms ease;
}
.vs-drawer-navlink:last-of-type { border-bottom: none; }
.vs-drawer-navlink.active {
  color: var(--vs-accent, #1A3A5C);
  border-left-color: var(--vs-accent, #1A3A5C);
  padding-left: 12px;
}
.vs-drawer-section-title {
  font-family: var(--vs-sans, 'Inter', sans-serif);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--vs-ink-soft, #777777);
  margin-top: 20px;
  margin-bottom: 10px;
}
.vs-drawer-btn-row { display: flex; gap: 8px; flex-wrap: wrap; }
.vs-drawer-btn {
  font-family: var(--vs-sans, 'Inter', sans-serif);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--vs-ink-mid, #444444);
  background: transparent;
  border: 1px solid var(--vs-rule, #D4D4D2);
  padding: 6px 14px;
  cursor: pointer;
  border-radius: 0;
  transition: all 150ms ease;
}
.vs-drawer-btn.active {
  background: var(--vs-accent, #1A3A5C);
  border-color: var(--vs-accent, #1A3A5C);
  color: #FFFFFF;
}

/* Dark: drawer */
html[data-theme="dark"] .vs-mobile-drawer { background: var(--vs-bg-card) !important; border-left-color: var(--vs-rule) !important; }
html[data-theme="dark"] .vs-drawer-header { border-bottom-color: var(--vs-rule) !important; }
html[data-theme="dark"] .vs-drawer-wordmark { color: var(--vs-ink) !important; }
html[data-theme="dark"] .vs-drawer-close { color: var(--vs-ink-soft) !important; }
html[data-theme="dark"] .vs-drawer-navlink { color: var(--vs-ink) !important; border-bottom-color: var(--vs-rule) !important; }
html[data-theme="dark"] .vs-drawer-navlink.active { color: var(--vs-accent) !important; border-left-color: var(--vs-accent) !important; }
html[data-theme="dark"] .vs-drawer-section-title { color: var(--vs-ink-soft) !important; }
html[data-theme="dark"] .vs-drawer-btn { color: var(--vs-ink-mid) !important; border-color: var(--vs-rule) !important; }

/* Backdrop */
.vs-nav-backdrop {
  position: fixed;
  top: 0; left: 0;
  width: 100vw; height: 100vh;
  background: rgba(0,0,0,0.4);
  z-index: 9999;
  opacity: 0;
  pointer-events: none;
  transition: opacity 250ms ease-out;
}
.vs-nav-backdrop.visible { opacity: 1; pointer-events: auto; }

/* ═══════════════════════════════════════════════════════════════════════════
   DENSITY CONTROL & CARD HOVER INTERACTIONS
   ═══════════════════════════════════════════════════════════════════════════ */

/* Density: compact */
[data-density="compact"] .card { padding: 16px !important; gap: 10px !important; }
[data-density="compact"] .vs-hero-stat { padding: 14px 18px !important; }
[data-density="compact"] .vs-statbar-cell { padding: 12px 16px !important; }
[data-density="compact"] .vs-section-header { padding-top: 20px !important; }

/* Density: spacious */
[data-density="spacious"] .card { padding: 32px !important; gap: 18px !important; }
[data-density="spacious"] .vs-hero-stat { padding: 28px 32px !important; }
[data-density="spacious"] .vs-statbar-cell { padding: 22px 28px !important; }
[data-density="spacious"] .vs-section-header { padding-top: 44px !important; }

/* Card hover shadow (desktop only) */
@media (min-width: 1024px) {
  .card:hover {
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    z-index: 1;
    position: relative;
  }
  html[data-theme="dark"] .card:hover {
    box-shadow: 0 2px 12px rgba(0,0,0,0.3);
  }
}

/* Accessibility: focus rings */
*:focus-visible { outline: 2px solid var(--vs-accent, #1A3A5C); outline-offset: 2px; }
*:focus:not(:focus-visible) { outline: none; }
html[data-theme="dark"] *:focus-visible { outline-color: var(--vs-accent); }
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


def _uid() -> str | None:
    """Return the current user's ID from session state, or None for legacy mode."""
    return st.session_state.get("user_id")


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE INIT
# ══════════════════════════════════════════════════════════════════════════════

def _init_state():
    if "instruments" not in st.session_state:
        st.session_state.instruments = []
    if "sector_medians" not in st.session_state:
        st.session_state.sector_medians = {}
    uid = _uid()
    if "watchlist" not in st.session_state:
        st.session_state.watchlist = load_watchlist(uid)
    if "holdings" not in st.session_state:
        st.session_state.holdings = load_holdings(uid)
    if "user_name" not in st.session_state:
        st.session_state.user_name = st.session_state.get("email", st.secrets.get("APP_USERNAME", ""))
    if "prefs" not in st.session_state:
        # load_prefs always returns a complete dict (merged with defaults)
        st.session_state.prefs = load_prefs(uid)

    # ── Migrate legacy emoji market group keys in saved prefs ────────────────
    _key_map = {
        "🇬🇧 UK Stocks": "UK Stocks",
        "🇪🇺 EU Stocks": "EU Stocks",
        "🇺🇸 US Stocks": "US Stocks",
        "📦 ETFs & Index Funds": "ETFs & Index Funds",
        "💰 Money Market & Short Duration": "Money Market & Short Duration",
    }
    _groups = st.session_state.prefs.get("groups", [])
    _migrated = [_key_map.get(g, g) for g in _groups]
    if _migrated != _groups:
        st.session_state.prefs["groups"] = _migrated
        save_prefs(_uid(), st.session_state.prefs)
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
    if "dd_search_result" not in st.session_state:
        st.session_state.dd_search_result = None    # deepdive search result
    if "dd_add_target" not in st.session_state:
        st.session_state.dd_add_target = "holdings" # "holdings" or "watchlist"
    if "wl_refreshing" not in st.session_state:
        st.session_state.wl_refreshing = set()      # tickers currently being refreshed
    if "da_extra" not in st.session_state:
        st.session_state.da_extra = {}              # {ticker: extra_context_text}
    if "auto_refresh" not in st.session_state:
        st.session_state.auto_refresh = True        # on by default
    if "last_auto_refresh" not in st.session_state:
        st.session_state.last_auto_refresh = None   # ISO timestamp of last auto-refresh
    if "news_signals_map" not in st.session_state:
        st.session_state.news_signals_map = {}      # {ticker: {headline, url, sentiment, source}}


_init_state()


# ══════════════════════════════════════════════════════════════════════════════
# MARKET SCHEDULE — auto-refresh at open/close
# ══════════════════════════════════════════════════════════════════════════════

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python < 3.9

# Market open/close times in local tz (hour, minute)
MARKET_SCHEDULE = {
    "London":   {"tz": "Europe/London",   "open": (8, 0),  "close": (16, 30)},
    "Frankfurt": {"tz": "Europe/Berlin",  "open": (9, 0),  "close": (17, 30)},
    "New York": {"tz": "America/New_York", "open": (9, 30), "close": (16, 0)},
}


def _market_events_today() -> list[dict]:
    """Return list of market events (open/close) as UTC datetimes for today."""
    events = []
    utc_now = datetime.now(timezone.utc)
    for name, sched in MARKET_SCHEDULE.items():
        tz = ZoneInfo(sched["tz"])
        local_now = utc_now.astimezone(tz)
        # Only weekdays
        if local_now.weekday() >= 5:
            continue
        for event_type in ("open", "close"):
            h, m = sched[event_type]
            local_event = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
            events.append({
                "market": name,
                "type": event_type,
                "utc": local_event.astimezone(timezone.utc),
                "local_str": local_event.strftime("%H:%M %Z"),
            })
    return sorted(events, key=lambda e: e["utc"])


def _should_auto_refresh() -> tuple[bool, str]:
    """Check if we just crossed a market open/close boundary (within last 5 min)."""
    if not st.session_state.auto_refresh:
        return False, ""
    utc_now = datetime.now(timezone.utc)
    last = st.session_state.last_auto_refresh
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            # Don't refresh more than once every 20 minutes
            if (utc_now - last_dt).total_seconds() < 1200:
                return False, ""
        except Exception:
            pass

    for event in _market_events_today():
        delta = (utc_now - event["utc"]).total_seconds()
        # Fire if event was 0–5 minutes ago
        if 0 <= delta <= 300:
            label = f"{event['market']} {'opened' if event['type'] == 'open' else 'closed'}"
            return True, label
    return False, ""


def _next_market_event() -> str | None:
    """Return a human-readable string for the next market event."""
    utc_now = datetime.now(timezone.utc)
    for event in _market_events_today():
        if event["utc"] > utc_now:
            verb = "opens" if event["type"] == "open" else "closes"
            mins = int((event["utc"] - utc_now).total_seconds() / 60)
            if mins < 60:
                return f"{event['market']} {verb} in {mins}m"
            else:
                h = mins // 60
                m = mins % 60
                return f"{event['market']} {verb} in {h}h {m}m"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# FORMAT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# _f, _fmt_pct, _fmt_ratio, _fmt_price, _fmt_aum imported from utils.helpers above.

def _pill(label, value, cls=""):
    """Render an HTML metric pill for the instrument cards."""
    return f'<span class="metric-pill {cls}"><b>{value}</b> {label}</span>'


# ── Monoline SVG icon library (thin-stroke, no fill, consistent 1.5px stroke) ─
# Used throughout the app in place of emoji. All icons: viewBox 0 0 16 16,
# stroke-width 1.5, stroke-linecap/join round, fill none.
_SVG: dict[str, str] = {
    "gear": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<circle cx="8" cy="8" r="2.5"/>'
        '<path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.42 1.42'
        'M11.53 11.53l1.42 1.42M3.05 12.95l1.42-1.42M11.53 4.47l1.42-1.42"/>'
        '</svg>'
    ),
    "analyse": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#1A3A5C"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<line x1="8" y1="14" x2="8" y2="10"/>'
        '<line x1="5" y1="14" x2="11" y2="14"/>'
        '<circle cx="8" cy="6.5" r="3"/>'
        '<line x1="8" y1="1" x2="8" y2="3.5"/>'
        '</svg>'
    ),
    "trash": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<polyline points="2 4 14 4"/>'
        '<path d="M5 4V2h6v2"/>'
        '<rect x="3" y="4" width="10" height="10"/>'
        '<line x1="6" y1="7" x2="6" y2="11"/>'
        '<line x1="10" y1="7" x2="10" y2="11"/>'
        '</svg>'
    ),
    "newspaper": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<rect x="1" y="2" width="14" height="12"/>'
        '<line x1="4" y1="6" x2="12" y2="6"/>'
        '<line x1="4" y1="9" x2="12" y2="9"/>'
        '<line x1="4" y1="12" x2="8" y2="12"/>'
        '</svg>'
    ),
    "chart": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<line x1="2" y1="14" x2="14" y2="14"/>'
        '<rect x="3" y="8" width="2.5" height="6"/>'
        '<rect x="6.75" y="5" width="2.5" height="9"/>'
        '<rect x="10.5" y="2" width="2.5" height="12"/>'
        '</svg>'
    ),
    "star": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<polygon points="8 1 10 6 15 6 11 9.5 12.5 15 8 12 3.5 15 5 9.5 1 6 6 6"/>'
        '</svg>'
    ),
    "eye": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<path d="M1 8s3-5.5 7-5.5S15 8 15 8s-3 5.5-7 5.5S1 8 1 8z"/>'
        '<circle cx="8" cy="8" r="2"/>'
        '</svg>'
    ),
    "shield": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<path d="M8 1L2 3.5v4C2 11 5 14 8 15c3-1 6-4 6-7.5v-4L8 1z"/>'
        '</svg>'
    ),
    "box": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<polyline points="14 5 8 2 2 5"/>'
        '<polyline points="2 5 2 11 8 14 14 11 14 5"/>'
        '<polyline points="8 14 8 8"/>'
        '<polyline points="14 5 8 8 2 5"/>'
        '</svg>'
    ),
    "coin": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<circle cx="8" cy="8" r="6.5"/>'
        '<path d="M8 5v6M6.5 6.5h2.25a1.25 1.25 0 0 1 0 2.5H6.5"/>'
        '</svg>'
    ),
    "satellite": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<circle cx="6" cy="10" r="2.5"/>'
        '<path d="M9 7l4-4M11 3l2 2"/>'
        '<path d="M4 8C4 5.8 5.8 4 8 4"/>'
        '<path d="M2 10C2 5.4 5.4 2 10 2"/>'
        '</svg>'
    ),
    "reset": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#777777"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<path d="M2.5 8A5.5 5.5 0 1 1 5 3.4"/>'
        '<polyline points="5 1 5 4 2 4"/>'
        '</svg>'
    ),
    "apply": (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="#FFFFFF"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px;flex-shrink:0">'
        '<circle cx="8" cy="8" r="6.5"/>'
        '<polyline points="5 8 7 10 11 6"/>'
        '</svg>'
    ),
    # Severity dot indicators — monoline circle outlines, no fill, stroke colour encodes priority
    "dot-high":   (
        '<svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="#1A1A1A"'
        ' stroke-width="1.8" style="display:inline-block;vertical-align:-1px;flex-shrink:0">'
        '<circle cx="5" cy="5" r="3.5"/></svg>'
    ),
    "dot-medium": (
        '<svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="#444444"'
        ' stroke-width="1.8" style="display:inline-block;vertical-align:-1px;flex-shrink:0">'
        '<circle cx="5" cy="5" r="3.5"/></svg>'
    ),
    "dot-low":    (
        '<svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="#777777"'
        ' stroke-width="1.8" style="display:inline-block;vertical-align:-1px;flex-shrink:0">'
        '<circle cx="5" cy="5" r="3.5"/></svg>'
    ),
    "dot-info":   (
        '<svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="#AAAAAA"'
        ' stroke-width="1.8" style="display:inline-block;vertical-align:-1px;flex-shrink:0">'
        '<circle cx="5" cy="5" r="3.5"/></svg>'
    ),
}

def _svg(name: str, label: str = "") -> str:
    """Return SVG icon string, optionally followed by a label with non-breaking space."""
    icon = _SVG.get(name, "")
    return f'{icon}&nbsp;{label}' if label else icon


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

def _build_quality_thresholds():
    # scoring.py expects thresholds in the same units it uses internally:
    #   min_roe / min_profit_margin → percent (e.g. 8 means 8%), because _passes_quality does roe*100 < min_roe
    #   max_de                      → ratio (e.g. 3 means 3.0×)
    #   require_pos_fcf             → bool
    # Key names must match exactly what _passes_quality() reads via qt.get(...)
    p = st.session_state.prefs
    return {
        "min_roe":           p.get("min_roe", 10),           # % — do NOT divide; scoring.py does roe*100 < min_roe
        "max_de":            p.get("max_de",   2),           # ratio
        "min_profit_margin": p.get("min_profit_margin", 2),  # % — do NOT divide; scoring.py does pm*100 < min_pm
        "require_pos_fcf":   p.get("require_pos_fcf", True),
    }


def _build_scoring_weights() -> dict:
    """
    Returns a flat weight dict keyed exactly as scoring.py expects (wt_* prefix).
    scoring.py reads e.g. weights.get("wt_pe", 30), weights.get("wt_evebitda", 30),
    so the keys here must match those names exactly.
    """
    p = st.session_state.prefs
    return {
        # Non-financial stocks
        "wt_pe":       p.get("wt_pe",       30),
        "wt_pb":       p.get("wt_pb",       20),
        "wt_evebitda": p.get("wt_evebitda", 20),
        "wt_pfcf":     p.get("wt_pfcf",     25),   # P/FCF weight (separate from P/E)
        "wt_divyield": p.get("wt_divyield", 15),
        "wt_52w":      p.get("wt_52w",      15),
        # Financial stocks
        "wt_fin_ptb":   p.get("wt_fin_ptb",   35),
        "wt_fin_roe":   p.get("wt_fin_roe",   30),
        "wt_fin_yield": p.get("wt_fin_yield", 20),
        "wt_fin_52w":   p.get("wt_fin_52w",   15),
        # ETFs
        "wt_etf_aum": p.get("wt_etf_aum", 35),
        "wt_etf_ter": p.get("wt_etf_ter", 35),
        "wt_etf_ret": p.get("wt_etf_ret", 20),
        "wt_etf_mom": p.get("wt_etf_mom", 10),
        # Money market
        "wt_mm_yield": p.get("wt_mm_yield", 60),
        "wt_mm_aum":   p.get("wt_mm_aum",   25),
        "wt_mm_ter":   p.get("wt_mm_ter",   15),
    }


def load_all_data(groups: list, progress_cb=None) -> tuple:
    """Fetch all instruments, score them, compute sector medians."""
    raw = []
    # Include custom tickers in total count for progress bar
    _custom_tks = load_custom_tickers(_uid())
    total_tickers = (
        sum(len(UNIVERSE[g]["tickers"]) for g in groups if g in UNIVERSE)
        + len(_custom_tks)
    )
    done = 0

    for group in groups:
        if group not in UNIVERSE:
            continue
        meta = UNIVERSE[group]
        for ticker, name in meta["tickers"].items():
            needs_live_fetch = not _cache_is_fresh(ticker)
            inst = fetch_one(ticker, name, meta["asset_class"], group)
            raw.append(inst)
            done += 1
            if progress_cb:
                progress_cb(done / max(total_tickers, 1),
                            f"Loading {group} — {name}")
            # Pace live fetches to reduce Yahoo Finance rate-limiting (HTTP 429).
            # No sleep needed if data came from local cache.
            if needs_live_fetch and inst.get("ok") and done < total_tickers:
                time.sleep(0.4)  # 400 ms between live fetches (~2.5 req/s)

    # ── Custom user tickers ───────────────────────────────────────────────────
    for ct in _custom_tks:
        needs_live_fetch = not _cache_is_fresh(ct["ticker"])
        inst = fetch_one(ct["ticker"], ct.get("name", ct["ticker"]),
                         ct.get("asset_class", "Stock"), ct.get("group_name", "Custom"))
        raw.append(inst)
        done += 1
        if progress_cb:
            progress_cb(done / max(total_tickers, 1),
                        f"Loading custom — {ct['ticker']}")
        if needs_live_fetch and inst.get("ok") and done < total_tickers:
            time.sleep(0.4)

    sector_medians = compute_sector_medians(raw)
    qt = _build_quality_thresholds()
    sw = _build_scoring_weights()
    scored = score_all(raw, sector_medians, qt, sw)
    scored = add_verdicts(scored, sector_medians)
    scored = enrich_with_signals(scored)
    return scored, sector_medians


def _auto_load_from_cache(groups: list):
    """Load instruments from SQLite cache without hitting Yahoo Finance.
    Loads ALL available cached data (even if prices are slightly stale) so
    the app is instantly usable on startup. A stale-data banner in the
    sidebar prompts the user to refresh when needed.
    """
    raw = []
    for group in groups:
        if group not in UNIVERSE:
            continue
        meta = UNIVERSE[group]
        for ticker, name in meta["tickers"].items():
            inst = _load_cache(ticker)   # returns data regardless of age
            if inst:
                inst["name"]        = name
                inst["group"]       = group
                inst["asset_class"] = meta["asset_class"]
                inst.setdefault("ok", True)
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


# ── Startup: load from cache if available ──────────────────────────────────
if not st.session_state.instruments and any_cache_exists():
    groups = st.session_state.prefs.get("groups", list(UNIVERSE.keys())[:2])
    _auto_load_from_cache(groups)

# ── Auto-refresh at market open/close ──────────────────────────────────────
# Poll every 5 minutes (300 000 ms). On Streamlit Cloud the app is kept alive
# by user sessions; the component just triggers a re-run to check the schedule.
try:
    from streamlit_autorefresh import st_autorefresh   # pip install streamlit-autorefresh
    st_autorefresh(interval=300_000, key="market_clock")
except ImportError:
    pass  # Graceful degradation if package not installed

_do_auto_refresh, _refresh_reason = _should_auto_refresh()
if _do_auto_refresh:
    _groups = st.session_state.prefs.get("groups", list(UNIVERSE.keys())[:2])
    if _groups:
        _prog = st.progress(0, text=f"Auto-refresh: {_refresh_reason}…")
        def _auto_cb(pct, msg):
            _prog.progress(pct, text=msg)
        _scored, _sm = load_all_data(_groups, progress_cb=_auto_cb)
        _prog.empty()
        st.session_state.instruments    = _scored
        st.session_state.sector_medians = _sm
        st.session_state.last_fetch     = datetime.now().strftime("%H:%M  %d %b %Y")
        st.session_state.last_auto_refresh = datetime.now(timezone.utc).isoformat()
        # Snapshot today's real scores into history
        try:
            snapshot_scores(_scored)
        except Exception:
            pass
        _ok = [x for x in _scored if x.get("ok")]
        save_scan_summary({
            "total": len(_ok),
            "stocks_passing_quality": sum(
                1 for x in _ok if x.get("asset_class") == "Stock" and x.get("quality_passes")
            ),
            "strong_value":  sum(1 for x in _ok if (_f(x.get("score")) or 0) >= 75),
            "top_picks": [
                {"ticker": x["ticker"], "name": x["name"],
                 "score": x.get("score"), "verdict": x.get("verdict", "")}
                for x in sorted(_ok, key=lambda r: _f(r.get("score")) or 0, reverse=True)[:5]
            ],
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
        st.session_state.toast = (f"Data refreshed — {_refresh_reason}", "info")
        st.rerun()


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
# TOP NAVIGATION BAR
# ══════════════════════════════════════════════════════════════════════════════

def _render_topnav():
    """Render the sticky horizontal top navigation bar."""
    _latest_signals  = load_latest_signals()
    _high_count      = sum(1 for s in _latest_signals if s.get("severity") == "high")
    _scoring_changed = st.session_state.scoring_changed
    current_page     = st.session_state.page

    nav_pages = [
        ("Home",     "home"),
        ("Deepdive", "deepdive"),
        ("Screen",   "screener"),
        ("Compare",  "compare"),
        ("Briefing", "briefing"),
    ]

    links_html = ""
    for label, key in nav_pages:
        display = label
        if key == "briefing" and _high_count > 0:
            display = f'Briefing <span style="display:inline-block;background:transparent;border:1px solid #1A3A5C;color:#1A3A5C;font-size:9px;font-weight:700;padding:1px 5px;letter-spacing:0.05em;vertical-align:1px">{_high_count}</span>'
        active_cls = " active" if current_page == key else ""
        links_html += (
            f'<span class="vs-topnav-link{active_cls}" '
            f'id="topnav_{key}">{display}</span>'
        )

    settings_dot = '<span class="vs-topnav-settings-dot"> ●</span>' if _scoring_changed else ""
    settings_cls = " active" if current_page == "settings" else ""

    # SVG icons for nav controls
    _moon_svg = (
        '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor"'
        ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"'
        ' style="display:inline-block;vertical-align:-2px">'
        '<path d="M12 9A6 6 0 0 1 7 3a6 6 0 1 0 5 6z"/>'
        '</svg>'
    )
    _hamburger_svg = (
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        ' stroke-width="1.5" stroke-linecap="round" style="display:block">'
        '<path d="M3 12H21M3 6H21M3 18H21"/>'
        '</svg>'
    )

    nav_html = (
        f'<div class="vs-topnav" data-page="{current_page}">'
        f'<span class="vs-topnav-wordmark">Value Screener</span>'
        f'<div class="vs-topnav-links">{links_html}</div>'
        f'<div style="display:flex;align-items:center;flex-shrink:0;gap:4px">'
        f'<button class="vs-theme-toggle-btn" id="vs_theme_toggle"'
        f' title="Toggle dark mode" aria-label="Toggle dark mode">{_moon_svg}</button>'
        f'<span class="vs-topnav-settings{settings_cls}" id="topnav_settings">'
        f'Settings{settings_dot}</span>'
        f'<button class="vs-hamburger" id="vs_hamburger"'
        f' aria-label="Open navigation" aria-expanded="false">{_hamburger_svg}</button>'
        f'</div>'
        f'</div>'
    )
    st.markdown(nav_html, unsafe_allow_html=True)

    # ── Hidden Streamlit buttons (actual nav triggers) ──────────────────────
    st.markdown(
        '<style>'
        '.vs-nav-sentinel + div,'
        '.vs-nav-sentinel + div > div,'
        '.vs-nav-sentinel ~ div[data-testid="stHorizontalBlock"],'
        '.vs-nav-sentinel ~ [data-testid="stHorizontalBlock"] {'
        '  display:none !important;'
        '  height:0 !important;'
        '  overflow:hidden !important;'
        '  margin:0 !important;'
        '  padding:0 !important;'
        '}'
        '</style>'
        '<div class="vs-nav-sentinel" style="height:0;overflow:hidden;margin:0;padding:0"></div>',
        unsafe_allow_html=True,
    )

    all_nav = nav_pages + [("Settings", "settings")]
    btn_cols = st.columns(len(all_nav))
    for i, (label, key) in enumerate(all_nav):
        with btn_cols[i]:
            if st.button(label, key=f"topnav_btn_{key}"):
                st.session_state.page = key
                st.rerun()

    st.markdown(
        '<div class="vs-nav-sentinel-end" style="height:0;overflow:hidden;margin:0;padding:0"></div>',
        unsafe_allow_html=True,
    )

    # ── JS: nav wiring + dark mode + hamburger drawer + density ──────────────
    js = """
    <script>
    (function() {
      var NAV_KEYS = ['home','deepdive','screener','compare','briefing','settings'];

      // ─── Helpers ────────────────────────────────────────────────────────────
      function getCurrentPage() {
        var nav = document.querySelector('.vs-topnav[data-page]');
        return nav ? nav.getAttribute('data-page') : 'home';
      }

      // ─── Dark mode ──────────────────────────────────────────────────────────
      function initTheme() {
        var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        var saved = localStorage.getItem('vs-theme');
        var theme = saved || (prefersDark ? 'dark' : 'light');
        document.documentElement.setAttribute('data-theme', theme);
        updateThemeToggleBtn(theme);
        return theme;
      }

      function updateThemeToggleBtn(theme) {
        var btn = document.getElementById('vs_theme_toggle');
        if (!btn) return;
        var moonSvg = '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-2px"><path d="M12 9A6 6 0 0 1 7 3a6 6 0 1 0 5 6z"/></svg>';
        var sunSvg = '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="display:inline-block;vertical-align:-2px"><circle cx="8" cy="8" r="3"/><line x1="8" y1="1" x2="8" y2="3"/><line x1="8" y1="13" x2="8" y2="15"/><line x1="1" y1="8" x2="3" y2="8"/><line x1="13" y1="8" x2="15" y2="8"/><line x1="3.5" y1="3.5" x2="5" y2="5"/><line x1="11" y1="11" x2="12.5" y2="12.5"/><line x1="12.5" y1="3.5" x2="11" y2="5"/><line x1="5" y1="11" x2="3.5" y2="12.5"/></svg>';
        btn.innerHTML = (theme === 'dark') ? sunSvg : moonSvg;
        btn.title = (theme === 'dark') ? 'Switch to light mode' : 'Switch to dark mode';
        btn.setAttribute('aria-label', btn.title);
      }

      function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('vs-theme', theme);
        updateThemeToggleBtn(theme);
        syncDrawerThemeBtns(theme);
      }

      function toggleTheme() {
        var current = document.documentElement.getAttribute('data-theme') || 'light';
        setTheme(current === 'dark' ? 'light' : 'dark');
      }

      function wireThemeBtn() {
        var btn = document.getElementById('vs_theme_toggle');
        if (btn && !btn._vsThemeWired) {
          btn._vsThemeWired = true;
          btn.addEventListener('click', toggleTheme);
        }
      }

      if (window.matchMedia) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
          if (!localStorage.getItem('vs-theme')) {
            setTheme(e.matches ? 'dark' : 'light');
          }
        });
      }

      // ─── Density ────────────────────────────────────────────────────────────
      function initDensity() {
        var saved = localStorage.getItem('vs-density') || 'comfortable';
        document.documentElement.setAttribute('data-density', saved);
        return saved;
      }

      function setDensity(density) {
        document.documentElement.setAttribute('data-density', density);
        localStorage.setItem('vs-density', density);
        syncDrawerDensityBtns(density);
      }

      function syncDrawerDensityBtns(density) {
        document.querySelectorAll('.vs-drawer-btn[data-density-val]').forEach(function(btn) {
          btn.classList.toggle('active', btn.getAttribute('data-density-val') === density);
        });
      }

      function syncDrawerThemeBtns(theme) {
        document.querySelectorAll('.vs-drawer-btn[data-theme-val]').forEach(function(btn) {
          btn.classList.toggle('active', btn.getAttribute('data-theme-val') === theme);
        });
      }

      // ─── Mobile drawer ───────────────────────────────────────────────────────
      function createDrawer() {
        if (document.getElementById('vs_mobile_drawer')) return;

        var currentPage = getCurrentPage();
        var currentTheme = document.documentElement.getAttribute('data-theme') || 'light';
        var currentDensity = document.documentElement.getAttribute('data-density') || 'comfortable';

        var pageLinks = [
          {label: 'Home',     key: 'home'},
          {label: 'Deepdive', key: 'deepdive'},
          {label: 'Screen',   key: 'screener'},
          {label: 'Compare',  key: 'compare'},
          {label: 'Briefing', key: 'briefing'},
          {label: 'Settings', key: 'settings'},
        ];

        var navHtml = pageLinks.map(function(p) {
          var cls = p.key === currentPage ? ' active' : '';
          return '<div class="vs-drawer-navlink' + cls + '" data-nav-key="' + p.key + '" role="button" tabindex="0">' + p.label + '</div>';
        }).join('');

        function densityBtnCls(d) { return ' vs-drawer-btn' + (currentDensity === d ? ' active' : ''); }
        function themeBtnCls(t)   { return ' vs-drawer-btn' + (currentTheme   === t ? ' active' : ''); }

        var drawer = document.createElement('div');
        drawer.id = 'vs_mobile_drawer';
        drawer.className = 'vs-mobile-drawer';
        drawer.setAttribute('role', 'navigation');
        drawer.setAttribute('aria-label', 'Site navigation');
        drawer.innerHTML =
          '<div class="vs-drawer-header">' +
            '<span class="vs-drawer-wordmark">Value Screener</span>' +
            '<button class="vs-drawer-close" id="vs_drawer_close" aria-label="Close menu">' +
              '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">' +
              '<path d="M3 3L13 13M13 3L3 13"/></svg>' +
            '</button>' +
          '</div>' +
          navHtml +
          '<div class="vs-drawer-section-title">Density</div>' +
          '<div class="vs-drawer-btn-row">' +
            '<button class="' + densityBtnCls('compact')     + '" data-density-val="compact">Compact</button>' +
            '<button class="' + densityBtnCls('comfortable') + '" data-density-val="comfortable">Default</button>' +
            '<button class="' + densityBtnCls('spacious')    + '" data-density-val="spacious">Spacious</button>' +
          '</div>' +
          '<div class="vs-drawer-section-title">Theme</div>' +
          '<div class="vs-drawer-btn-row">' +
            '<button class="' + themeBtnCls('light') + '" data-theme-val="light">Light</button>' +
            '<button class="' + themeBtnCls('dark')  + '" data-theme-val="dark">Dark</button>' +
          '</div>';

        var backdrop = document.createElement('div');
        backdrop.id = 'vs_nav_backdrop';
        backdrop.className = 'vs-nav-backdrop';

        document.body.appendChild(backdrop);
        document.body.appendChild(drawer);

        document.getElementById('vs_drawer_close').addEventListener('click', closeDrawer);
        backdrop.addEventListener('click', closeDrawer);

        drawer.querySelectorAll('[data-nav-key]').forEach(function(link) {
          link.addEventListener('click', function() {
            closeDrawer();
            triggerNavBtn(link.getAttribute('data-nav-key'));
          });
          link.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              closeDrawer();
              triggerNavBtn(link.getAttribute('data-nav-key'));
            }
          });
        });

        drawer.querySelectorAll('[data-density-val]').forEach(function(btn) {
          btn.addEventListener('click', function() { setDensity(btn.getAttribute('data-density-val')); });
        });

        drawer.querySelectorAll('[data-theme-val]').forEach(function(btn) {
          btn.addEventListener('click', function() { setTheme(btn.getAttribute('data-theme-val')); });
        });

        document.addEventListener('keydown', function(e) {
          if (e.key === 'Escape') closeDrawer();
        });
      }

      function openDrawer() {
        createDrawer();
        var drawer = document.getElementById('vs_mobile_drawer');
        var backdrop = document.getElementById('vs_nav_backdrop');
        if (drawer) drawer.classList.add('open');
        if (backdrop) backdrop.classList.add('visible');
        document.body.style.overflow = 'hidden';
        var hbg = document.getElementById('vs_hamburger');
        if (hbg) hbg.setAttribute('aria-expanded', 'true');
      }

      function closeDrawer() {
        var drawer = document.getElementById('vs_mobile_drawer');
        var backdrop = document.getElementById('vs_nav_backdrop');
        if (drawer) drawer.classList.remove('open');
        if (backdrop) backdrop.classList.remove('visible');
        document.body.style.overflow = '';
        var hbg = document.getElementById('vs_hamburger');
        if (hbg) hbg.setAttribute('aria-expanded', 'false');
      }

      function wireHamburger() {
        var btn = document.getElementById('vs_hamburger');
        if (btn && !btn._vsHamburgerWired) {
          btn._vsHamburgerWired = true;
          btn.addEventListener('click', function() {
            var drawer = document.getElementById('vs_mobile_drawer');
            if (drawer && drawer.classList.contains('open')) {
              closeDrawer();
            } else {
              openDrawer();
            }
          });
        }
      }

      // ─── Navigation wiring ──────────────────────────────────────────────────
      function triggerNavBtn(key) {
        var labelMap = {
          'home': 'home', 'deepdive': 'deepdive', 'screener': 'screen',
          'compare': 'compare', 'briefing': 'briefing', 'settings': 'settings'
        };
        var target = labelMap[key] || key;
        var btns = document.querySelectorAll('button');
        for (var i = 0; i < btns.length; i++) {
          if (btns[i].innerText.trim().toLowerCase() === target) {
            btns[i].click();
            break;
          }
        }
      }

      function hideNavBtns() {
        NAV_KEYS.forEach(function(key) {
          document.querySelectorAll('button').forEach(function(btn) {
            var label = btn.innerText.trim().toLowerCase();
            if (label === key || (key === 'screener' && label === 'screen')) {
              var el = btn;
              for (var depth = 0; depth < 8; depth++) {
                el = el.parentElement;
                if (!el) break;
                var tid = el.getAttribute('data-testid') || '';
                if (tid === 'stHorizontalBlock') {
                  el.style.cssText = 'display:none!important;height:0!important;overflow:hidden!important;margin:0!important;padding:0!important;';
                  break;
                }
              }
            }
          });
        });
      }

      function wireNavSpans() {
        var pairs = [
          ['topnav_home',     'home'],
          ['topnav_deepdive', 'deepdive'],
          ['topnav_screener', 'screener'],
          ['topnav_compare',  'compare'],
          ['topnav_briefing', 'briefing'],
          ['topnav_settings', 'settings'],
        ];
        pairs.forEach(function(p) {
          var span = document.getElementById(p[0]);
          if (!span || span._wired) return;
          span._wired = true;
          span.style.cursor = 'pointer';
          span.addEventListener('click', function() { triggerNavBtn(p[1]); });
        });
        hideNavBtns();
      }

      // ─── Main init ───────────────────────────────────────────────────────────
      function vsInit() {
        initTheme();
        initDensity();
        wireThemeBtn();
        wireHamburger();
        wireNavSpans();
        // Recreate drawer on each render (Streamlit re-runs) to reflect current page
        var existing = document.getElementById('vs_mobile_drawer');
        if (existing) existing.remove();
        var existingBd = document.getElementById('vs_nav_backdrop');
        if (existingBd) existingBd.remove();
      }

      var obs = new MutationObserver(vsInit);
      obs.observe(document.body, {childList: true, subtree: true});
      vsInit();
    })();
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)


_render_topnav()


# ── Mobile bottom tab bar ──────────────────────────────────────────────────────
# Rendered below topnav; hidden on desktop via @media. Uses the same hidden
# Streamlit buttons as the topnav — JS clicks them when a tab is tapped.
def _render_mobile_bottombar():
    _cur = st.session_state.page
    _tabs = [
        ("home",     "Home",     '<path d="M3 9.5L12 3l9 6.5V20a1 1 0 01-1 1H4a1 1 0 01-1-1V9.5z"/><path d="M9 21V12h6v9"/>'),
        ("screener", "Screen",   '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><path d="M11 8v6M8 11h6"/>'),
        ("deepdive", "Deepdive", '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>'),
        ("briefing", "Briefing", '<path d="M4 4h16v12H4z"/><path d="M8 20h8M12 16v4"/>'),
        ("settings", "Settings", '<circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>'),
    ]
    tabs_html = ""
    for key, label, svg_path in _tabs:
        active_cls = " active" if _cur == key else ""
        tabs_html += (
            f'<button class="vs-mobile-tab{active_cls}" id="mbt_{key}" aria-label="{label}">'
            f'<svg viewBox="0 0 24 24">{svg_path}</svg>'
            f'<span>{label}</span>'
            f'</button>'
        )
    st.markdown(
        f'<div class="vs-mobile-bottombar">{tabs_html}</div>'
        f'<script>'
        f'(function(){{'
        f'  var tabs=[{",".join(repr(k) for k,_,__ in _tabs)}];'
        f'  tabs.forEach(function(k){{'
        f'    var btn=document.getElementById("mbt_"+k);'
        f'    if(!btn||btn._mbt)return;'
        f'    btn._mbt=true;'
        f'    btn.addEventListener("click",function(){{'
        f'      var nb=document.querySelectorAll("[data-testid=\'stButton\'] button");'
        f'      nb.forEach(function(b){{'
        f'        if(b.innerText.trim().toLowerCase()===k.toLowerCase()||'
        f'           b.getAttribute("data-key")==="topnav_btn_"+k){{b.click();}}'
        f'      }});'
        f'    }});'
        f'  }});'
        f'}})();</script>',
        unsafe_allow_html=True,
    )

_render_mobile_bottombar()


# ══════════════════════════════════════════════════════════════════════════════
# DATA CONTROLS (Markets + Filters) — rendered inline on relevant pages
# ══════════════════════════════════════════════════════════════════════════════

def _render_data_controls():
    """Markets selector + refresh button, shown as a top-of-page control strip."""
    chosen_groups = st.session_state.prefs.get("groups", ["UK Stocks", "ETFs & Index Funds"])

    with st.expander("Markets & Data", expanded=not st.session_state.instruments):
        chosen_groups = st.multiselect(
            "Markets to load",
            list(UNIVERSE.keys()),
            default=chosen_groups,
            help="Select which markets to include in the screen",
        )
        if set(chosen_groups) != set(st.session_state.prefs.get("groups", [])):
            st.session_state.prefs["groups"] = chosen_groups
            save_prefs(_uid(), st.session_state.prefs)

        _age = cache_age_hours()
        col_info, col_btn, col_toggle = st.columns([3, 2, 3])
        with col_info:
            if _age is not None:
                _freshness = "Live" if _age < 1 else (f"{int(_age)}h old" if _age < 8 else f"Stale — {int(_age)}h")
                st.caption(f"Data: {_freshness}")
                if _age >= 6 and st.session_state.instruments:
                    st.markdown(
                        f'<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-left:3px solid #777777;'
                        f'padding:8px 12px;font-family:var(--vs-sans),sans-serif;font-size:12px;color:#444444;'
                        f'margin-top:4px;">Prices {int(_age)}h old — refresh for live data.</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No data loaded")
        with col_btn:
            fetch_label = "Refresh Now" if st.session_state.instruments else "Load Data"
            if st.button(fetch_label, type="primary", use_container_width=True, key="data_ctrl_fetch"):
                if chosen_groups:
                    prog = st.progress(0, text="Starting…")
                    def _cb(pct, msg):
                        prog.progress(pct, text=msg)
                    scored, sm = load_all_data(chosen_groups, progress_cb=_cb)
                    prog.empty()
                    st.session_state.instruments    = scored
                    st.session_state.sector_medians = sm
                    st.session_state.last_fetch     = datetime.now().strftime("%H:%M  %d %b %Y")
                    st.session_state.last_auto_refresh = datetime.now(timezone.utc).isoformat()
                    # Snapshot today's real scores into history
                    try:
                        snapshot_scores(scored)
                    except Exception:
                        pass
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
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    })
                    st.rerun()
                else:
                    st.markdown(
                        '<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-left:3px solid #777777;'
                        'padding:8px 12px;font-family:var(--vs-sans),sans-serif;font-size:12px;color:#444444;'
                        'margin-top:4px;">Select at least one market above.</div>',
                        unsafe_allow_html=True,
                    )
        with col_toggle:
            _next_event = _next_market_event()
            _auto_on = st.session_state.auto_refresh
            _auto_label = "Auto-refresh on" if _auto_on else "Auto-refresh off"
            if st.toggle(_auto_label, value=_auto_on, key="auto_refresh_toggle",
                         help="Automatically refresh prices at each market open and close"):
                st.session_state.auto_refresh = True
            else:
                st.session_state.auto_refresh = False
            if _next_event and st.session_state.auto_refresh:
                st.caption(f"Next: {_next_event}")


def _render_screen_filters():
    """Filter sliders for the Screener page."""
    with st.expander("Filters", expanded=False):
        p = st.session_state.prefs
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            min_score = st.slider("Min score", 0, 100, int(p.get("min_score", 0)), 5,
                                  help="Only show instruments scoring at least this")
        with fc2:
            min_yield = st.slider("Min yield (%)", 0.0, 8.0, float(p.get("min_yield", 0.0)), 0.5,
                                  help="Minimum dividend or distribution yield")
        with fc3:
            max_pe = st.slider("Max P/E", 5, 100, int(p.get("max_pe", 100)), 5,
                               help="Filter out expensive stocks. 100 = show all.")
        with fc4:
            max_ter = st.slider("Max TER (%)", 0.05, 1.5, float(p.get("max_ter", 1.5)), 0.05,
                                help="Maximum annual fee for ETFs")

        with st.expander("Quality gate"):
            st.caption("Stocks must pass ALL of these to appear.")
            qc1, qc2 = st.columns(2)
            with qc1:
                min_roe = st.slider("Min ROE (%)", 0, 30, int(p.get("min_roe", 10)), 1,
                                    help="Return on Equity")
            with qc2:
                max_de = st.slider("Max Debt/Equity", 0, 10, int(p.get("max_de", 2)), 1,
                                   help="Financial leverage")
            if min_roe != p.get("min_roe") or max_de != p.get("max_de"):
                p["min_roe"] = min_roe
                p["max_de"]  = max_de
                save_prefs(_uid(), p)

        changed = (min_score != p.get("min_score") or min_yield != p.get("min_yield")
                   or max_pe != p.get("max_pe") or max_ter != p.get("max_ter"))
        if changed:
            p["min_score"] = min_score
            p["min_yield"] = min_yield
            p["max_pe"]    = max_pe
            p["max_ter"]   = max_ter
            save_prefs(_uid(), p)


# ══════════════════════════════════════════════════════════════════════════════
# TOAST NOTIFICATIONS
# ══════════════════════════════════════════════════════════════════════════════

def _show_toast():
    """Render and clear any pending toast notification."""
    if st.session_state.toast:
        msg, kind = st.session_state.toast
        if kind == "success":
            st.toast(msg, icon=None)
        elif kind == "info":
            st.toast(msg, icon=None)
        elif kind == "warning":
            st.toast(msg, icon=None)
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

    # Friendly display names for score component keys
    LABELS = {
        "ev_ebitda_score": "EV/EBITDA",
        "pfcf_score":      "P/Free Cash Flow",
        "pe_score":        "P/E ratio",
        "pb_score":        "P/Book",
        "ptb_score":       "P/Tangible Book",
        "roe_score":       "ROE vs peers",
        "div_score":       "Dividend yield",
        "wk52_score":      "52-week position",
    }

    rows_html = ""
    for key, item in components.items():
        # New format: item is a plain float (or None)
        # Old format: item is a dict with "score" and "weight" keys
        if isinstance(item, dict):
            score  = item.get("score")
            weight = item.get("weight", 0)
            weight_str = f"{weight}%"
        else:
            score  = float(item) if item is not None else None
            weight_str = ""

        label = LABELS.get(key, key.replace("_score", "").replace("_", " ").title())

        if score is None:
            bar_html = '<div class="breakdown-bar-bg"><div class="breakdown-bar-fill" style="width:0%"></div></div>'
            score_str = "no data"
            label_col = "#AAAAAA"
        else:
            pct   = max(min(score, 100), 0)
            bar_html = (f'<div class="breakdown-bar-bg">'
                        f'<div class="breakdown-bar-fill" style="width:{pct:.0f}%"></div>'
                        f'</div>')
            score_str = f"{score:.0f}/100"
            label_col = "#444444"

        rows_html += (f'<div class="breakdown-row">'
                      f'<span style="min-width:160px;color:{label_col}">{label}</span>'
                      f'{bar_html}'
                      f'<span style="min-width:60px;text-align:right;color:{label_col}">{score_str}</span>'
                      f'<span style="min-width:42px;text-align:right;color:#555">{weight_str}</span>'
                      f'</div>')

    is_fin = inst.get("is_financial", False)
    coverage = inst.get("score_coverage")
    note = '<div style="font-size:0.7rem;color:#555;margin-top:6px">Scored relative to sector peers'
    if is_fin:
        note += " · Financial sector model (P/TangBook + ROE)"
    if coverage is not None:
        note += f" · Data coverage {coverage*100:.0f}%"
    note += "</div>"
    st.markdown(f'<div style="padding:4px 0">{rows_html}{note}</div>', unsafe_allow_html=True)

    # ── Quality gate detail ────────────────────────────────────────────────────
    ac = inst.get("asset_class", "")
    if ac == "Stock":
        passes  = inst.get("quality_passes", True)
        reasons = inst.get("quality_fail_reasons", [])
        flags   = inst.get("quality_flags", [])

        # Gate metrics with their actual values
        roe_val   = inst.get("roe")
        de_val    = inst.get("debt_equity")
        pm_val    = inst.get("profit_margin")
        fcf_val   = inst.get("free_cashflow")
        accrual   = inst.get("accrual_ratio")      # may be None if not computed
        altman    = inst.get("altman_z")            # may be None

        gate_icon = "✅ Quality gate: PASS" if passes else "⚠️ Quality gate: FAIL"
        gate_col  = "#1A1A1A" if passes else "#777777"

        gate_rows = []
        if roe_val is not None:
            roe_pct = roe_val * 100 if abs(roe_val) < 5 else roe_val
            gate_rows.append(f"ROE {roe_pct:.1f}%")
        if de_val is not None:
            gate_rows.append(f"D/E {de_val:.2f}x")
        if pm_val is not None:
            pm_pct = pm_val * 100 if abs(pm_val) < 2 else pm_val
            gate_rows.append(f"Margin {pm_pct:.1f}%")
        if fcf_val is not None:
            fcf_sign = "+" if fcf_val >= 0 else "−"
            fcf_abs  = abs(fcf_val)
            fcf_disp = f"{fcf_abs/1e9:.1f}bn" if fcf_abs >= 1e9 else f"{fcf_abs/1e6:.0f}m" if fcf_abs >= 1e6 else f"{fcf_abs:,.0f}"
            gate_rows.append(f"FCF {fcf_sign}{fcf_disp}")
        if accrual is not None:
            gate_rows.append(f"Accrual ratio {accrual:.3f}")
        if altman is not None:
            z_risk = " (distress)" if altman < 1.81 else " (grey zone)" if altman < 2.99 else " (safe)"
            gate_rows.append(f"Altman Z {altman:.2f}{z_risk}")

        metrics_str = "  ·  ".join(gate_rows) if gate_rows else "—"
        fail_html = ""
        if reasons:
            fail_html = (
                f'<div style="color:#777777;font-size:0.72rem;margin-top:3px">'
                f'Fail reasons: {" · ".join(reasons)}</div>'
            )
        flag_html = ""
        if flags:
            flag_html = (
                f'<div style="color:#555;font-size:0.72rem;margin-top:2px">'
                f'Flags: {" · ".join(flags)}</div>'
            )
        st.markdown(
            f'<div style="margin-top:8px;padding:8px 12px;background:#F8F8F6;'
            f'border:1px solid #D4D4D2;border-left:3px solid {"#1A3A5C" if passes else "#777777"}">'
            f'<div style="font-weight:600;font-size:0.78rem;color:{gate_col}">{gate_icon}</div>'
            f'<div style="font-size:0.72rem;color:#444444;margin-top:2px">{metrics_str}</div>'
            f'{fail_html}{flag_html}'
            f'</div>',
            unsafe_allow_html=True,
        )


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

    # Colour logic — monochrome only, no red/green signals
    def rate_col(v):  return "#1A1A1A" if v is not None else "#AAAAAA"
    def curve_col(v): return "#777777" if (v is not None and v < 0) else "#1A1A1A" if (v is not None and v > 0.5) else "#444444"
    def vix_col(v):   return "#777777" if (v is not None and v > 30) else "#444444" if (v is not None and v > 20) else "#1A1A1A"
    def hy_col(v):    return "#777777" if (v is not None and v > 500) else "#444444" if (v is not None and v > 350) else "#1A1A1A"

    if ffr is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(ffr)}">{ffr:.2f}%</div><div class="macro-item-lbl">Fed Funds</div></div>')
    if boe is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(boe)}">{boe:.2f}%</div><div class="macro-item-lbl">BoE Rate</div></div>')
    if dgs10 is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(dgs10)}">{dgs10:.2f}%</div><div class="macro-item-lbl">US 10Y</div></div>')
    if gilt is not None:
        items.append(f'<div class="macro-item"><div class="macro-item-val" style="color:{rate_col(gilt)}">{gilt:.2f}%</div><div class="macro-item-lbl">UK Gilt 10Y</div></div>')
    if t10y2y is not None:
        label = "Inverted" if t10y2y < 0 else "Yield Curve"
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
    tone_col    = "#777777" if high_count >= 2 else "#444444" if high_count == 1 else "#1A1A1A"
    tone_lbl    = "Cautious" if high_count >= 2 else "Mixed" if high_count == 1 else "Constructive"
    tone_item   = (f'<div class="macro-item" style="border-right:1px solid #D4D4D2;padding-right:20px;margin-right:4px">'
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


def _get_news_signals_map() -> dict:
    """
    Lazily build and cache a {ticker: signal_dict} map for the current session.
    Pulls from get_signals_from_news() using the loaded instruments as the universe.
    Returns {} if finnews is unavailable or instruments not yet loaded.
    """
    if st.session_state.news_signals_map:
        return st.session_state.news_signals_map
    instruments = st.session_state.get("instruments") or []
    if not instruments:
        return {}
    try:
        signals = get_signals_from_news(instruments, max_signals=50)
        smap = {}
        for sig in signals:
            t = sig.get("ticker")
            if t and t not in smap:   # keep strongest-sentiment signal per ticker
                smap[t] = sig
        st.session_state.news_signals_map = smap
        return smap
    except Exception:
        return {}


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
    # ── Phase 1: Risk flags ───────────────────────────────────────────────────
    risk_flags_html = ""
    risk_flags = inst.get("risk_flags", [])
    if risk_flags and ac == "Stock":
        flag_parts = []
        for rf in risk_flags:
            cls = "risk-flag distress" if rf.get("type") == "distress" else "risk-flag"
            detail = rf.get("detail", "").replace('"', "'")
            flag_parts.append(f'<span class="{cls}" title="{detail}">{rf.get("label","")}</span>')
        risk_flags_html = "<div>" + "".join(flag_parts) + "</div>"

    quality_badge = ""
    if not passes and ac == "Stock":
        reasons = inst.get("quality_fail_reasons", [])
        tip = " · ".join(reasons).replace('"', "'") if reasons else ""
        quality_badge = f'<div><span class="quality-fail" title="{tip}">Does not pass quality filter</span></div>'

    # ── Signal badges ─────────────────────────────────────────────────────────
    badges_html = ""
    badges = inst.get("signal_badges", [])
    if badges:
        badge_parts = []
        for b in badges:
            badge_parts.append(
                f'<span class="signal-badge" title="{b.get("detail","")}">'
                f'{b.get("label","")}</span>'
            )
        badges_html = '<div class="signal-badge-row">' + "".join(badge_parts) + "</div>"

    # ── Score nudge note ──────────────────────────────────────────────────────
    nudge = inst.get("score_nudge", 0)
    nudge_html = ""
    if nudge and abs(nudge) >= 1 and score is not None:
        nudge_html = (f'<span style="font-size:9px;color:#777777;margin-left:4px;'
                      f'font-family:var(--vs-sans);font-weight:600;text-transform:uppercase;'
                      f'letter-spacing:0.06em">({nudge:+.0f})</span>')

    # ── Price + YTD ────────────────────────────────────────────────────────────
    price = _f(inst.get("price"))
    ytd   = _f(inst.get("ytd_pct"))

    price_str = f"{cur} {price:,.2f}" if price else "—"
    ytd_str   = ""
    ytd_cls   = ""
    if ytd is not None:
        sign    = "+" if ytd >= 0 else ""
        ytd_str = f"{sign}{ytd:.1f}%"

    # ── Determine score block class (high vs low) ─────────────────────────────
    score_block_cls = "card-score-block"
    if score is None or score < 45:
        score_block_cls += " low"

    # ── Build verdict bullets ─────────────────────────────────────────────────
    # verdict may be plain text or already contain bullet structure
    # We parse for Signal / Risk / Watch prefixes; fall back to plain text
    def _make_bullets(text):
        if not text or text == "—":
            return f'<div class="card-bullet"><span style="color:#444444">{text}</span></div>'
        import re
        # Try to split on known markers
        sig = re.search(r'(?:Signal|Thesis)[:\s]+(.+?)(?=Risk[:\s]|Watch[:\s]|$)', text, re.I | re.S)
        rsk = re.search(r'Risk[:\s]+(.+?)(?=Watch[:\s]|Signal[:\s]|$)', text, re.I | re.S)
        wch = re.search(r'Watch[:\s]+(.+?)(?=Risk[:\s]|Signal[:\s]|$)', text, re.I | re.S)
        if sig or rsk or wch:
            rows = []
            if sig:
                rows.append(('↑', 'Signal', sig.group(1).strip()))
            if rsk:
                rows.append(('!', 'Risk', rsk.group(1).strip()))
            if wch:
                rows.append(('→', 'Watch', wch.group(1).strip()))
            html = ""
            for icon, lbl, body in rows:
                html += (
                    f'<div class="card-bullet">'
                    f'<span class="card-bullet-icon">{icon}</span>'
                    f'<span><strong>{lbl}:</strong> {body}</span>'
                    f'</div>'
                )
            return html
        # Plain text fallback — split on ". " for rough bullets
        sentences = [s.strip() for s in text.replace("•", ". ").split(". ") if s.strip()]
        icons = ['↑', '!', '→']
        lbls  = ['Signal', 'Risk', 'Watch']
        html = ""
        for i, sent in enumerate(sentences[:3]):
            icon = icons[i] if i < len(icons) else '→'
            lbl  = lbls[i]  if i < len(lbls)  else 'Note'
            html += (
                f'<div class="card-bullet">'
                f'<span class="card-bullet-icon">{icon}</span>'
                f'<span><strong>{lbl}:</strong> {sent}</span>'
                f'</div>'
            )
        return html

    bullets_html = _make_bullets(verdict)

    # ── YTD footer ────────────────────────────────────────────────────────────
    ytd_footer = ""
    if ytd_str:
        ytd_footer = (
            f'<span class="card-ytd">YTD '
            f'<span class="card-ytd-val">{ytd_str}</span></span>'
        )

    # ── Strong Value tag ──────────────────────────────────────────────────────
    tag_html = ""
    if score is not None and score >= 75:
        tag_html = '<span class="card-tag">Strong Value</span>'

    # ── News signal tag ───────────────────────────────────────────────────────
    news_tag_html = ""
    try:
        _nsmap = _get_news_signals_map()
        _nsig  = _nsmap.get(ticker)
        if _nsig:
            _sent  = _nsig.get("sentiment", 0)
            _src   = _nsig.get("source", "")
            _url   = _nsig.get("url", "")
            _src_short = {"Yahoo Finance": "YF", "Seeking Alpha": "SA",
                          "MarketWatch": "MW", "CNBC": "CNBC", "WSJ": "WSJ",
                          "NASDAQ": "NAS", "S&P Global": "S&P",
                          "CNN Finance": "CNN"}.get(_src, _src[:4])
            _direction = "+" if _sent >= 0.05 else "−" if _sent <= -0.05 else ""
            _tag_label = f"{_direction}&nbsp;{_src_short}" if _direction else _src_short
            if _url:
                news_tag_html = (
                    f'<a href="{_url}" target="_blank" rel="noopener" style="text-decoration:none">'
                    f'<span class="card-tag" style="border-color:#1A3A5C;color:#1A3A5C;'
                    f'font-family:\'Inter\',sans-serif">{_tag_label}</span></a>'
                )
            else:
                news_tag_html = (
                    f'<span class="card-tag" style="border-color:#1A3A5C;color:#1A3A5C;'
                    f'font-family:\'Inter\',sans-serif">{_tag_label}</span>'
                )
    except Exception:
        pass

    # NOTE: no leading spaces — Streamlit/CommonMark treats 4-space-indented lines as code blocks
    card_html = (
        f'<div class="card">'
        f'<div class="card-header">'
        f'<div style="flex:1;min-width:0">'
        f'<div class="card-name">{name}</div>'
        f'<div class="card-ticker-line">'
        f'<span class="ticker">{ticker}</span>'
        f'&nbsp;&nbsp;<span class="price">{price_str}</span>'
        f'</div>'
        f'<div class="card-market-line">{subtitle}</div>'
        f'</div>'
        f'<div class="{score_block_cls}">'
        f'<div class="card-score-num">{score_display}{nudge_html}</div>'
        f'<div class="card-score-lbl">{rating_label}</div>'
        f'</div>'
        f'</div>'
        f'{quality_badge}'
        f'{risk_flags_html}'
        f'{badges_html}'
        f'<div class="card-bullets">{bullets_html}</div>'
        f'<div class="card-metrics">{pills_html}</div>'
        f'<div class="card-footer">'
        f'{ytd_footer}'
        f'{tag_html}'
        f'{news_tag_html}'
        f'</div>'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

    # ── Score breakdown + Watchlist actions ───────────────────────────────────
    # FIX Bug 1: stable keys using ticker string only
    action_col, breakdown_col = st.columns([2, 3])

    with action_col:
        if show_add_watchlist:
            if is_wl:
                if st.button("Remove",     key=f"rm_wl_{_ks}", use_container_width=True):
                    st.session_state.watchlist = [
                        w for w in st.session_state.watchlist if w["ticker"] != ticker
                    ]
                    save_watchlist(_uid(), st.session_state.watchlist)
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
                    save_watchlist(_uid(), st.session_state.watchlist)
                    # FIX UX: toast confirmation instead of silent rerun
                    st.session_state.toast = (f"{name} added to watchlist", "success")
                    st.rerun()

    with breakdown_col:
        # FIX UX: score breakdown inline per card
        if inst.get("score_components"):
            with st.expander("Score breakdown", expanded=False, key=f"bd_{_ks}"):
                _render_score_breakdown(inst)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: HOME
# ══════════════════════════════════════════════════════════════════════════════

def _home_summary_tile(col, num, label, colour="#1A1A1A"):
    with col:
        st.markdown(
            f'<div class="summary-tile">'
            f'<div class="summary-number" style="color:{colour}">{num}</div>'
            f'<div class="summary-label">{label}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _section_header(label, page_key=None):
    """Render the BBC-style section header with optional 'View all →' link.

    Navigation is wired entirely via JS setting query_params to navigate.
    """
    link_html = ""
    wire_js = ""
    if page_key:
        link_id = f"sec_link_{page_key}_{label[:6].replace(' ','_')}"
        link_html = f'<span class="vs-section-link" id="{link_id}">View all →</span>'
        # JS: clicking the section link sets query_params to navigate
        wire_js = (
            f'<script>'
            f'(function(){{'
            f'  var lnk=document.getElementById("{link_id}");'
            f'  if(lnk&&!lnk._wired){{'
            f'    lnk._wired=true;'
            f'    lnk.addEventListener("click",function(){{'
            f'      var u=new URL(window.location.href);'
            f'      u.searchParams.set("p","{page_key}");'
            f'      window.location.href=u.toString();'
            f'    }});'
            f'  }}'
            f'}})();</script>'
        )

    st.markdown(
        f'<div class="vs-section-header">'
        f'<div class="vs-section-header-row">'
        f'<span class="vs-section-title">{label}</span>'
        f'{link_html}'
        f'</div>'
        f'<div class="vs-section-rule"></div>'
        f'</div>'
        f'{wire_js}',
        unsafe_allow_html=True,
    )


# Keep old _nav_heading as thin wrapper for any legacy callers
def _nav_heading(label, page_key, subtitle=None):
    _section_header(label, page_key)


def page_home():
    _render_counter.clear()

    instruments = st.session_state.instruments
    ok          = [x for x in instruments if x.get("ok")] if instruments else []
    live        = {x["ticker"]: x for x in ok}
    holdings    = st.session_state.holdings
    watchlist   = st.session_state.watchlist
    age         = cache_age_hours()

    # ── Build status strings for hero timestamp ───────────────────────────────
    if age is not None:
        age_str = ("Live" if age < 1 else f"{int(age)}h ago" if age < 8 else f"{int(age)}h ago — refresh below")
    else:
        age_str = "No data loaded"
    last_surv = get_last_run_time()
    surv_str  = ""
    if last_surv:
        try:
            surv_dt  = datetime.fromisoformat(last_surv)
            surv_str = f"  ·  Surveillance {surv_dt.strftime('%H:%M %d %b')}"
        except Exception:
            pass
    next_ev  = _next_market_event()
    next_str = f"  ·  {next_ev}" if next_ev else ""
    ts_line  = f"{datetime.now().strftime('%A %d %B %Y').upper()}  ·  {age_str}{surv_str}{next_str}"

    # ── Market mood (from news sentiment) ─────────────────────────────────────
    _mood_str = ""
    try:
        _mood = get_market_mood(sample_size=30)
        if _mood.get("label") and _mood["label"] != "No data":
            _mood_str = f"  ·  {_mood['label']}"
    except Exception:
        pass

    # ── Welcome heading ───────────────────────────────────────────────────────
    user = st.session_state.get("user_name", "")
    now_h = datetime.now().hour
    if now_h < 12:
        period = "morning"
    elif now_h < 17:
        period = "afternoon"
    else:
        period = "evening"
    greeting = f"Good {period}, {user}." if user else f"Good {period}."

    # ── Hero summary stats ────────────────────────────────────────────────────
    scored_all = [x for x in ok if _f(x.get("score")) is not None]
    strong_val = sum(1 for x in scored_all if (_f(x.get("score")) or 0) >= 75)
    h_scored   = [live[h["ticker"]] for h in holdings if h["ticker"] in live and _f(live[h["ticker"]].get("score")) is not None]
    avg_h_score = (sum(_f(x["score"]) for x in h_scored) / len(h_scored)) if h_scored else None

    # Avg portfolio return
    gains = []
    h_map = {h["ticker"]: h for h in holdings}
    for inst in h_scored:
        added = _f(h_map.get(inst["ticker"], {}).get("price_when_added"))
        price = _f(inst.get("price"))
        if added and price and added > 0:
            gains.append((price / added - 1) * 100)
    avg_gain = (sum(gains) / len(gains)) if gains else None

    stat1_val = str(len(ok)) if ok else "—"
    stat2_val = f"{avg_h_score:.0f}" if avg_h_score is not None else "—"
    stat3_val = str(strong_val) if ok else "—"
    stat4_raw = f"{'+' if avg_gain and avg_gain >= 0 else ''}{avg_gain:.1f}%" if avg_gain is not None else "—"
    stat4_cls = " positive" if avg_gain and avg_gain > 0 else ""

    hero_html = (
        f'<div class="vs-hero">'
        f'<div class="vs-hero-greeting">{greeting}</div>'
        f'<div class="vs-hero-timestamp">{ts_line}{_mood_str}</div>'
        f'<div class="vs-hero-stats">'
        f'<div class="vs-hero-stat"><div class="vs-hero-stat-val">{stat1_val}</div>'
        f'<div class="vs-hero-stat-lbl">Instruments loaded</div></div>'
        f'<div class="vs-hero-stat"><div class="vs-hero-stat-val">{stat2_val}</div>'
        f'<div class="vs-hero-stat-lbl">Avg holdings score</div></div>'
        f'<div class="vs-hero-stat"><div class="vs-hero-stat-val">{stat3_val}</div>'
        f'<div class="vs-hero-stat-lbl">Strong value picks</div></div>'
        f'<div class="vs-hero-stat"><div class="vs-hero-stat-val{stat4_cls}">{stat4_raw}</div>'
        f'<div class="vs-hero-stat-lbl">Avg portfolio return</div></div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(hero_html, unsafe_allow_html=True)

    # ── Data controls ─────────────────────────────────────────────────────────
    _render_data_controls()

    # ── Welcome / no-data state ───────────────────────────────────────────────
    if not instruments:
        st.markdown(
            '<div class="changed-banner" style="margin-top:32px;text-align:center;'
            'padding:40px 24px;border-left:none;border:1px solid #D4D4D2">'
            '<div style="font-family:\'Playfair Display\',Georgia,serif;font-size:26px;'
            'font-weight:700;color:#1A1A1A;margin-bottom:10px;letter-spacing:-0.3px">'
            'Welcome to Value Screener</div>'
            '<div style="font-size:13px;line-height:1.6;max-width:420px;margin:0 auto;color:#444444">'
            'Choose your markets above, then click <b style="color:#1A1A1A">Load Data</b> to begin.'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    # ── Macro bar ─────────────────────────────────────────────────────────────
    _render_macro_bar()

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — YOUR HOLDINGS
    # ══════════════════════════════════════════════════════════════════════════
    _section_header("Your Holdings", "deepdive")

    if not holdings:
        st.markdown(
            '<div class="changed-banner">'
            'No holdings yet — go to <b>Deepdive</b> to add your positions.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        h_tickers = {h["ticker"]: h for h in holdings}
        h_live    = [live[t] for t in h_tickers if t in live]
        h_missing = [t for t in h_tickers if t not in live]

        if h_missing:
            st.caption(f"{len(h_missing)} holding(s) have no live data — load their markets above.")

        if h_live:
            scored_h  = [x for x in h_live if _f(x.get("score")) is not None]
            avg_score = (sum(_f(x["score"]) for x in scored_h) / len(scored_h)) if scored_h else None
            avg_str   = f"{avg_score:.0f}" if avg_score is not None else "—"

            gains2 = []
            for inst in h_live:
                t     = inst["ticker"]
                added = _f(h_tickers[t].get("price_when_added"))
                price_v = _f(inst.get("price"))
                if added and price_v and added > 0:
                    gains2.append((price_v / added - 1) * 100)
            avg_gain2 = (sum(gains2) / len(gains2)) if gains2 else None
            gain_str  = f"{'+' if avg_gain2 and avg_gain2 >= 0 else ''}{avg_gain2:.1f}%" if avg_gain2 is not None else "—"

            tc1, tc2, tc3, tc4 = st.columns(4)
            _home_summary_tile(tc1, str(len(holdings)), "Holdings")
            _home_summary_tile(tc2, str(len(h_live)),   "With live data")
            _home_summary_tile(tc3, avg_str,            "Avg value score")
            _home_summary_tile(tc4, gain_str,           "Avg return since added")

            st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

            h_sorted = sorted(h_live, key=lambda x: _f(x.get("score")) or 0, reverse=True)
            cols = st.columns(2)
            for j, inst in enumerate(h_sorted[:2]):
                with cols[j]:
                    render_card(inst, show_add_watchlist=False)
            if len(h_live) > 2:
                st.caption(f"+{len(h_live) - 2} more — click View all → above.")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — WATCHLIST
    # ══════════════════════════════════════════════════════════════════════════
    _section_header("Watchlist", "deepdive")

    if not watchlist:
        st.markdown(
            '<div class="changed-banner">'
            'Nothing on your watchlist yet — go to <b>Deepdive</b> to add instruments.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        wl_tickers = {w["ticker"]: w for w in watchlist}
        wl_live    = [live[t] for t in wl_tickers if t in live]
        wl_missing = [t for t in wl_tickers if t not in live]

        if wl_missing:
            st.caption(f"{len(wl_missing)} watchlist item(s) have no live data — load their markets above.")

        if wl_live:
            scored_wl  = [x for x in wl_live if _f(x.get("score")) is not None]
            best_wl    = sorted(scored_wl, key=lambda x: _f(x.get("score")) or 0, reverse=True)
            flagged_wl = [x for x in wl_live if x.get("has_signals")]
            avg_wl     = (sum(_f(x["score"]) for x in scored_wl) / len(scored_wl)) if scored_wl else None
            avg_wl_str = f"{avg_wl:.0f}" if avg_wl is not None else "—"

            wc1, wc2, wc3, wc4 = st.columns(4)
            _home_summary_tile(wc1, str(len(watchlist)),  "Watching")
            _home_summary_tile(wc2, str(len(wl_live)),    "With live data")
            _home_summary_tile(wc3, avg_wl_str,           "Avg value score")
            _home_summary_tile(wc4, str(len(flagged_wl)), "Flagged")

            st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)

            cols = st.columns(2)
            for j, inst in enumerate(best_wl[:2]):
                with cols[j]:
                    render_card(inst, show_add_watchlist=False)
            if len(wl_live) > 2:
                st.caption(f"+{len(wl_live) - 2} more — click View all → above.")

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 3 — RADAR (top picks not already held or watched)
    # ══════════════════════════════════════════════════════════════════════════
    known_tickers = (
        {h["ticker"] for h in holdings} |
        {w["ticker"] for w in watchlist}
    )
    radar = sorted(
        [x for x in ok
         if x["ticker"] not in known_tickers and _f(x.get("score")) is not None],
        key=lambda x: _f(x.get("score")) or 0, reverse=True
    )[:4]

    if radar:
        _section_header("Radar", "screener")
        chips_html = '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px">'
        for inst in radar:
            tkr       = inst.get("ticker", "")
            iname     = inst.get("name", tkr)
            score     = _f(inst.get("score"))
            score_txt = f"{score:.0f}" if score is not None else "—"
            chips_html += (
                f'<div style="display:flex;align-items:center;gap:8px;'
                f'background:#FFFFFF;border:1px solid #D4D4D2;'
                f'padding:8px 16px 8px 10px;white-space:nowrap">'
                f'<span style="font-family:\'Playfair Display\',serif;font-size:20px;'
                f'font-weight:700;color:#1A1A1A;line-height:1">{score_txt}</span>'
                f'<span style="border-left:1px solid #D4D4D2;margin:0 4px;height:18px;'
                f'display:inline-block;vertical-align:middle"></span>'
                f'<span style="font-family:\'Inter\',sans-serif;font-size:12px;font-weight:700;'
                f'color:#1A1A1A">{tkr}</span>'
                f'<span style="font-family:\'Inter\',sans-serif;font-size:11px;color:#777777">'
                f'{iname[:28]}</span>'
                f'</div>'
            )
        chips_html += '</div>'
        st.markdown(chips_html, unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 4 — BRIEFING SNAPSHOT
    # ══════════════════════════════════════════════════════════════════════════
    signals  = load_latest_signals()
    briefing = load_briefing()

    if signals or briefing:
        _section_header("Briefing", "briefing")

        if briefing and briefing.get("headline"):
            st.markdown(
                f'<div class="changed-banner">{briefing["headline"]}</div>',
                unsafe_allow_html=True,
            )

        if signals:
            high_count = sum(1 for s in signals if s.get("severity") == "high")
            med_count  = sum(1 for s in signals if s.get("severity") == "medium")
            low_count  = sum(1 for s in signals if s.get("severity") in ("low", "info"))
            badges_html = '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">'
            for count, lbl in [(high_count, "High"), (med_count, "Medium"), (low_count, "Low / Info")]:
                if count:
                    badges_html += (
                        f'<span style="background:transparent;color:#1A3A5C;'
                        f'font-family:\'Inter\',sans-serif;font-size:10px;font-weight:700;'
                        f'text-transform:uppercase;letter-spacing:0.08em;'
                        f'border:1px solid #1A3A5C;padding:3px 10px">'
                        f'{count} {lbl}</span>'
                    )
            badges_html += '</div>'
            st.markdown(badges_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SCREENER (Find Ideas)
# ══════════════════════════════════════════════════════════════════════════════

def page_screener():
    _render_counter.clear()

    # ── Page title ────────────────────────────────────────────────────────────
    st.markdown(
        '<div style="font-family:\'Playfair Display\',Georgia,serif;font-size:38px;'
        'font-weight:700;color:#1A1A1A;letter-spacing:-0.5px;line-height:1.1;'
        'padding-top:32px;padding-bottom:8px">Screen</div>',
        unsafe_allow_html=True,
    )

    # ── Data controls ─────────────────────────────────────────────────────────
    _render_data_controls()
    _render_screen_filters()

    instruments = st.session_state.instruments
    if not instruments:
        st.markdown(
            '<div class="changed-banner" style="margin-top:16px">Select markets above and click <b>Load Data</b> to screen them.</div>',
            unsafe_allow_html=True,
        )
        return

    filtered = apply_filters(instruments, include_excluded=False)
    excluded = apply_filters(instruments, include_excluded=True)
    ok_all   = [x for x in instruments if x.get("ok")]

    # ── Stats bar ──────────────────────────────────────────────────────────────
    stocks_passing = [x for x in filtered if x.get("asset_class") == "Stock"]
    funds_passing  = [x for x in filtered if x.get("asset_class") != "Stock"]
    flagged_count  = sum(1 for x in filtered if x.get("has_signals"))

    statbar_html = (
        f'<div class="vs-statbar">'
        f'<div class="vs-statbar-cell">'
        f'<div class="vs-statbar-val">{len(filtered)}</div>'
        f'<div class="vs-statbar-lbl">Showing of {len(ok_all)}</div></div>'
        f'<div class="vs-statbar-cell">'
        f'<div class="vs-statbar-val">{len(stocks_passing)}</div>'
        f'<div class="vs-statbar-lbl">Stocks</div></div>'
        f'<div class="vs-statbar-cell">'
        f'<div class="vs-statbar-val">{len(funds_passing)}</div>'
        f'<div class="vs-statbar-lbl">Funds / ETFs</div></div>'
        f'<div class="vs-statbar-cell">'
        f'<div class="vs-statbar-val">{len(excluded)}</div>'
        f'<div class="vs-statbar-lbl">Excluded</div></div>'
        f'<div class="vs-statbar-cell">'
        f'<div class="vs-statbar-val">{flagged_count}</div>'
        f'<div class="vs-statbar-lbl">Flagged</div></div>'
        f'</div>'
    )
    st.markdown(statbar_html, unsafe_allow_html=True)

    if not filtered and not excluded:
        st.warning("Nothing matches your current filters — try loosening them above.")
        return

    # ── CSV export ─────────────────────────────────────────────────────────────
    def _screener_csv(insts):
        import io
        _fields = ["ticker", "name", "group", "asset_class", "score", "quality_passes",
                   "price", "ytd_pct", "yr1_pct", "pe", "pb", "ev_ebitda",
                   "div_yield", "roe", "debt_equity", "profit_margin", "free_cashflow",
                   "market_cap", "verdict"]
        buf = io.StringIO()
        buf.write(",".join(_fields) + "\n")
        for inst in insts:
            row = []
            for f in _fields:
                v = inst.get(f, "")
                if isinstance(v, float):
                    v = f"{v:.4f}"
                elif isinstance(v, bool):
                    v = "TRUE" if v else "FALSE"
                elif v is None:
                    v = ""
                row.append(str(v).replace(",", ";"))
            buf.write(",".join(row) + "\n")
        return buf.getvalue().encode("utf-8")

    _exp_col, _ = st.columns([2, 6])
    with _exp_col:
        st.download_button(
            label=f"Export {len(filtered)} results (CSV)",
            data=_screener_csv(filtered),
            file_name=f"value_screener_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            key="screener_csv_btn",
        )

    # ── Flagged-only toggle ────────────────────────────────────────────────────
    if flagged_count > 0:
        flag_col, _ = st.columns([2, 3])
        with flag_col:
            flag_label = (
                f"Showing flagged only ({flagged_count})"
                if st.session_state.show_flagged_only
                else f"Show flagged only ({flagged_count})"
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

    # ── Section header + Group tabs ────────────────────────────────────────────
    _section_header("Top Picks by Score")

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

    # ── Quality-failed stocks (hidden by default) ──────────────────────────────
    if excluded:
        st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
        toggle_label = (
            f"Hide {len(excluded)} stocks that failed quality filter"
            if st.session_state.show_excluded
            else f"Show {len(excluded)} stocks that failed quality filter"
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
                group = "UK Stocks"
            elif ticker.endswith((".DE", ".PA", ".AS", ".MC", ".MI", ".SW",
                                   ".ST", ".CO", ".HE", ".OL")):
                group = "EU Stocks"
            elif asset_class == "ETF":
                group = "ETFs & Index Funds"
            else:
                group = "US Stocks"

            div_raw = _f(info.get("dividendYield"))
            if div_raw is None:
                div_yield = None
            elif div_raw > 1.0:
                div_yield = round(min(div_raw, 99.0), 2)
            else:
                div_yield = round(div_raw * 100, 2)

            hist = t.history(period="1y")
            price    = _f(hist["Close"].iloc[-1])  if not hist.empty else None
            high_52w = _f(hist["Close"].max())     if not hist.empty else None
            low_52w  = _f(hist["Close"].min())     if not hist.empty else None
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
                "pe":          _f(info.get("trailingPE")),
                "pb":          _f(info.get("priceToBook")),
                "div_yield":   div_yield,
                "market_cap":  _f(info.get("marketCap")),
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

    pe_span    = (f'<span><b style="color:#1A1A1A">P/E</b> {pe:.1f}x</span>' if pe else '')
    pb_span    = (f'<span><b style="color:#1A1A1A">P/B</b> {pb:.1f}x</span>' if pb else '')
    yield_span = (f'<span><b style="color:#1A1A1A">Yield</b> {div_yield:.2f}%</span>' if div_yield else '')
    ret_span   = (f'<span><b style="color:#1A1A1A">1yr</b> {_fmt_pct(yr1_ret)}</span>' if yr1_ret is not None else '')
    cap_span   = (f'<span><b style="color:#1A1A1A">Mkt cap</b> {_fmt_aum(mktcap)}</span>' if mktcap else '')
    price_disp = _fmt_price(price, currency + ' ') if price else '—'
    st.markdown(
        f'<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-radius:0;'
        f'padding:18px 22px;margin-bottom:14px;box-shadow:var(--vs-shadow)">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
        f'<div>'
        f'<span style="font-size:1.05rem;font-weight:600;color:#1A1A1A">{name}</span>'
        f'<span style="font-size:0.82rem;color:#777777;margin-left:10px">{ticker}</span>'
        f'<span style="font-size:0.72rem;background:#F0F0EE;color:#444444;'
        f'border:1px solid #D4D4D2;border-radius:0;padding:2px 8px;margin-left:8px">{group}</span>'
        f'</div>'
        f'<div style="font-size:1rem;font-weight:600;color:#1A1A1A">{price_disp}</div>'
        f'</div>'
        f'<div style="margin-top:10px;display:flex;gap:18px;flex-wrap:wrap;font-size:0.82rem;color:#444444">'
        f'<span><b style="color:#1A1A1A">Sector</b> {sector}</span>'
        f'{pe_span}{pb_span}{yield_span}{ret_span}{cap_span}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    act_c1, act_c2, _ = st.columns([2, 2, 4])
    with act_c1:
        if already_in_wl:
            st.success("Already on watchlist")
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
                save_watchlist(_uid(), st.session_state.watchlist)
                st.session_state.toast = (f"{name} added to watchlist", "success")
                st.session_state.wl_search_result = None
                st.rerun()
    with act_c2:
        if st.button("Clear result", key="wl_sr_clear", use_container_width=True):
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

    # ── Colour helpers (monochrome — no colour signals) ───────────────────────
    def _score_col(s, mx):
        pct = s / mx if mx else 0
        if pct >= 0.8: return "#1A1A1A"
        if pct >= 0.6: return "#444444"
        if pct >= 0.4: return "#777777"
        return "#AAAAAA"

    def _rating_col(r):
        r = (r or "").lower()
        if "exceptional" in r: return "#1A1A1A"
        if "strong"      in r: return "#444444"
        if "moderate"    in r: return "#777777"
        return "#AAAAAA"

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
    _section_header("Deep Analysis")

    # Status line — show model used if cached
    if cached:
        age_str   = f"{age:.1f} days ago" if age is not None else "recently"
        _model    = cached.get("_model", "")
        _model_lbl = "Sonnet" if "sonnet" in _model else ("Haiku" if "haiku" in _model else "")
        _model_tag = f" · via {_model_lbl}" if _model_lbl else ""
        st.caption(
            f"Last analysed {age_str} · {cached.get('confidence','—')} confidence"
            f"{_model_tag} · Scores reflect data available at time of analysis"
        )
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

    # Run controls — three buttons: Haiku (fast/cheap), Sonnet (deep), Clear
    btn_c1, btn_c2, btn_c3, _ = st.columns([2, 2, 2, 2])
    with btn_c1:
        run_label   = "Re-analyse (Haiku)" if cached else "Analyse"
        run_clicked = st.button(run_label, key=f"da_run_{ticker}", use_container_width=True,
                                type="primary")
    with btn_c2:
        deep_label    = "Deep refresh (Sonnet)" if cached else "Analyse — full depth"
        deep_clicked  = st.button(deep_label, key=f"da_deep_{ticker}", use_container_width=True)
    with btn_c3:
        if cached and st.button("Clear analysis", key=f"da_clear_{ticker}",
                                use_container_width=True):
            try:
                from utils.deep_analysis import _cache_file
                _cache_file(ticker).unlink(missing_ok=True)
            except Exception:
                pass
            st.session_state.toast = ("Analysis cleared", "info")
            st.rerun()

    # ── Run analysis ──────────────────────────────────────────────────────────
    _force_sonnet = deep_clicked and not run_clicked
    if run_clicked or deep_clicked:
        extra = st.session_state.da_extra.get(ticker, "")
        _spinner_msg = (
            f"Running deep analysis with Sonnet — 30–60 seconds …"
            if _force_sonnet
            else f"Analysing {name} with Haiku — 10–20 seconds …"
        )
        with st.spinner(_spinner_msg):
            try:
                cached = run_deep_analysis(inst, extra_context=extra,
                                           force_sonnet=_force_sonnet)
                _done_model = "Sonnet" if _force_sonnet else "Haiku"
                st.session_state.toast = (
                    f"Deep analysis complete for {name} ({_done_model})", "success"
                )
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))
                return
            except Exception as e:
                st.error(f"Analysis failed: {e}")
                return

    if not cached:
        return

    # ── Score history sparkline ───────────────────────────────────────────────
    _section_header("Score History (5 years)")
    try:
        from utils.score_history import get_score_history, has_history, backfill_ticker
        import altair as alt

        _has_hist = has_history(ticker)
        if not _has_hist:
            _bfc1, _bfc2 = st.columns([3, 1])
            with _bfc1:
                st.caption(
                    "No score history yet. Click **Backfill 5yr** to download historical "
                    "price data and compute proxy scores. Live scores will accumulate daily."
                )
            with _bfc2:
                if st.button("Backfill 5yr", key=f"backfill_{ticker}",
                             use_container_width=True):
                    with st.spinner(f"Downloading 5 years of data for {ticker}…"):
                        try:
                            n = backfill_ticker(ticker, years=5)
                            if n > 0:
                                st.toast(f"Backfilled {n} data points for {ticker}")
                                st.rerun()
                            else:
                                st.warning(f"No historical data found for {ticker} via yfinance.")
                        except Exception as _be:
                            st.error(f"Backfill failed: {_be}")
        else:
            _hist_df = get_score_history(ticker, days=365 * 5)
            if not _hist_df.empty:
                # Colour-code backfill vs live rows
                _hist_df["type"] = _hist_df["source"].map(
                    lambda s: "Proxy (price-based)" if s == "backfill" else "Live score"
                )
                _hist_df["date_str"] = _hist_df["date"].dt.strftime("%d %b %Y")

                _chart = (
                    alt.Chart(_hist_df)
                    .mark_line(interpolate="monotone", strokeWidth=1.5)
                    .encode(
                        x=alt.X("date:T", title=None,
                                axis=alt.Axis(format="%b %Y", labelAngle=-30)),
                        y=alt.Y("score:Q", title="Score",
                                scale=alt.Scale(domain=[0, 100])),
                        color=alt.Color(
                            "type:N",
                            scale=alt.Scale(
                                domain=["Proxy (price-based)", "Live score"],
                                range=["#D4D4D2", "#1A3A5C"],
                            ),
                            legend=alt.Legend(title=None, orient="top-right"),
                        ),
                        tooltip=["date_str:N", "score:Q", "price:Q", "type:N"],
                    )
                    .properties(height=180)
                    .configure_view(strokeWidth=0)
                    .configure_axis(
                        labelFont="Inter", titleFont="Inter",
                        labelColor="#777777", titleColor="#777777",
                        gridColor="#F0F0EE",
                    )
                )
                st.altair_chart(_chart, use_container_width=True)
                _earliest, _latest = _hist_df["date"].min(), _hist_df["date"].max()
                _n_live = (_hist_df["source"] == "live").sum()
                st.caption(
                    f"{len(_hist_df)} data points · {_earliest.strftime('%d %b %Y')} → "
                    f"{_latest.strftime('%d %b %Y')} · "
                    f"{_n_live} live · grey = price-momentum proxy"
                )
            st.markdown("")
    except ImportError:
        st.caption("Install `altair` for score history charts: `pip install altair`")
    except Exception as _he:
        st.caption(f"Score history unavailable: {_he}")

    st.markdown("---")

    # ── Render the result ─────────────────────────────────────────────────────
    overall = cached.get("overall_score", 0)
    rating  = cached.get("final_assessment", {}).get("rating", "—")
    conf    = cached.get("confidence", "—")
    rat_col = _rating_col(rating)
    ov_col  = _score_col(overall, 100)

    # Header: big score + rating badge
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:16px;margin:12px 0 8px 0">'
        f'<div class="da-score-big">{overall}</div>'
        f'<div>'
        f'<span class="da-rating">{rating}</span>'
        f'<span class="da-confidence"> {_conf_icon(conf)} {conf} confidence</span>'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Summary
    summary = cached.get("final_assessment", {}).get("summary", "")
    if summary:
        st.markdown(
            f'<div style="font-family:\'Inter\',sans-serif;font-size:13px;color:#444444;line-height:1.6;'
            f'margin-bottom:12px;padding:14px 16px;background:#F8F8F6;'
            f'border-left:3px solid #1A3A5C;border:1px solid #D4D4D2;'
            f'border-left-width:3px">{summary}</div>',
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
    group      = wl_entry.get("group", "US Stocks")
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


# PAGE: DEEPDIVE
# ══════════════════════════════════════════════════════════════════════════════

def _render_instrument_expander(entry: dict, list_key: str, live_data: dict,
                                 expander_prefix: str = ""):
    """
    Render one expander row for an instrument in either Holdings or Watchlist.
    list_key: "holdings" or "watchlist"  — used for state key namespacing.
    """
    ticker      = entry["ticker"]
    added_price = _f(entry.get("price_when_added"))

    if ticker not in live_data:
        with st.expander(
            f"{entry.get('name', ticker)} ({ticker}) — no data loaded", expanded=False
        ):
            st.caption(
                f"Load {entry.get('group','the relevant market')} in the sidebar, "
                f"or fetch this instrument individually:"
            )
            miss_c1, miss_c2 = st.columns(2)
            with miss_c1:
                if st.button("Fetch now", key=f"dd_fetch_{list_key}_{ticker}",
                             use_container_width=True):
                    _refresh_single_ticker(entry)
                    st.rerun()
            with miss_c2:
                if st.button("Remove", key=f"dd_rm_miss_{list_key}_{ticker}",
                             use_container_width=True):
                    lst = getattr(st.session_state, list_key)
                    updated = [x for x in lst if x["ticker"] != ticker]
                    setattr(st.session_state, list_key, updated)
                    if list_key == "holdings":
                        save_holdings(_uid(), updated)
                    else:
                        save_watchlist(_uid(), updated)
                    st.rerun()
        return

    inst  = live_data[ticker]
    score = _f(inst.get("score"))
    label = score_label(score) if inst.get("quality_passes", True) else "Not scored"
    price = _f(inst.get("price"))

    change_str = ""
    if price and added_price and added_price > 0:
        chg    = (price / added_price - 1) * 100
        sign   = "+" if chg >= 0 else ""
        colour = "#1A1A1A" if chg >= 0 else "#777777"
        change_str = (
            f'<span style="color:{colour};font-weight:600">{sign}{chg:.1f}% since added</span>'
        )

    header = (
        f"{inst['name']} ({ticker})  ·  {score:.0f}/100 — {label}"
        if score is not None
        else f"{inst['name']} ({ticker})"
    )

    with st.expander(header, expanded=False):
        render_card(inst, show_add_watchlist=False)

        mc1, mc2, mc3 = st.columns(3)
        mc1.markdown(f"**Added:** {entry.get('added_at', '—')}")
        if added_price:
            mc2.markdown(
                f"**Price when added:** {inst.get('currency', '')} {added_price:,.2f}"
            )
        if change_str:
            mc3.markdown(change_str, unsafe_allow_html=True)

        notes = st.text_area(
            "Notes",
            value=entry.get("notes", ""),
            key=f"dd_notes_{list_key}_{ticker}",
            label_visibility="collapsed",
            placeholder="Add your research notes here…",
        )
        if notes != entry.get("notes", ""):
            lst = getattr(st.session_state, list_key)
            for item in lst:
                if item["ticker"] == ticker:
                    item["notes"] = notes
            if list_key == "holdings":
                save_holdings(_uid(), lst)
            else:
                save_watchlist(_uid(), lst)

        btn_c1, btn_c2 = st.columns(2)
        with btn_c1:
            if st.button("Refresh data", key=f"dd_refresh_{list_key}_{ticker}",
                         use_container_width=True):
                _refresh_single_ticker(entry)
                st.rerun()
        with btn_c2:
            remove_label = "Remove from holdings" if list_key == "holdings" else "Remove from watchlist"
            if st.button(remove_label, key=f"dd_remove_{list_key}_{ticker}",
                         use_container_width=True):
                lst = getattr(st.session_state, list_key)
                updated = [x for x in lst if x["ticker"] != ticker]
                setattr(st.session_state, list_key, updated)
                if list_key == "holdings":
                    save_holdings(_uid(), updated)
                else:
                    save_watchlist(_uid(), updated)
                st.session_state.toast = (f"Removed {inst['name']}", "info")
                st.rerun()

        # ── Recent news & analyst commentary ─────────────────────────────────
        _section_header("Recent News")
        try:
            _ticker_articles = fetch_news_for_ticker(ticker, name=inst.get("name", ""), force=False)
            if _ticker_articles:
                # Split: short headlines vs longer Seeking Alpha editorial pieces
                _editorials = [a for a in _ticker_articles if a.get("source") == "Seeking Alpha"][:3]
                _headlines  = [a for a in _ticker_articles if a.get("source") != "Seeking Alpha"][:5]

                if _headlines:
                    st.markdown(
                        '<div style="font-family:\'Inter\',sans-serif;font-size:10px;font-weight:700;'
                        'text-transform:uppercase;letter-spacing:0.08em;color:#777777;'
                        'margin-bottom:6px">Headlines</div>',
                        unsafe_allow_html=True,
                    )
                    for _art in _headlines:
                        _sent  = _art.get("sentiment", 0)
                        _col   = "#1A1A1A" if _sent > 0.1 else "#777777" if _sent < -0.1 else "#444444"
                        _icon  = "▲" if _sent > 0.1 else "▼" if _sent < -0.1 else "─"
                        _link  = _art.get("url", "")
                        _title = _art.get("title", "")
                        _src   = _art.get("source", "")
                        if _link:
                            st.markdown(
                                f'<div style="padding:5px 0;border-bottom:1px solid #E8E8E6">'
                                f'<span style="color:{_col};font-size:0.72rem">{_icon} </span>'
                                f'<a href="{_link}" target="_blank" style="color:#1A1A1A;'
                                f'text-decoration:none;font-size:0.87rem">{_title}</a>'
                                f'<span style="color:#AAAAAA;font-size:0.74rem"> · {_src}</span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f'<div style="padding:5px 0;border-bottom:1px solid #E8E8E6">'
                                f'<span style="color:{_col};font-size:0.72rem">{_icon} </span>'
                                f'<span style="color:#1A1A1A;font-size:0.87rem">{_title}</span>'
                                f'<span style="color:#AAAAAA;font-size:0.74rem"> · {_src}</span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                if _editorials:
                    st.markdown(
                        '<div style="font-family:\'Inter\',sans-serif;font-size:10px;font-weight:700;'
                        'text-transform:uppercase;letter-spacing:0.08em;color:#777777;'
                        'margin-top:10px;margin-bottom:6px">Analyst Commentary · Seeking Alpha</div>',
                        unsafe_allow_html=True,
                    )
                    for _art in _editorials:
                        _sent    = _art.get("sentiment", 0)
                        _link    = _art.get("url", "")
                        _title   = _art.get("title", "")
                        _summary = _art.get("summary", "")
                        _sent_lbl = "Positive" if _sent > 0.05 else "Negative" if _sent < -0.05 else "Neutral"
                        st.markdown(
                            f'<div style="background:#FAFAF8;border:1px solid #D4D4D2;'
                            f'border-left:3px solid #1A3A5C;padding:10px 14px;margin-bottom:6px">'
                            f'<div style="font-family:\'Inter\',sans-serif;font-size:0.87rem;'
                            f'font-weight:600;color:#1A1A1A;margin-bottom:3px">'
                            f'{"<a href=" + repr(_link) + " target=_blank style=color:#1A1A1A;text-decoration:none>" + _title + "</a>" if _link else _title}'
                            f'</div>'
                            f'{"<div style=font-family:Inter,sans-serif;font-size:0.8rem;color:#444444;line-height:1.4>" + _summary[:180] + "…</div>" if _summary else ""}'
                            f'<div style="font-family:\'Inter\',sans-serif;font-size:0.72rem;'
                            f'color:#777777;margin-top:4px">{_sent_lbl} sentiment</div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.caption("No recent news found for this instrument.")
        except Exception:
            st.caption("News unavailable.")

        _render_deep_analysis(inst)


def _render_dd_search_result(target: str):
    """
    Render the Deepdive search result with Add to Holdings / Add to Watchlist buttons.
    target: "holdings" or "watchlist"
    """
    result = st.session_state.dd_search_result

    if result == "not_found":
        st.warning("No instrument found — try the exact ticker symbol (e.g. AAPL, HSBA.L).")
        if st.button("Clear", key="dd_sr_clear_notfound"):
            st.session_state.dd_search_result = None
            st.rerun()
        return

    if isinstance(result, str) and result.startswith("error:"):
        st.error(f"Lookup failed: {result[6:]}. Check the ticker and try again.")
        if st.button("Clear", key="dd_sr_clear_error"):
            st.session_state.dd_search_result = None
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

    in_holdings = ticker in {h["ticker"] for h in st.session_state.holdings}
    in_watchlist = ticker in {w["ticker"] for w in st.session_state.watchlist}

    pe_span    = (f'<span><b style="color:#1A1A1A">P/E</b> {pe:.1f}x</span>' if pe else '')
    pb_span    = (f'<span><b style="color:#1A1A1A">P/B</b> {pb:.1f}x</span>' if pb else '')
    yield_span = (f'<span><b style="color:#1A1A1A">Yield</b> {div_yield:.2f}%</span>' if div_yield else '')
    ret_span   = (f'<span><b style="color:#1A1A1A">1yr</b> {_fmt_pct(yr1_ret)}</span>' if yr1_ret is not None else '')
    cap_span   = (f'<span><b style="color:#1A1A1A">Mkt cap</b> {_fmt_aum(mktcap)}</span>' if mktcap else '')
    price_disp = _fmt_price(price, currency + ' ') if price else '—'

    st.markdown(
        f'<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-radius:0;'
        f'padding:18px 22px;margin-bottom:14px;box-shadow:var(--vs-shadow)">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
        f'<div>'
        f'<span style="font-size:1.05rem;font-weight:600;color:#1A1A1A">{name}</span>'
        f'<span style="font-size:0.82rem;color:#777777;margin-left:10px">{ticker}</span>'
        f'<span style="font-size:0.72rem;background:#F0F0EE;color:#444444;'
        f'border:1px solid #D4D4D2;border-radius:0;padding:2px 8px;margin-left:8px">{group}</span>'
        f'</div>'
        f'<div style="font-size:1rem;font-weight:600;color:#1A1A1A">{price_disp}</div>'
        f'</div>'
        f'<div style="margin-top:10px;display:flex;gap:18px;flex-wrap:wrap;font-size:0.82rem;color:#444444">'
        f'<span><b style="color:#1A1A1A">Sector</b> {sector}</span>'
        f'{pe_span}{pb_span}{yield_span}{ret_span}{cap_span}'
        f'</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    entry = {
        "ticker":           ticker,
        "name":             name,
        "group":            group,
        "asset_class":      result.get("asset_class", "Stock"),
        "price_when_added": price,
        "added_at":         datetime.now().strftime("%Y-%m-%d"),
        "notes":            "",
    }

    a1, a2, a3 = st.columns([2, 2, 1])
    with a1:
        if in_holdings:
            st.success("Already in holdings")
        else:
            if st.button(f"Add to Holdings", key="dd_add_holdings",
                         use_container_width=True, type="primary"):
                st.session_state.holdings.append(entry)
                save_holdings(_uid(), st.session_state.holdings)
                st.session_state.toast = (f"{name} added to holdings", "success")
                st.session_state.dd_search_result = None
                st.rerun()
    with a2:
        if in_watchlist:
            st.success("Already on watchlist")
        else:
            if st.button(f"Add to Watchlist", key="dd_add_watchlist",
                         use_container_width=True):
                st.session_state.watchlist.append(entry)
                save_watchlist(_uid(), st.session_state.watchlist)
                st.session_state.toast = (f"{name} added to watchlist", "success")
                st.session_state.dd_search_result = None
                st.rerun()
    with a3:
        if st.button("Clear", key="dd_sr_clear", use_container_width=True):
            st.session_state.dd_search_result = None
            st.rerun()


def page_deepdive():
    _render_counter.clear()
    st.markdown(
        '<div style="font-family:\'Playfair Display\',Georgia,serif;font-size:38px;'
        'font-weight:700;color:#1A1A1A;letter-spacing:-0.5px;line-height:1.1;'
        'padding-top:32px;padding-bottom:8px">Deepdive</div>',
        unsafe_allow_html=True,
    )

    instruments = st.session_state.instruments
    live_data   = {
        x["ticker"]: x
        for x in instruments
        if x.get("ok")
    } if instruments else {}

    # ══════════════════════════════════════════════════════════════════════════
    # SEARCH — shared between both sections
    # ══════════════════════════════════════════════════════════════════════════
    _section_header("Search & Add")
    st.caption("Enter a ticker (e.g. NVDA, HSBA.L, SIE.DE) or company name, then choose where to add it.")

    srch_col, btn_col = st.columns([4, 1])
    with srch_col:
        search_query = st.text_input(
            "Search",
            key="dd_search_input",
            placeholder="e.g. AAPL, HSBA.L, iShares Core FTSE 100…",
            label_visibility="collapsed",
        )
    with btn_col:
        search_clicked = st.button("Search", key="dd_search_btn", use_container_width=True,
                                   type="primary")

    if search_clicked and search_query.strip():
        with st.spinner(f"Looking up {search_query.strip()} …"):
            # Reuse the existing watchlist search logic but store in dd_search_result
            import yfinance as yf
            query  = search_query.strip()
            ticker = query.upper().strip()
            try:
                t    = yf.Ticker(ticker)
                info = t.info or {}
                name = info.get("longName") or info.get("shortName") or info.get("name")
                if not name:
                    try:
                        results = yf.Search(query, max_results=5)
                        quotes  = getattr(results, "quotes", []) or []
                        if quotes:
                            best   = quotes[0]
                            ticker = best.get("symbol", ticker)
                            name   = best.get("longname") or best.get("shortname") or ticker
                            t      = yf.Ticker(ticker)
                            info   = t.info or {}
                    except Exception:
                        pass
                if not name:
                    st.session_state.dd_search_result = "not_found"
                else:
                    qt = info.get("quoteType", "").upper()
                    asset_class = ("ETF" if qt in ("ETF", "MUTUALFUND")
                                   else "Stock" if qt == "EQUITY"
                                   else qt.title() or "Unknown")
                    if ticker.endswith(".L"):
                        group = "UK Stocks"
                    elif ticker.endswith((".DE", ".PA", ".AS", ".MC", ".MI",
                                         ".SW", ".ST", ".CO", ".HE", ".OL")):
                        group = "EU Stocks"
                    elif asset_class == "ETF":
                        group = "ETFs & Index Funds"
                    else:
                        group = "US Stocks"
                    div_raw   = _f(info.get("dividendYield"))
                    div_yield = None
                    if div_raw is not None:
                        div_yield = round(min(div_raw * 100 if div_raw <= 1.0 else div_raw, 99.0), 2)
                    hist     = t.history(period="1y")
                    price    = _f(hist["Close"].iloc[-1]) if not hist.empty else None
                    high_52w = _f(hist["Close"].max())    if not hist.empty else None
                    low_52w  = _f(hist["Close"].min())    if not hist.empty else None
                    yr1_ret  = None
                    if not hist.empty and len(hist) > 10:
                        yr1_ret = round((hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 1)
                    st.session_state.dd_search_result = {
                        "ticker": ticker, "name": name, "asset_class": asset_class,
                        "group": group,
                        "sector":    info.get("sector") or info.get("fundFamily") or "—",
                        "currency":  info.get("currency", ""),
                        "exchange":  info.get("exchange", ""),
                        "price":     round(price, 2) if price else None,
                        "high_52w":  round(high_52w, 2) if high_52w else None,
                        "low_52w":   round(low_52w, 2)  if low_52w  else None,
                        "yr1_pct":   yr1_ret,
                        "pe":        _f(info.get("trailingPE")),
                        "pb":        _f(info.get("priceToBook")),
                        "div_yield": div_yield,
                        "market_cap":_f(info.get("marketCap")),
                        "ok":        True,
                    }
            except Exception as exc:
                st.session_state.dd_search_result = f"error:{exc}"

    if st.session_state.dd_search_result:
        _render_dd_search_result(st.session_state.dd_add_target)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — HOLDINGS
    # ══════════════════════════════════════════════════════════════════════════
    holdings = st.session_state.holdings
    _section_header("Holdings")
    st.caption("Instruments you own. Track performance against your entry price.")

    if not holdings:
        st.markdown(
            '<div class="changed-banner">'
            'No holdings yet — search above and click <b>Add to Holdings</b>.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        h_tickers = {h["ticker"]: h for h in holdings}
        missing_h = [t for t in h_tickers if t not in live_data]
        if missing_h:
            miss_groups = {h_tickers[t].get("group", "that market") for t in missing_h}
            st.info(
                f"{len(missing_h)} holding(s) have no live data. "
                f"Load **{', '.join(miss_groups)}** to see them."
            )
        for entry in holdings:
            _render_instrument_expander(entry, "holdings", live_data)

    # ══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — WATCHLIST
    # ══════════════════════════════════════════════════════════════════════════
    watchlist = st.session_state.watchlist
    _section_header("Watchlist")
    st.caption("Instruments you are monitoring but do not currently hold.")

    if not watchlist:
        st.markdown(
            '<div class="changed-banner">'
            'Nothing on your watchlist — search above and click <b>Add to Watchlist</b>.'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        wl_tickers = {w["ticker"]: w for w in watchlist}
        missing_wl = [t for t in wl_tickers if t not in live_data]
        if missing_wl:
            miss_groups = {wl_tickers[t].get("group", "that market") for t in missing_wl}
            st.info(
                f"{len(missing_wl)} watchlist item(s) have no live data. "
                f"Load **{', '.join(miss_groups)}** to see them."
            )
        for entry in watchlist:
            _render_instrument_expander(entry, "watchlist", live_data)

    # ── Export holdings + watchlist ────────────────────────────────────────────
    if holdings or watchlist:
        st.markdown("---")
        _exp_h, _exp_wl, _ = st.columns([2, 2, 4])

        def _list_csv(entries, live):
            import io
            _fields = ["ticker", "name", "group", "asset_class", "score",
                       "price", "added_at", "price_when_added", "notes"]
            buf = io.StringIO()
            buf.write(",".join(_fields) + "\n")
            for e in entries:
                live_inst = live.get(e.get("ticker", ""), {})
                row = []
                for f in _fields:
                    v = e.get(f) or live_inst.get(f, "")
                    if isinstance(v, float): v = f"{v:.4f}"
                    elif v is None: v = ""
                    row.append(str(v).replace(",", ";"))
                buf.write(",".join(row) + "\n")
            return buf.getvalue().encode("utf-8")

        if holdings:
            with _exp_h:
                st.download_button(
                    label=f"Export holdings ({len(holdings)})",
                    data=_list_csv(holdings, live_data),
                    file_name=f"holdings_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="holdings_csv_btn",
                )
        if watchlist:
            with _exp_wl:
                st.download_button(
                    label=f"Export watchlist ({len(watchlist)})",
                    data=_list_csv(watchlist, live_data),
                    file_name=f"watchlist_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    key="watchlist_csv_btn",
                )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: COMPARE
# ══════════════════════════════════════════════════════════════════════════════

def page_compare():
    _render_counter.clear()
    st.markdown(
        '<div style="font-family:\'Playfair Display\',Georgia,serif;font-size:38px;'
        'font-weight:700;color:#1A1A1A;letter-spacing:-0.5px;line-height:1.1;'
        'padding-top:32px;padding-bottom:8px">Compare</div>',
        unsafe_allow_html=True,
    )

    instruments = st.session_state.instruments
    if not instruments:
        st.info("Load data first — use the Markets & Data control above.")
        return

    ok      = [x for x in instruments if x.get("ok")]
    options = {f"{x['ticker']}  —  {x['name']}": x for x in ok}

    # Pre-populate with top 2 items from holdings then watchlist
    known_tickers = (
        [h["ticker"] for h in st.session_state.holdings] +
        [w["ticker"] for w in st.session_state.watchlist]
    )
    default_labels = [
        lbl for lbl in options
        if lbl.split("  —  ")[0].strip() in known_tickers
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
    _section_header("Detailed Metrics")

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
        row("Quality gate",      lambda i: "Pass" if i.get("quality_passes") else ("Fail" if i.get("asset_class")=="Stock" else "N/A")),
        row("Value score",       lambda i: f"{_f(i.get('score')):.0f}/100" if _f(i.get("score")) is not None else "—"),
    ]

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=560)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SIGNALS
# ══════════════════════════════════════════════════════════════════════════════

def _severity_colour(sev: str) -> str:
    return {"high": "#777777", "medium": "#444444", "low": "#1A1A1A", "info": "#1A3A5C"}.get(sev, "#777777")

def _severity_icon(sev: str) -> str:
    return {"high": _SVG["dot-high"], "medium": _SVG["dot-medium"], "low": _SVG["dot-low"], "info": _SVG["dot-info"]}.get(sev, _SVG["dot-info"])

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


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: BRIEFING
# ══════════════════════════════════════════════════════════════════════════════

def page_briefing():
    st.markdown(
        '<div style="font-family:\'Playfair Display\',Georgia,serif;font-size:38px;'
        'font-weight:700;color:#1A1A1A;letter-spacing:-0.5px;line-height:1.1;'
        'padding-top:32px;padding-bottom:8px">Morning Briefing</div>',
        unsafe_allow_html=True,
    )

    briefing = load_briefing()

    col_title, col_btn = st.columns([3, 1])
    with col_btn:
        if st.button("Generate Briefing", type="primary", use_container_width=True,
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
        - Macro backdrop (rates, yield curve, VIX, credit spreads)
        - Top value opportunities from your screener
        - Your watchlist at a glance
        - Market-moving headlines
        - Alerts requiring attention

        Click **Generate Briefing** to run the surveillance engine.
        """)
        return

    with col_title:
        st.caption(f"Generated: {briefing.get('date_str', '')}")

    # ── Headline ───────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:#FFFFFF;border:1px solid #D4D4D2;'
        f'border-left:3px solid #1A3A5C;border-radius:0;'
        f'padding:18px 22px;margin-bottom:18px;font-family:\'Inter\',sans-serif;'
        f'font-size:0.92rem;color:#444444;line-height:1.7;box-shadow:var(--vs-shadow)">'
        f'<b style="color:#1A1A1A;font-weight:600;display:block;margin-bottom:6px">Today\'s Summary</b>'
        f'{briefing.get("headline","")}</div>',
        unsafe_allow_html=True,
    )

    # ── Macro section ──────────────────────────────────────────────────────────
    macro = briefing.get("macro", {})
    tone  = macro.get("tone", "mixed")
    tone_colours = {"constructive": "#1A1A1A", "mixed": "#444444", "cautious": "#777777"}
    tone_col = tone_colours.get(tone, "#777777")

    with st.expander(f"Macro — {tone.title()} backdrop", expanded=True):
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
        with st.expander(f"High-priority alerts ({len(high_sigs)})", expanded=True):
            for sig in high_sigs:
                col = _severity_colour(sig.get("severity", "high"))
                st.markdown(
                    f'<div style="border-left:3px solid {col};padding:10px 14px;'
                    f'margin-bottom:8px;background:#F8F8F6;border-radius:0;'
                    f'border:1px solid #D4D4D2">'
                    f'<b style="color:#1A1A1A;font-size:0.88rem">{sig["title"]}</b><br>'
                    f'<span style="color:#444444;font-size:0.83rem">{sig.get("detail","")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── Top opportunities ──────────────────────────────────────────────────────
    opportunities = briefing.get("opportunities", [])
    if opportunities:
        with st.expander(f"Top value picks ({len(opportunities)})", expanded=True):
            pairs = [opportunities[i:i+2] for i in range(0, len(opportunities), 2)]
            for pair in pairs:
                cols = st.columns(2)
                for j, opp in enumerate(pair):
                    with cols[j]:
                        opp_score = _f(opp.get("score"))
                        opp_score_cls = "card-score-block" + ("" if opp_score and opp_score >= 45 else " low")
                        opp_score_disp = f"{opp_score:.0f}" if opp_score is not None else "—"
                        opp_lbl = score_label(opp_score) if opp_score is not None else "—"
                        st.markdown(
                            f'<div class="card">'
                            f'<div class="card-header">'
                            f'<div style="flex:1;min-width:0">'
                            f'<div class="card-name">{opp.get("name","")}</div>'
                            f'<div class="card-ticker-line"><span class="ticker">{opp.get("ticker","")}</span></div>'
                            f'<div class="card-market-line">{opp.get("group","")}</div>'
                            f'</div>'
                            f'<div class="{opp_score_cls}">'
                            f'<div class="card-score-num">{opp_score_disp}</div>'
                            f'<div class="card-score-lbl">{opp_lbl}</div>'
                            f'</div></div>'
                            f'<div class="card-bullets"><div class="card-bullet">'
                            f'<span class="card-bullet-icon">↑</span>'
                            f'<span>{opp.get("verdict","")}</span></div></div>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

    # ── Watchlist ──────────────────────────────────────────────────────────────
    wl_data = briefing.get("watchlist", [])
    if wl_data:
        with st.expander(f"Your watchlist ({len(wl_data)} items)", expanded=False):
            for item in wl_data:
                score_val = _f(item.get("score"))
                score_col = "#1A1A1A" if score_val and score_val >= 45 else "#777777"
                ytd_str   = _fmt_pct(item.get("ytd_pct"))
                yr1_str   = _fmt_pct(item.get("yr1_pct"))
                st.markdown(
                    f'<div style="display:flex;justify-content:space-between;padding:9px 0;'
                    f'border-bottom:1px solid #E0E0DE">'
                    f'<div><b style="color:#1A1A1A;font-weight:600">{item.get("name","")}</b> '
                    f'<span style="color:#777777;font-size:0.82rem">{item.get("ticker","")}</span></div>'
                    f'<div style="display:flex;gap:16px;align-items:center">'
                    f'<span style="color:#777777;font-size:0.8rem">YTD {ytd_str}</span>'
                    f'<span style="color:#777777;font-size:0.8rem">1Y {yr1_str}</span>'
                    f'<span style="color:{score_col};font-weight:600">{item.get("score","—")}</span>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    # ── News highlights ────────────────────────────────────────────────────────
    news_items = briefing.get("news_highlights", [])
    if news_items:
        with st.expander(f"Market headlines ({len(news_items)})", expanded=False):
            for item in news_items:
                sent = item.get("sentiment", 0)
                col  = "#1A1A1A" if sent > 0.2 else "#777777" if sent < -0.2 else "#777777"
                icon = "▲" if sent > 0.2 else "▼" if sent < -0.2 else "─"
                link = item.get("link", "")
                title = item.get("title", "")
                feed  = item.get("feed", "")
                if link:
                    st.markdown(
                        f'<div style="padding:7px 0;border-bottom:1px solid #E0E0DE">'
                        f'<span style="color:{col};font-size:0.75rem">{icon} </span>'
                        f'<a href="{link}" target="_blank" style="color:#1A1A1A;text-decoration:none;'
                        f'font-size:0.87rem">{title}</a>'
                        f'<span style="color:#AAAAAA;font-size:0.74rem"> · {feed}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="padding:7px 0;border-bottom:1px solid #E0E0DE">'
                        f'<span style="color:{col};font-size:0.75rem">{icon} </span>'
                        f'<span style="color:#1A1A1A;font-size:0.87rem">{title}</span>'
                        f'<span style="color:#AAAAAA;font-size:0.74rem"> · {feed}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            st.markdown('<div style="height:4px"></div>', unsafe_allow_html=True)

    # ── Full signals feed (dedicated section) ──────────────────────────────────
    st.markdown("---")
    _section_header("Signals Feed")

    _all_signals = load_latest_signals()
    _last_run    = get_last_run_time()
    _sig_caption = f"Last updated: {_last_run}" if _last_run else "No signals run yet"
    st.caption(_sig_caption)

    if not _all_signals:
        st.info(
            "No signals generated yet.  Click **Generate Briefing** above to run the "
            "surveillance engine — it will populate this feed with score drift, "
            "value opportunities, macro warnings, news alerts, and insider signals."
        )
    else:
        # Filter tabs: All / High / Holdings / Macro
        _my_tickers = {
            i.get("ticker") for i in (
                st.session_state.watchlist + st.session_state.holdings
            ) if i.get("ticker")
        }
        _tab_all, _tab_high, _tab_mine, _tab_macro = st.tabs(
            [f"All ({len(_all_signals)})",
             f"High priority ({sum(1 for s in _all_signals if s.get('severity') == 'high')})",
             f"My holdings ({sum(1 for s in _all_signals if s.get('ticker') in _my_tickers)})",
             "Macro"]
        )

        def _render_signals_list(sigs):
            if not sigs:
                st.caption("No signals in this category.")
                return
            for sig in sorted(sigs, key=lambda s: {"high": 0, "medium": 1, "low": 2, "info": 3}.get(s.get("severity", "info"), 3)):
                _sev  = sig.get("severity", "info")
                _col  = _severity_colour(_sev)
                _icon = _severity_icon(_sev)
                _ts   = sig.get("generated_at", sig.get("timestamp", ""))[:10] if sig.get("generated_at") or sig.get("timestamp") else ""
                st.markdown(
                    f'<div style="border-left:3px solid {_col};padding:10px 14px 10px 14px;'
                    f'margin-bottom:6px;background:#FFFFFF;border:1px solid #D4D4D2;'
                    f'border-left-width:3px">'
                    f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
                    f'<div>'
                    f'<span style="font-size:0.75rem;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:0.06em;color:{_col}">{_type_label(sig.get("type",""))}</span>'
                    f'<b style="display:block;color:#1A1A1A;font-size:0.88rem;margin-top:3px">'
                    f'{sig.get("title","")}</b>'
                    f'<span style="color:#444444;font-size:0.82rem">{sig.get("detail","")}</span>'
                    f'</div>'
                    f'<div style="text-align:right;flex-shrink:0;padding-left:12px">'
                    f'<span style="font-size:0.75rem;color:#AAAAAA">{_ts}</span>'
                    + (f'<br><span class="ticker" style="font-size:0.75rem">{sig.get("ticker","")}</span>'
                       if sig.get("ticker") else "")
                    + f'</div></div></div>',
                    unsafe_allow_html=True,
                )

        with _tab_all:
            _render_signals_list(_all_signals)
        with _tab_high:
            _render_signals_list([s for s in _all_signals if s.get("severity") == "high"])
        with _tab_mine:
            _render_signals_list([s for s in _all_signals if s.get("ticker") in _my_tickers])
        with _tab_macro:
            _macro_types = {"macro_warning", "macro_positive", "macro_info"}
            _render_signals_list([s for s in _all_signals if s.get("type") in _macro_types])


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS (Scoring Logic)
# ══════════════════════════════════════════════════════════════════════════════

def page_settings():
    _render_counter.clear()
    st.markdown(
        '<div style="font-family:\'Playfair Display\',Georgia,serif;font-size:38px;'
        'font-weight:700;color:#1A1A1A;letter-spacing:-0.5px;line-height:1.1;'
        'padding-top:32px;padding-bottom:4px">Scoring Settings</div>'
        '<div style="font-family:\'Inter\',sans-serif;font-size:13px;color:#777777;'
        'margin-bottom:24px">Adjust how instruments are scored. Changes take effect when '
        'you click Apply &amp; Rescore — no data is re-fetched, scoring is instant.</div>',
        unsafe_allow_html=True,
    )

    p   = st.session_state.prefs
    changed = False  # tracks whether any value changed this render

    # ── Helper: weight bar visual ─────────────────────────────────────────────
    def _weight_bar(vals: list, labels: list):
        """Tiny horizontal stacked bar showing relative weight distribution."""
        total = sum(vals) or 1
        segments = ""
        colours = ["#1A3A5C", "#444444", "#777777", "#1A1A1A", "#AAAAAA"]
        for i, (v, lbl) in enumerate(zip(vals, labels)):
            pct = v / total * 100
            col = colours[i % len(colours)]
            segments += (
                f'<div title="{lbl}: {pct:.0f}%" style="flex:{v};background:{col};'
                f'height:8px;min-width:2px"></div>'
            )
        st.markdown(
            f'<div style="display:flex;gap:1px;border-radius:0;overflow:hidden;margin-bottom:4px">{segments}</div>',
            unsafe_allow_html=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 1: STOCK QUALITY GATE
    # ═══════════════════════════════════════════════════════════════════════
    with st.expander("Stock Quality Gate — who gets scored", expanded=True):
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
    with st.expander("Stock Valuation — what matters most", expanded=True):
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
            st.markdown(
                '<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-left:3px solid #777777;'
                'padding:8px 12px;font-family:var(--vs-sans),sans-serif;font-size:12px;color:#444444;">'
                'All weights are zero — stocks cannot be scored.</div>',
                unsafe_allow_html=True,
            )
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
    with st.expander("ETF & Index Fund scoring weights", expanded=False):
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
    with st.expander("Money Market & Short Duration weights", expanded=False):
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
        save_prefs(_uid(), p)
        st.session_state.scoring_changed = True

    apply_col, reset_col, _ = st.columns([2, 2, 4])

    with apply_col:
        apply_disabled = not (st.session_state.instruments)
        if st.button(
            "Apply & Rescore",
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
        if st.button("Reset to defaults", use_container_width=True):
            defaults = {
                "min_roe": 10, "max_de": 2, "min_profit_margin": 2, "require_pos_fcf": True,
                "wt_pe": 30, "wt_pb": 20, "wt_evebitda": 20, "wt_divyield": 15, "wt_52w": 15,
                "wt_etf_aum": 35, "wt_etf_ter": 35, "wt_etf_ret": 20, "wt_etf_mom": 10,
                "wt_mm_yield": 60, "wt_mm_aum": 25, "wt_mm_ter": 15,
            }
            for k, v in defaults.items():
                p[k] = v
            save_prefs(_uid(), p)
            st.session_state.scoring_changed = True
            st.session_state.toast = ("Settings reset to defaults — click Apply & Rescore", "info")
            st.rerun()

    if apply_disabled:
        st.markdown(
            '<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-left:3px solid #1A3A5C;'
            'padding:10px 14px;font-family:var(--vs-sans),sans-serif;font-size:13px;color:#444444;">'
            'Load data from the Markets &amp; Data section above, then click Apply &amp; Rescore.</div>',
            unsafe_allow_html=True,
        )
    elif st.session_state.scoring_changed:
        st.markdown(
            '<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-left:3px solid #777777;'
            'padding:8px 12px;font-family:var(--vs-sans),sans-serif;font-size:12px;color:#444444;">'
            'Settings changed — click <strong>Apply &amp; Rescore</strong> to update scores.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div style="background:#FFFFFF;border:1px solid #D4D4D2;border-left:3px solid #1A3A5C;'
            'padding:8px 12px;font-family:var(--vs-sans),sans-serif;font-size:12px;color:#444444;">'
            'Scores are up to date with current settings.</div>',
            unsafe_allow_html=True,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # SECTION 5: TICKER MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════
    st.markdown("---")
    _section_header("Custom Tickers")
    st.markdown(
        "Add instruments beyond the built-in universe (FTSE 100, S&P 500, EU stocks, ETFs). "
        "Enter any valid yfinance ticker symbol. Custom tickers are fetched and scored "
        "alongside the main universe on your next data refresh."
    )

    _custom = load_custom_tickers(_uid())

    # Add new ticker
    with st.expander("Add a custom ticker", expanded=not _custom):
        _add_cols = st.columns([2, 2, 2, 1])
        with _add_cols[0]:
            _new_ticker = st.text_input("Ticker symbol", placeholder="e.g. NOVO-B.CO",
                                        key="custom_ticker_input").strip().upper()
        with _add_cols[1]:
            _new_name = st.text_input("Display name (optional)", placeholder="e.g. Novo Nordisk",
                                      key="custom_name_input")
        with _add_cols[2]:
            _new_group = st.selectbox(
                "Group",
                ["UK Stocks", "EU Stocks", "US Stocks", "ETFs & Index Funds",
                 "Money Market & Short Duration", "Custom"],
                index=5,
                key="custom_group_input",
            )
        with _add_cols[3]:
            _new_ac = st.selectbox("Asset class", ["Stock", "ETF", "Money Market"],
                                   key="custom_ac_input")

        if st.button("Add ticker", key="custom_add_btn", type="primary"):
            if not _new_ticker:
                st.error("Please enter a ticker symbol.")
            else:
                ok = add_custom_ticker(
                    _uid(), _new_ticker,
                    name=_new_name or _new_ticker,
                    group_name=_new_group,
                    asset_class=_new_ac,
                )
                if ok:
                    st.session_state.toast = (
                        f"{_new_ticker} added — refresh data to include it in scores", "success"
                    )
                    st.rerun()
                else:
                    st.warning(f"{_new_ticker} is already in your custom list.")

    # Current custom tickers
    if _custom:
        st.markdown(f"**{len(_custom)} custom ticker(s)**")
        for ct in _custom:
            _ct_c1, _ct_c2, _ct_c3, _ct_c4 = st.columns([2, 2, 2, 1])
            _ct_c1.markdown(f"**{ct['ticker']}**")
            _ct_c2.markdown(ct.get("name", ""))
            _ct_c3.markdown(f"{ct.get('group_name','—')} · {ct.get('asset_class','Stock')}")
            with _ct_c4:
                if st.button("Remove", key=f"rm_custom_{ct['ticker']}",
                             use_container_width=True):
                    remove_custom_ticker(_uid(), ct["ticker"])
                    st.session_state.toast = (f"Removed {ct['ticker']}", "info")
                    st.rerun()
    else:
        st.caption("No custom tickers yet.")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════

page = st.session_state.page
if   page == "home":      page_home()
elif page == "screener":  page_screener()
elif page == "deepdive":  page_deepdive()
elif page == "compare":   page_compare()
elif page == "briefing":  page_briefing()
elif page == "settings":  page_settings()
elif page == "watchlist":
    # Redirect legacy page key → deepdive (watchlist lives there)
    st.session_state.page = "deepdive"
    st.rerun()
elif page == "signals":
    # Redirect legacy signals page → briefing (signals feed lives there)
    st.session_state.page = "briefing"
    st.rerun()
else:
    st.session_state.page = "home"
    st.rerun()

