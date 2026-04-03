#!/usr/bin/env python3
"""
fix_universe.py
Removes confirmed dead/delisted/acquired tickers from data/universe.py
and corrects two known wrong ticker symbols.

Dead tickers identified from Streamlit Cloud logs (HTTP 404 / no price data):

  UK:
    COB.L    — Cobham (taken private by Advent, 2020)
    HL.L     — Hargreaves Lansdown (taken private by CVC/Abu Dhabi, 2024)
    SMDS.L   — DS Smith (acquired by International Paper, 2024 → delist)

  EU:
    SIVB.DE  — wrong ticker for Siemens Energy (correct is ENR.DE)
    ZIG.DE   — Delivery Hero delisted from XETRA / rebranded DHER.DE
    AXA.PA   — wrong ticker (correct is CS.PA; but CS.PA is AXA duplicate — remove both, keep AXA.PA)
    STM.PA   — STMicro trades as STM.PA but Yahoo uses STMPA.PA; replace
    URW.AS   — Unibail-Rodamco delisted from AEX; now URW.NA — replace
    CEL.MC   — Cellnex: Yahoo Finance ticker is CLNX.MC — replace
    ATL.MI   — Atlantia delisted (taken private 2022); remove
    SMEA.PA  — iShares MSCI Europe Small Cap: Yahoo uses SMEA.AS — replace
    ERNX.L   — Invesco GBP Corp Bond 0-3yr: delisted/merged — remove

  US (acquired/merged out of S&P 500):
    JNPR     — Juniper Networks (acquired by HPE, 2024)
    ANSS     — ANSYS (acquired by Synopsys, 2024)
    PARA     — Paramount Global (merged into Skydance, 2024)
    IPG      — Interpublic (acquired by Omnicom, 2024)
    K        — Kellanova (acquired by Mars, 2024)
    ABC      — AmerisourceBergen (rebranded → Cencora, ticker AMEX:COR — replace)
    PKI      — PerkinElmer (renamed → Revvity, ticker RVTY — replace)
    MMC      — Marsh & McLennan: ticker is actually valid but 404ing — keep, flag only
    PXD      — Pioneer Natural Resources (acquired by ExxonMobil, 2024)
    HES      — Hess Corp (acquired by Chevron, 2024)
    MRO      — Marathon Oil (acquired by ConocoPhillips, 2024)
    SPR      — Spirit AeroSystems (acquired by Boeing, 2024)

Run from inside the "Value Screener v3" folder:
    python3 fix_universe.py
"""

import sys, re
from pathlib import Path

ROOT = Path(".")
universe_path = ROOT / "data" / "universe.py"

if not universe_path.exists():
    sys.exit("ERROR: data/universe.py not found — run from inside Value Screener v3 folder")

src = universe_path.read_text(encoding="utf-8")
original = src

changes = []

def remove_ticker(ticker, reason):
    """Remove a ticker line like '    "TICK":  "Name",' from the file."""
    global src
    # Match the line with this exact ticker key, with any spacing/comma
    pattern = rf'[ \t]+"{re.escape(ticker)}"[ \t]*:[ \t]*"[^"]*",?\n'
    new, count = re.subn(pattern, "", src)
    if count:
        src = new
        changes.append(f"  REMOVED  {ticker:12s} — {reason}")
    else:
        changes.append(f"  SKIPPED  {ticker:12s} — not found (may already be removed)")

def replace_ticker(old_ticker, new_ticker, new_name, reason):
    """Replace a ticker key (and optionally name) in-place."""
    global src
    pattern = rf'([ \t]+)"{re.escape(old_ticker)}"([ \t]*:[ \t]*)"[^"]*"(,?)'
    replacement = rf'\g<1>"{new_ticker}"\g<2>"{new_name}"\g<3>'
    new, count = re.subn(pattern, replacement, src)
    if count:
        src = new
        changes.append(f"  REPLACED {old_ticker:12s} → {new_ticker:12s} ({new_name}) — {reason}")
    else:
        changes.append(f"  SKIPPED  {old_ticker:12s} → {new_ticker} — not found")

# ── UK removals ───────────────────────────────────────────────────────────────
remove_ticker("COB.L",   "Cobham taken private 2020")
remove_ticker("HL.L",    "Hargreaves Lansdown taken private 2024")
remove_ticker("SMDS.L",  "DS Smith acquired by International Paper 2024")

# ── EU fixes ─────────────────────────────────────────────────────────────────
replace_ticker("SIVB.DE", "ENR.DE",    "Siemens Energy",         "SIVB.DE was wrong ticker — correct is ENR.DE")
replace_ticker("ZIG.DE",  "DHER.DE",   "Delivery Hero",          "ZIG.DE delisted; rebranded DHER.DE on XETRA")
remove_ticker("CS.PA",    "Duplicate of AXA.PA — both map to AXA")
replace_ticker("STM.PA",  "STMPA.PA",  "STMicroelectronics",     "Yahoo Finance uses STMPA.PA for STM")
replace_ticker("URW.AS",  "URW.NA",    "Unibail-Rodamco-Westfield","Delisted from AEX; use URW.NA (Euronext)")
replace_ticker("CEL.MC",  "CLNX.MC",   "Cellnex Telecom",        "Yahoo Finance ticker is CLNX.MC")
remove_ticker("ATL.MI",   "Atlantia taken private 2022")
replace_ticker("SMEA.PA", "SMEA.AS",   "iShares MSCI Europe Small Cap", "Yahoo Finance uses SMEA.AS not SMEA.PA")
remove_ticker("ERNX.L",   "Invesco GBP Corp Bond 0-3yr — delisted/merged")

# ── US removals & replacements ────────────────────────────────────────────────
remove_ticker("JNPR",  "Juniper Networks acquired by HPE, 2024")
remove_ticker("ANSS",  "ANSYS acquired by Synopsys, 2024")
remove_ticker("PARA",  "Paramount Global merged into Skydance, 2024")
remove_ticker("IPG",   "Interpublic acquired by Omnicom, 2024")
remove_ticker("K",     "Kellanova acquired by Mars, 2024")
replace_ticker("ABC",  "COR",   "Cencora",                 "AmerisourceBergen rebranded → Cencora (COR)")
replace_ticker("PKI",  "RVTY",  "Revvity",                 "PerkinElmer renamed → Revvity (RVTY)")
remove_ticker("PXD",   "Pioneer Natural Resources acquired by ExxonMobil, 2024")
remove_ticker("HES",   "Hess Corp acquired by Chevron, 2024")
remove_ticker("MRO",   "Marathon Oil acquired by ConocoPhillips, 2024")
remove_ticker("SPR",   "Spirit AeroSystems acquired by Boeing, 2024")

# ── Write file ────────────────────────────────────────────────────────────────
if src != original:
    universe_path.write_text(src, encoding="utf-8")
    print(f"✅ data/universe.py updated")
    print(f"\nChanges ({len([c for c in changes if 'REMOVED' in c or 'REPLACED' in c])} applied):")
    for c in changes:
        print(c)
else:
    print("⚠ No changes made — all tickers already removed or patterns not matched.")
    for c in changes:
        print(c)

print("\nDone. Commit and push in GitHub Desktop.")
