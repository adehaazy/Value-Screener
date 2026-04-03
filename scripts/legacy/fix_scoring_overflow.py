#!/usr/bin/env python3
"""
fix_scoring_overflow.py
Fixes OverflowError in utils/scoring.py — clamps the exponent passed to
math.exp() so extremely cheap/expensive stocks don't blow up the logistic curve.

Run from inside the "Value Screener v3" folder:
    python3 fix_scoring_overflow.py
"""

import sys
from pathlib import Path

ROOT = Path(".")
scoring_path = ROOT / "utils" / "scoring.py"

if not scoring_path.exists():
    sys.exit("ERROR: utils/scoring.py not found — run from inside Value Screener v3 folder")

src = scoring_path.read_text(encoding="utf-8")

OLD = """    if lower_is_better:
        # ratio < 1 → cheaper than median → score > 50
        # Use logistic-style transform: score = 100 / (1 + exp(k*(ratio-1)))
        k = 3.0 * sensitivity
        score = 100.0 / (1.0 + math.exp(k * (ratio - 1.0)))
    else:
        # Higher is better (e.g. ROE)
        k = 3.0 * sensitivity
        score = 100.0 / (1.0 + math.exp(-k * (ratio - 1.0)))"""

NEW = """    _EXP_CLAMP = 500.0  # math.exp(709) overflows; clamp well below that

    if lower_is_better:
        # ratio < 1 → cheaper than median → score > 50
        k = 3.0 * sensitivity
        exponent = min(k * (ratio - 1.0), _EXP_CLAMP)
        score = 100.0 / (1.0 + math.exp(exponent))
    else:
        # Higher is better (e.g. ROE)
        k = 3.0 * sensitivity
        exponent = max(-k * (ratio - 1.0), -_EXP_CLAMP)
        score = 100.0 / (1.0 + math.exp(exponent))"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    scoring_path.write_text(src, encoding="utf-8")
    print("✅ utils/scoring.py patched — overflow fix applied")
elif "_EXP_CLAMP" in src:
    print("⚠ Already patched — nothing to do")
else:
    print("⚠ Pattern not found. The file may have been manually edited.")
    print("  Manually replace the math.exp lines in _score_vs_median() with:")
    print()
    print(NEW)
