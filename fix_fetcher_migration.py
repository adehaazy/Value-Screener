#!/usr/bin/env python3
"""
fix_fetcher_migration.py
Wraps the one-time JSON→SQLite migration block in fetcher.py with a
try/except so missing legacy cache files (e.g. PXD.json) don't crash
the app on startup.

Run from inside the "Value Screener v3" folder:
    python3 fix_fetcher_migration.py
"""

import sys
from pathlib import Path

ROOT = Path(".")
fetcher_path = ROOT / "data" / "fetcher.py"

if not fetcher_path.exists():
    sys.exit("ERROR: data/fetcher.py not found — run from inside Value Screener v3 folder")

src = fetcher_path.read_text(encoding="utf-8")
original = src

OLD = """if not _migrated_flag.exists() and not _db.any_data_exists():
    _n = _db.migrate_from_json(
        instruments_dir=_BASE / "instruments",
        fundamentals_dir=_BASE / "fundamentals",
        prices_dir=_BASE / "prices",
    )
    if _n > 0:
        _migrated_flag.touch()"""

NEW = """if not _migrated_flag.exists() and not _db.any_data_exists():
    try:
        _n = _db.migrate_from_json(
            instruments_dir=_BASE / "instruments",
            fundamentals_dir=_BASE / "fundamentals",
            prices_dir=_BASE / "prices",
        )
        if _n > 0:
            _migrated_flag.touch()
    except (FileNotFoundError, OSError):
        # Legacy JSON cache files missing — skip migration cleanly
        _migrated_flag.touch()  # mark as done so we don't retry"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    fetcher_path.write_text(src, encoding="utf-8")
    print("✅ data/fetcher.py patched — migration wrapped in try/except")
elif "except (FileNotFoundError, OSError)" in src:
    print("⚠ Already patched — nothing to do")
else:
    print("⚠ Pattern not found — the migration block may look different in your version.")
    print("  Manually wrap the _db.migrate_from_json(...) call in try/except FileNotFoundError.")

print("\nDone. Commit and push in GitHub Desktop.")
