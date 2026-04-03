#!/usr/bin/env python3
"""
apply_fetcher_patch.py
Patches data/fetcher.py to capture free_cashflow, price_to_book, and
pre-computed p_fcf — fields needed by the new deep value scoring model.

    cd ~/Documents/Value\ Screener\ v3
    python3 apply_fetcher_patch.py
"""

import sys
from pathlib import Path

FETCHER = Path("data/fetcher.py")
if not FETCHER.exists():
    sys.exit("ERROR: run this from inside the 'Value Screener v3' folder")

src = FETCHER.read_text(encoding="utf-8")
original = src

# ────────────────────────────────────────────────────────────────────────────
# We need to find where the result dict is built for stocks and add
# free_cashflow, price_to_book, and p_fcf.
#
# The fetcher builds a result dict from yfinance's info object.
# We look for the block that pulls "sector" and nearby fields,
# then add our new fields right after.
# ────────────────────────────────────────────────────────────────────────────

# Strategy: find the line that extracts "sector" from info and add fields nearby.
# This is robust regardless of exact line numbers.

SECTOR_PATTERNS = [
    # Pattern A — direct dict key access
    '"sector":  info.get("sector",',
    '"sector": info.get("sector",',
    # Pattern B — variable assignment
    'sector    = info.get("sector"',
    'sector = info.get("sector"',
]

found_pattern = None
for pat in SECTOR_PATTERNS:
    if pat in src:
        found_pattern = pat
        break

if not found_pattern:
    # Try to find any info.get block we can hook into
    if 'info.get("regularMarketPrice")' in src or 'info.get("trailingPE")' in src:
        print("⚠ Could not find sector extraction pattern.")
        print("  Please manually add these fields to the result dict in data/fetcher.py:")
        print()
        print('  "free_cashflow":  info.get("freeCashflow"),')
        print('  "price_to_book":  info.get("priceToBook"),')
        print('  # p_fcf: price / free cash flow (pre-computed)')
        print('  "p_fcf": (')
        print('      (info.get("marketCap") / info.get("freeCashflow"))')
        print('      if info.get("marketCap") and info.get("freeCashflow")')
        print('         and info.get("freeCashflow") > 0')
        print('      else None')
        print('  ),')
        sys.exit(0)

# ── Patch: inject fields after the sector line ────────────────────────────────

# Find a good insertion anchor — the line after "sector" in the result dict
# We look for common patterns of what follows sector in the result dict

ANCHORS_TO_PATCH = [
    # If sector is in a dict literal, add our fields right after it
    (
        '"sector":  info.get("sector", ""),',
        '"sector":  info.get("sector", ""),\n'
        '                "free_cashflow":  info.get("freeCashflow"),\n'
        '                "price_to_book":  info.get("priceToBook"),\n'
        '                "p_fcf": (\n'
        '                    (info.get("marketCap") / info.get("freeCashflow"))\n'
        '                    if info.get("marketCap") and info.get("freeCashflow")\n'
        '                       and info.get("freeCashflow") > 0\n'
        '                    else None\n'
        '                ),',
    ),
    (
        '"sector": info.get("sector", ""),',
        '"sector": info.get("sector", ""),\n'
        '                "free_cashflow":  info.get("freeCashflow"),\n'
        '                "price_to_book":  info.get("priceToBook"),\n'
        '                "p_fcf": (\n'
        '                    (info.get("marketCap") / info.get("freeCashflow"))\n'
        '                    if info.get("marketCap") and info.get("freeCashflow")\n'
        '                       and info.get("freeCashflow") > 0\n'
        '                    else None\n'
        '                ),',
    ),
    (
        '"sector":  info.get("sector"),',
        '"sector":  info.get("sector"),\n'
        '                "free_cashflow":  info.get("freeCashflow"),\n'
        '                "price_to_book":  info.get("priceToBook"),\n'
        '                "p_fcf": (\n'
        '                    (info.get("marketCap") / info.get("freeCashflow"))\n'
        '                    if info.get("marketCap") and info.get("freeCashflow")\n'
        '                       and info.get("freeCashflow") > 0\n'
        '                    else None\n'
        '                ),',
    ),
]

patched = False
for old, new in ANCHORS_TO_PATCH:
    if old in src and new.split('\n')[0] not in src:  # don't double-patch
        src = src.replace(old, new, 1)
        patched = True
        print("✓ Fetcher patch applied: free_cashflow, price_to_book, p_fcf added")
        break

if not patched:
    # Check if already patched
    if "free_cashflow" in src and "price_to_book" in src and "p_fcf" in src:
        print("✓ Fetcher already contains free_cashflow / price_to_book / p_fcf — no changes needed")
    else:
        print("⚠ Could not auto-patch fetcher. Please manually add these three fields")
        print("  to the stock result dict in data/fetcher.py (near where 'sector' is extracted):")
        print()
        print('    "free_cashflow":  info.get("freeCashflow"),')
        print('    "price_to_book":  info.get("priceToBook"),')
        print('    "p_fcf": (')
        print('        (info.get("marketCap") / info.get("freeCashflow"))')
        print('        if info.get("marketCap") and info.get("freeCashflow")')
        print('           and info.get("freeCashflow") > 0')
        print('        else None')
        print('    ),')

if src != original:
    FETCHER.write_text(src, encoding="utf-8")
    print(f"\n✅ data/fetcher.py updated ({FETCHER.stat().st_size:,} bytes)")
else:
    print("\nNo changes written.")
