#!/usr/bin/env python3
"""
apply_holdings_card_patch.py
Patches the Holdings (watchlist) full page to:
  1. Show entry score + drift on each card header
  2. Show entry date
  3. Add a manual entry score edit field per holding
  4. Make the per-ticker refresh use fetch_prices_only (fast) by default

Run from inside the "Value Screener v3" folder:
    python3 apply_holdings_card_patch.py
"""

import sys
from pathlib import Path

ROOT = Path(".")
if not (ROOT / "app.py").exists():
    sys.exit("ERROR: run this from inside the 'Value Screener v3' folder")

src  = (ROOT / "app.py").read_text(encoding="utf-8")
orig = src

# ── Patch 1: Holdings page — annotate wl_insts with entry score before rendering ──

OLD_WL_FULL = '''    wl = st.session_state.watchlist
    if not wl:
        st.info("No holdings yet. Use the search above to add instruments.")
        return

    ok_map = {x["ticker"]: x for x in st.session_state.instruments if x.get("ok")}'''

NEW_WL_FULL = '''    wl = st.session_state.watchlist
    if not wl:
        st.info("No holdings yet. Use the search above to add instruments.")
        return

    ok_map  = {x["ticker"]: x for x in st.session_state.instruments if x.get("ok")}
    wl_meta = {w["ticker"]: w for w in wl}   # entry_score, entry_date etc.

    # Annotate ok_map instruments with entry score data from watchlist metadata
    for ticker, inst in ok_map.items():
        meta = wl_meta.get(ticker, {})
        entry_score = None
        try:
            v = meta.get("entry_score")
            entry_score = float(v) if v is not None else None
        except (TypeError, ValueError):
            pass
        current_score = inst.get("score")
        inst["entry_score"]  = entry_score
        inst["entry_date"]   = meta.get("entry_date", "")
        if entry_score is not None and current_score is not None:
            try:
                inst["score_drift_from_entry"] = float(current_score) - float(entry_score)
            except (TypeError, ValueError):
                pass'''

if OLD_WL_FULL in src:
    src = src.replace(OLD_WL_FULL, NEW_WL_FULL)
    print("✓ Patch 1: Holdings full page annotates entry score on instruments")
else:
    print("⚠ Patch 1 SKIPPED: watchlist full page block not found (already patched?)")

# ── Patch 2: Render entry score + drift in the card expander header ────────────

OLD_WL_EXPANDER = '''        with st.expander(f"{ticker}  ·  {name}", expanded=False):'''

NEW_WL_EXPANDER = '''        _entry_s = inst.get("entry_score")
        _curr_s  = inst.get("score")
        _drift   = inst.get("score_drift_from_entry")
        _edate   = inst.get("entry_date", "")
        if _entry_s is not None and _drift is not None:
            _drift_str = (f" ▲ +{_drift:.0f}" if _drift > 0 else f" ▼ {_drift:.0f}") if abs(_drift) >= 1 else " ─"
            _exp_label = f"{ticker}  ·  {name}  ·  Entry {_entry_s:.0f}{_drift_str} → {_curr_s:.0f}" if _curr_s else f"{ticker}  ·  {name}"
        else:
            _exp_label = f"{ticker}  ·  {name}"
        with st.expander(_exp_label, expanded=False):'''

if OLD_WL_EXPANDER in src:
    src = src.replace(OLD_WL_EXPANDER, NEW_WL_EXPANDER, 1)
    print("✓ Patch 2: Holdings card expander shows entry→current score drift")
else:
    print("⚠ Patch 2 SKIPPED: expander label not found (already patched?)")

# ── Patch 3: Add manual entry score edit below each holding card ───────────────

OLD_REFRESH_BTN = '''            if st.button(f"🔄 Refresh", key=f"refresh_{ticker}",
                         use_container_width=True):
                _refresh_single_ticker(wl_entry)
                st.rerun()'''

NEW_REFRESH_BTN = '''            if st.button(f"🔄 Refresh", key=f"refresh_{ticker}",
                         use_container_width=True):
                _refresh_single_ticker(wl_entry)
                st.rerun()

            # Manual entry score override
            _stored_entry = wl_entry.get("entry_score")
            _edit_key     = f"entry_score_edit_{ticker}"
            _new_entry = st.number_input(
                "Entry score",
                min_value=0.0, max_value=100.0,
                value=float(_stored_entry) if _stored_entry is not None else (inst.get("score") or 50.0),
                step=1.0,
                key=_edit_key,
                help="Score when you bought this. Edit to match your actual purchase timing.",
                label_visibility="visible",
            )
            if abs((_new_entry or 0) - (_stored_entry or -999)) > 0.4:
                # User changed it — save immediately
                for w in st.session_state.watchlist:
                    if w["ticker"] == ticker:
                        w["entry_score"] = _new_entry
                        if not w.get("entry_date"):
                            from datetime import datetime as _dt
                            w["entry_date"] = _dt.now().strftime("%Y-%m-%d")
                        break
                _save_json("watchlist.json", st.session_state.watchlist)'''

if OLD_REFRESH_BTN in src:
    src = src.replace(OLD_REFRESH_BTN, NEW_REFRESH_BTN, 1)
    print("✓ Patch 3: Manual entry score edit added to each holdings card")
else:
    print("⚠ Patch 3 SKIPPED: refresh button block not found (already patched?)")

# ── Write ─────────────────────────────────────────────────────────────────────
if src != orig:
    (ROOT / "app.py").write_text(src, encoding="utf-8")
    print(f"\n✅ app.py updated ({(ROOT/'app.py').stat().st_size:,} bytes)")
else:
    print("\n⚠ app.py unchanged — all patches skipped.")

print("\nDone. Commit in GitHub Desktop and push to deploy.")
