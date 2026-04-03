#!/usr/bin/env python3
"""
apply_scoring_v2_patch.py
Run this once from the "Value Screener v3" folder to apply the deep value
scoring model changes to app.py.

    cd ~/Documents/Value\ Screener\ v3
    python3 apply_scoring_v2_patch.py
"""

import re, sys
from pathlib import Path

APP = Path("app.py")
if not APP.exists():
    sys.exit("ERROR: run this from inside the 'Value Screener v3' folder")

src = APP.read_text(encoding="utf-8")
original = src


# ────────────────────────────────────────────────────────────────────────────
# PATCH 1: Replace old stock weight defaults in _init_state
# ────────────────────────────────────────────────────────────────────────────

OLD_WEIGHTS = '''        # Stock valuation weights (relative importance, 0–100)
        "wt_pe":       30,
        "wt_pb":       20,
        "wt_evebitda": 20,
        "wt_divyield": 15,
        "wt_52w":      15,'''

NEW_WEIGHTS = '''        # Non-financial stock weights (sector-relative deep value model)
        "wt_evebitda":   30,   # EV/EBITDA — best enterprise cheapness measure
        "wt_pfcf":       25,   # P/FCF — real cash generation
        "wt_pe":         15,   # P/E — familiar but noisy
        "wt_pb":         10,   # P/B — asset backing
        "wt_divyield":   10,   # Dividend yield
        "wt_52w":        10,   # 52w position — contrarian signal
        # Financial sector stock weights (banks, insurers, asset managers)
        "wt_fin_ptb":    35,   # Price/Tangible Book
        "wt_fin_roe":    30,   # ROE vs sector peers
        "wt_fin_yield":  20,   # Dividend yield
        "wt_fin_52w":    15,   # 52w contrarian signal
        # Financial quality gate
        "fin_min_roe":          6,
        "fin_max_price_book":   2.0,
        "fin_require_pos_fcf":  False,'''

if OLD_WEIGHTS in src:
    src = src.replace(OLD_WEIGHTS, NEW_WEIGHTS)
    print("✓ Patch 1 applied: weight defaults updated")
else:
    print("⚠ Patch 1 SKIPPED — old weight block not found (already patched?)")


# ────────────────────────────────────────────────────────────────────────────
# PATCH 2: Settings page — Stock Valuation section
# Replace the 5-slider block with the new 6-slider non-financial + financial blocks
# ────────────────────────────────────────────────────────────────────────────

OLD_SETTINGS_STOCK = '''    with st.expander("📊 Stock Valuation — what matters most", expanded=True):
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
            changed = True'''

NEW_SETTINGS_STOCK = '''    with st.expander("📊 Non-financial stocks — valuation weights", expanded=True):
        st.markdown(
            "Weights for companies **outside** banking, insurance, and asset management. "
            "All metrics are scored **relative to the sector median** — a stock only needs "
            "to be cheap *for its sector*, so utilities won't crowd out tech. "
            "Adjust relative importance; the engine normalises automatically."
        )
        st.markdown("---")

        sc1, sc2 = st.columns(2)
        with sc1:
            new_wt_ev = st.slider(
                "EV/EBITDA importance",
                0, 100, p.get("wt_evebitda", 30), 5,
                help="Enterprise Value / EBITDA — best single measure of enterprise cheapness. "
                     "Strips out capital structure differences, good for cross-border comparison.",
            )
            new_wt_fcf = st.slider(
                "P/FCF importance",
                0, 100, p.get("wt_pfcf", 25), 5,
                help="Price / Free Cash Flow — rewards real cash generation. "
                     "Harder to manipulate than earnings. Stocks with negative FCF fail quality gate.",
            )
            new_wt_pe = st.slider(
                "P/E importance",
                0, 100, p.get("wt_pe", 15), 5,
                help="Price-to-Earnings — familiar but noisy. Lower weight than before "
                     "because earnings are more easily manipulated than cash flow.",
            )
        with sc2:
            new_wt_pb = st.slider(
                "P/B importance",
                0, 100, p.get("wt_pb", 10), 5,
                help="Price-to-Book — useful as an asset backing check. "
                     "Less meaningful for asset-light businesses.",
            )
            new_wt_dy = st.slider(
                "Dividend yield importance",
                0, 100, p.get("wt_divyield", 10), 5,
                help="Higher yield = more income return and management confidence. "
                     "Set to 0 if screening for growth stocks that reinvest.",
            )
            new_wt_52 = st.slider(
                "52-week position importance",
                0, 100, p.get("wt_52w", 10), 5,
                help="Contrarian signal — near 52w lows may indicate an oversold opportunity. "
                     "Use alongside the quality gate to avoid value traps.",
            )

        wvals  = [new_wt_ev, new_wt_fcf, new_wt_pe, new_wt_pb, new_wt_dy, new_wt_52]
        wlabls = ["EV/EBITDA", "P/FCF", "P/E", "P/B", "Yield", "52w"]
        _weight_bar(wvals, wlabls)
        total_w = sum(wvals)
        if total_w == 0:
            st.warning("⚠ All weights are zero — non-financial stocks cannot be scored.")
        else:
            pcts = "  ·  ".join(
                f"**{l}** {v/total_w*100:.0f}%" for l, v in zip(wlabls, wvals) if v > 0
            )
            st.caption(f"Effective split: {pcts}")

        if (new_wt_ev != p.get("wt_evebitda") or new_wt_fcf != p.get("wt_pfcf")
                or new_wt_pe != p.get("wt_pe") or new_wt_pb != p.get("wt_pb")
                or new_wt_dy != p.get("wt_divyield") or new_wt_52 != p.get("wt_52w")):
            p["wt_evebitda"] = new_wt_ev
            p["wt_pfcf"]     = new_wt_fcf
            p["wt_pe"]       = new_wt_pe
            p["wt_pb"]       = new_wt_pb
            p["wt_divyield"] = new_wt_dy
            p["wt_52w"]      = new_wt_52
            changed = True

    with st.expander("🏦 Financial stocks — valuation weights", expanded=True):
        st.markdown(
            "Separate model for **banks, insurers, and asset managers**. "
            "D/E is removed (leverage is structural for financials). "
            "Uses Price/Tangible Book and ROE vs sector peers instead."
        )
        st.markdown("---")

        fc1, fc2 = st.columns(2)
        with fc1:
            new_fin_ptb = st.slider(
                "Price/Tangible Book importance",
                0, 100, p.get("wt_fin_ptb", 35), 5,
                help="Primary valuation anchor for financials. Strips goodwill from acquisitions. "
                     "Below 1x = potentially very cheap; above 2x = rarely deep value.",
            )
            new_fin_roe = st.slider(
                "ROE vs sector peers importance",
                0, 100, p.get("wt_fin_roe", 30), 5,
                help="Return on Equity vs sector median — rewards banks that earn well "
                     "relative to their peers, not an absolute ROE threshold.",
            )
        with fc2:
            new_fin_yield = st.slider(
                "Dividend yield importance",
                0, 100, p.get("wt_fin_yield", 20), 5,
                help="Banks and insurers return capital via dividends — this is a more "
                     "important signal for financials than for industrials.",
            )
            new_fin_52w = st.slider(
                "52-week position importance",
                0, 100, p.get("wt_fin_52w", 15), 5,
                help="Contrarian signal — financials near 52w lows may be oversold "
                     "due to macro fears rather than fundamental deterioration.",
            )

        fvals  = [new_fin_ptb, new_fin_roe, new_fin_yield, new_fin_52w]
        flabls = ["P/TangBook", "ROE", "Yield", "52w"]
        _weight_bar(fvals, flabls)
        total_f = sum(fvals)
        if total_f == 0:
            st.warning("⚠ All weights are zero — financial stocks cannot be scored.")
        else:
            pcts = "  ·  ".join(
                f"**{l}** {v/total_f*100:.0f}%" for l, v in zip(flabls, fvals) if v > 0
            )
            st.caption(f"Effective split: {pcts}")

        if (new_fin_ptb != p.get("wt_fin_ptb") or new_fin_roe != p.get("wt_fin_roe")
                or new_fin_yield != p.get("wt_fin_yield") or new_fin_52w != p.get("wt_fin_52w")):
            p["wt_fin_ptb"]   = new_fin_ptb
            p["wt_fin_roe"]   = new_fin_roe
            p["wt_fin_yield"] = new_fin_yield
            p["wt_fin_52w"]   = new_fin_52w
            changed = True'''

if OLD_SETTINGS_STOCK in src:
    src = src.replace(OLD_SETTINGS_STOCK, NEW_SETTINGS_STOCK)
    print("✓ Patch 2 applied: Settings page stock valuation section updated")
else:
    print("⚠ Patch 2 SKIPPED — settings stock block not found (already patched?)")


# ────────────────────────────────────────────────────────────────────────────
# PATCH 3: Quality gate — add financial-specific settings
# ────────────────────────────────────────────────────────────────────────────

OLD_QUALITY = '''        st.caption(
            f"Current gate: ROE ≥ {new_roe}%  ·  D/E ≤ {new_de}x  ·  "
            f"Margin ≥ {new_pm}%  ·  FCF {'positive required' if new_fcf else 'not required'}"
        )'''

NEW_QUALITY = '''        st.caption(
            f"Non-financials: ROE ≥ {new_roe}%  ·  D/E ≤ {new_de}x  ·  "
            f"Margin ≥ {new_pm}%  ·  FCF {'required' if new_fcf else 'not required'}"
        )
        st.markdown("---")
        st.caption(
            "**Financial stocks** (banks, insurers, asset managers) use a separate quality gate: "
            "ROE ≥ 6%  ·  Price/Book ≤ 2.0x  ·  D/E gate removed (leverage is structural). "
            "These thresholds are fixed — adjust via the Financial weights section above."
        )'''

if OLD_QUALITY in src:
    src = src.replace(OLD_QUALITY, NEW_QUALITY)
    print("✓ Patch 3 applied: quality gate caption updated")
else:
    print("⚠ Patch 3 SKIPPED — caption not found (already patched?)")


# ────────────────────────────────────────────────────────────────────────────
# Write output
# ────────────────────────────────────────────────────────────────────────────

if src == original:
    print("\n⚠ No changes made — all patches skipped.")
else:
    APP.write_text(src, encoding="utf-8")
    print(f"\n✅ app.py updated ({APP.stat().st_size:,} bytes)")
    print("Next: commit in GitHub Desktop and Streamlit will redeploy automatically.")
