#!/usr/bin/env python3
"""
apply_news_patch.py
Integrates the news_fetcher module into Value Screener v3:

  1. Copy surveillance/news_fetcher.py into the repo
  2. Patch app.py — add news import
  3. Patch app.py — add 📰 News nav item
  4. Patch app.py — add page_news() function
  5. Patch app.py — add news signals section to page_surveillance()
  6. Patch app.py — add news context block to Holdings deep analysis
  7. Patch app.py — add trending news to Briefing AI prompt

Run from inside the "Value Screener v3" folder:
    python3 apply_news_patch.py
"""

import sys, shutil
from pathlib import Path

ROOT = Path(".")
if not (ROOT / "app.py").exists():
    sys.exit("ERROR: run this from inside the 'Value Screener v3' folder")

# ── 0: Copy news_fetcher.py into repo ─────────────────────────────────────────

SURVEILLANCE_DIR = ROOT / "surveillance"
SURVEILLANCE_DIR.mkdir(exist_ok=True)

# Create __init__.py if missing
init_path = SURVEILLANCE_DIR / "__init__.py"
if not init_path.exists():
    init_path.write_text("", encoding="utf-8")

SRC_NEWS = Path(__file__).with_name("news_fetcher.py")
if SRC_NEWS.exists():
    shutil.copy2(SRC_NEWS, SURVEILLANCE_DIR / "news_fetcher.py")
    print("✓ Step 0: surveillance/news_fetcher.py copied into repo")
else:
    print("⚠ Step 0 SKIPPED: news_fetcher.py not found next to this script")
    print("  Copy news_fetcher.py from outputs/ into surveillance/news_fetcher.py manually")

# ── Load app.py ───────────────────────────────────────────────────────────────

app_path = ROOT / "app.py"
src = app_path.read_text(encoding="utf-8")
original = src

# ── Patch 1: Add news import after existing surveillance imports ──────────────

OLD_SURV_IMPORT = """from surveillance.briefing  import generate_morning_briefing"""

NEW_SURV_IMPORT = """from surveillance.briefing  import generate_morning_briefing
try:
    from surveillance.news_fetcher import (
        fetch_market_news, get_signals_from_news,
        get_news_for_ticker, get_trending_stories,
        get_news_summary_for_briefing, news_cache_age_minutes,
    )
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False"""

if OLD_SURV_IMPORT in src:
    src = src.replace(OLD_SURV_IMPORT, NEW_SURV_IMPORT, 1)
    print("✓ Patch 1: news_fetcher imports added")
else:
    # Fallback — add after the last 'from surveillance' import
    if "NEWS_AVAILABLE" not in src:
        FALLBACK_IMPORT = """try:
    from surveillance.news_fetcher import (
        fetch_market_news, get_signals_from_news,
        get_news_for_ticker, get_trending_stories,
        get_news_summary_for_briefing, news_cache_age_minutes,
    )
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False
"""
        # Insert before first def or class after imports
        idx = src.find("\n\n# ─")
        if idx == -1:
            idx = src.find("\nUNIVERSE")
        if idx != -1:
            src = src[:idx] + "\n" + FALLBACK_IMPORT + src[idx:]
            print("✓ Patch 1 (fallback): news_fetcher imports added at top of file")
        else:
            print("⚠ Patch 1 SKIPPED: could not locate import insertion point")
    else:
        print("⚠ Patch 1 SKIPPED: NEWS_AVAILABLE already present")

# ── Patch 2: Add 📰 News to nav pages dict ────────────────────────────────────

OLD_NAV = '''    pages = {
        "🔍 Screen":     page_screener,
        "⭐ Holdings":   page_watchlist,
        "🚨 Signals":    page_surveillance,
        "📰 Briefing":   page_briefing,
        "⚙️  Settings":   page_settings,
    }'''

NEW_NAV = '''    pages = {
        "🔍 Screen":     page_screener,
        "⭐ Holdings":   page_watchlist,
        "🚨 Signals":    page_surveillance,
        "📡 News":       page_news,
        "📰 Briefing":   page_briefing,
        "⚙️  Settings":   page_settings,
    }'''

if OLD_NAV in src:
    src = src.replace(OLD_NAV, NEW_NAV, 1)
    print("✓ Patch 2: 📡 News added to navigation")
elif "📡 News" not in src:
    print("⚠ Patch 2 SKIPPED: nav pages dict not found in expected format")
else:
    print("⚠ Patch 2 SKIPPED: 📡 News already in nav")

# ── Patch 3: Insert page_news() before page_briefing() ───────────────────────

PAGE_NEWS_FUNC = '''

# ─────────────────────────────────────────────────────────────────────────────
def page_news():
    """📡 News — market headlines with sentiment, ticker matching, refresh."""
    st.markdown("# 📡 News")

    if not NEWS_AVAILABLE:
        st.warning("News module not available. "
                   "Install finnews: `pip install finnews fake-useragent`")
        return

    # ── Controls ───────────────────────────────────────────────────────────
    col_refresh, col_age, _ = st.columns([1, 2, 4])
    with col_refresh:
        if st.button("🔄 Refresh News", use_container_width=True):
            fetch_market_news(force=True)
            st.rerun()
    with col_age:
        _age = news_cache_age_minutes()
        if _age is not None:
            _age_str = f"{int(_age)}m ago" if _age < 60 else f"{_age/60:.1f}h ago"
            st.caption(f"Last fetched {_age_str}")
        else:
            st.caption("Not yet fetched")

    st.markdown("---")

    # ── Fetch articles ─────────────────────────────────────────────────────
    with st.spinner("Loading news…"):
        articles = fetch_market_news()

    if not articles:
        st.info("No news articles found. Check your internet connection or try refreshing.")
        return

    # ── Filter controls ────────────────────────────────────────────────────
    col_sent, col_src, _ = st.columns([2, 2, 3])
    with col_sent:
        sentiment_filter = st.selectbox(
            "Sentiment", ["All", "Positive", "Negative", "Neutral"],
            key="news_sentiment_filter"
        )
    with col_src:
        sources = sorted({a.get("source", "Other") for a in articles})
        source_filter = st.selectbox(
            "Source", ["All"] + sources, key="news_source_filter"
        )

    # Apply filters
    filtered = articles
    if sentiment_filter != "All":
        filtered = [a for a in filtered
                    if a.get("sentiment_label", "neutral").lower() == sentiment_filter.lower()]
    if source_filter != "All":
        filtered = [a for a in filtered if a.get("source") == source_filter]

    st.caption(f"Showing {len(filtered)} of {len(articles)} articles")
    st.markdown("")

    # ── Render articles ────────────────────────────────────────────────────
    SENT_EMOJI = {"positive": "📈", "negative": "📉", "neutral": "📰"}
    SENT_COLOR = {"positive": "#2ecc71", "negative": "#e74c3c", "neutral": "#95a5a6"}

    for art in filtered[:40]:
        label = art.get("sentiment_label", "neutral")
        emoji = SENT_EMOJI.get(label, "📰")
        color = SENT_COLOR.get(label, "#95a5a6")
        score = art.get("sentiment", 0)
        source = art.get("source", "")
        published = art.get("published", "")
        url = art.get("url", "")
        title = art.get("title", "No title")
        summary = art.get("summary", "")

        # Format published time
        pub_str = ""
        if published:
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(published.replace("Z", "+00:00"))
                pub_str = dt.strftime("%d %b %Y, %H:%M")
            except Exception:
                pub_str = published[:16]

        score_str = f"{score:+.2f}" if score else ""

        with st.container():
            st.markdown(
                f'<div style="border-left: 3px solid {color}; padding: 8px 12px; '
                f'margin-bottom: 10px; background: rgba(0,0,0,0.02); border-radius: 0 4px 4px 0;">'
                f'<div style="font-size: 0.75rem; color: #888; margin-bottom: 2px;">'
                f'{emoji} {source} · {pub_str}</div>'
                f'<div style="font-weight: 600; font-size: 0.95rem;">'
                f'{"[" + title + "](" + url + ")" if url else title}</div>'
                + (f'<div style="font-size: 0.82rem; color: #666; margin-top: 4px;">{summary}</div>' if summary else "")
                + (f'<div style="font-size: 0.75rem; color: {color}; margin-top: 4px;">Sentiment: {score_str}</div>' if score_str else "")
                + "</div>",
                unsafe_allow_html=True
            )

    if len(filtered) > 40:
        st.caption(f"Showing first 40 articles. Use filters to narrow results.")

'''

OLD_BRIEFING_FUNC = '''
# ─────────────────────────────────────────────────────────────────────────────
def page_briefing():'''

# Also try without the separator line
OLD_BRIEFING_FUNC_ALT = '''\ndef page_briefing():'''

if PAGE_NEWS_FUNC.strip() not in src:
    if OLD_BRIEFING_FUNC in src:
        src = src.replace(OLD_BRIEFING_FUNC, PAGE_NEWS_FUNC + "\n# ─────────────────────────────────────────────────────────────────────────────\ndef page_briefing():", 1)
        print("✓ Patch 3: page_news() function inserted before page_briefing()")
    elif "def page_briefing():" in src:
        src = src.replace("def page_briefing():", PAGE_NEWS_FUNC + "def page_briefing():", 1)
        print("✓ Patch 3 (fallback): page_news() inserted before page_briefing()")
    else:
        print("⚠ Patch 3 SKIPPED: page_briefing() not found — insert page_news() manually")
else:
    print("⚠ Patch 3 SKIPPED: page_news() already present")

# ── Patch 4: Add news signals section to page_surveillance() ─────────────────
# Find the end of page_surveillance where it renders existing signals,
# and add a "News Signals" expandable section.

OLD_SURV_RETURN = '''    # ── Surveillance signals ──────────────────────────────────────────────
    st.markdown(\'\'\'<div class="section-header">Active signals</div>\'\'\',
                unsafe_allow_html=True)'''

NEW_SURV_WITH_NEWS = '''    # ── News Signals ───────────────────────────────────────────────────────
    if NEWS_AVAILABLE and st.session_state.instruments:
        _news_signals = get_signals_from_news(
            st.session_state.instruments, max_signals=15
        )
        if _news_signals:
            st.markdown(\'\'\'<div class="section-header">📡 News signals</div>\'\'\',
                        unsafe_allow_html=True)
            SENT_EMOJI = {"positive": "📈", "negative": "📉", "neutral": "📰"}
            for sig in _news_signals[:10]:
                _e = SENT_EMOJI.get(sig.get("sentiment_label", "neutral"), "📰")
                _sent = sig.get("sentiment", 0)
                _url  = sig.get("url", "")
                _hl   = sig.get("headline", "")
                _link = f"[{_hl}]({_url})" if _url else _hl
                _score_str = f" · score {sig.get(\'score\', \'n/a\')}" if sig.get("score") else ""
                st.markdown(
                    f"**{sig[\'ticker\']}** — {sig[\'name\']}{_score_str}  \\n"
                    f"{_e} {_link}  \\n"
                    f"<small>Sentiment: {_sent:+.2f} · {sig.get(\'source\', \'\')}</small>",
                    unsafe_allow_html=True
                )
            st.markdown("---")

    # ── Surveillance signals ──────────────────────────────────────────────
    st.markdown(\'\'\'<div class="section-header">Active signals</div>\'\'\',
                unsafe_allow_html=True)'''

if OLD_SURV_RETURN in src:
    src = src.replace(OLD_SURV_RETURN, NEW_SURV_WITH_NEWS, 1)
    print("✓ Patch 4: News signals section added to Signals page")
else:
    print("⚠ Patch 4 SKIPPED: Signals page section header not found in expected format")

# ── Patch 5: Add news context to Holdings deep analysis AI prompt ─────────────

OLD_BRIEFING_PROMPT = '''            prompt = f"""You are a value investing analyst. Provide a concise deep-dive analysis of {name} ({ticker}).'''

NEW_BRIEFING_PROMPT = '''            # News context for this ticker
            _ticker_news = ""
            if NEWS_AVAILABLE:
                try:
                    _ticker_articles = get_news_for_ticker(ticker, name, max_articles=5)
                    if _ticker_articles:
                        _news_lines = []
                        for _a in _ticker_articles:
                            _label = _a.get("sentiment_label", "neutral")
                            _emoji = {"positive": "📈", "negative": "📉", "neutral": "📰"}.get(_label, "📰")
                            _news_lines.append(f"  {_emoji} {_a.get(\'title\', \'\')}")
                        _ticker_news = "\\nRecent news headlines:\\n" + "\\n".join(_news_lines)
                except Exception:
                    pass

            prompt = f"""You are a value investing analyst. Provide a concise deep-dive analysis of {name} ({ticker}).{_ticker_news}'''

if OLD_BRIEFING_PROMPT in src:
    src = src.replace(OLD_BRIEFING_PROMPT, NEW_BRIEFING_PROMPT, 1)
    print("✓ Patch 5: News context injected into Holdings deep analysis AI prompt")
else:
    print("⚠ Patch 5 SKIPPED: Holdings AI prompt not found in expected format")

# ── Patch 6: Add trending news to Morning Briefing AI prompt ─────────────────

OLD_BRIEFING_GEN = '''        prompt = _build_briefing_prompt('''

NEW_BRIEFING_GEN = '''        # Prepend trending news to briefing context
        _trending_news_text = ""
        if NEWS_AVAILABLE:
            try:
                _trending_news_text = get_news_summary_for_briefing(max_stories=10)
            except Exception:
                pass

        prompt = _build_briefing_prompt('''

if OLD_BRIEFING_GEN in src and "_trending_news_text" not in src:
    src = src.replace(OLD_BRIEFING_GEN, NEW_BRIEFING_GEN, 1)
    print("✓ Patch 6a: Trending news fetched before Morning Briefing generation")

    # Now inject the text into the briefing prompt builder call if possible
    # The briefing prompt likely ends with st.session_state etc — add news as extra context
    OLD_BRIEFING_PROMPT_CALL = '''        result = generate_morning_briefing(prompt)'''
    NEW_BRIEFING_PROMPT_CALL = '''        # Append trending news to prompt if available
        if _trending_news_text:
            prompt = prompt + "\\n\\n## Today\\'s market headlines\\n" + _trending_news_text
        result = generate_morning_briefing(prompt)'''

    if OLD_BRIEFING_PROMPT_CALL in src and "Today\\'s market headlines" not in src:
        src = src.replace(OLD_BRIEFING_PROMPT_CALL, NEW_BRIEFING_PROMPT_CALL, 1)
        print("✓ Patch 6b: Trending news appended to Morning Briefing AI prompt")
    else:
        print("⚠ Patch 6b SKIPPED: generate_morning_briefing call not found or already patched")
else:
    print("⚠ Patch 6 SKIPPED: Briefing generation block not found or already patched")

# ── Write app.py ───────────────────────────────────────────────────────────────
if src != original:
    app_path.write_text(src, encoding="utf-8")
    print(f"\n✅ app.py updated ({app_path.stat().st_size:,} bytes)")
else:
    print("\n⚠ app.py unchanged — all patches skipped.")

print("\nDone. Open GitHub Desktop, review the diff, and push to deploy.")
print("\nAlso add to requirements.txt if not already present:")
print("  finnews")
print("  fake-useragent")
print("  vaderSentiment (already present as vadersentiment)")
