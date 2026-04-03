#!/usr/bin/env python3
"""
fix_container_width.py
Replaces deprecated Streamlit `use_container_width` parameter usage
with the new `width` parameter (Streamlit >= 1.42 / Cloud as of Dec 2025).

  use_container_width=True   →  width='stretch'
  use_container_width=False  →  width='content'

Applies to: app.py (and optionally any other .py files in the repo).

Run from inside the "Value Screener v3" folder:
    python3 fix_container_width.py
"""

import sys, re
from pathlib import Path

ROOT = Path(".")

if not (ROOT / "app.py").exists():
    sys.exit("ERROR: app.py not found — run from inside Value Screener v3 folder")

def fix_file(path: Path) -> int:
    src = path.read_text(encoding="utf-8")
    original = src

    # use_container_width=True  →  width='stretch'
    src = re.sub(r'\buse_container_width\s*=\s*True\b', "width='stretch'", src)

    # use_container_width=False  →  width='content'
    src = re.sub(r'\buse_container_width\s*=\s*False\b', "width='content'", src)

    if src != original:
        path.write_text(src, encoding="utf-8")
        count = len(re.findall(r"width='stretch'|width='content'", src))
        print(f"  ✅ {path} — {count} replacements made")
        return count
    else:
        print(f"  ⚠ {path} — no use_container_width found (already fixed?)")
        return 0

total = 0
for py_file in ROOT.rglob("*.py"):
    # Skip venv, cache, hidden dirs
    if any(part.startswith(".") or part in {"venv", "__pycache__", "cache"}
           for part in py_file.parts):
        continue
    src = py_file.read_text(encoding="utf-8", errors="ignore")
    if "use_container_width" in src:
        total += fix_file(py_file)

if total:
    print(f"\n✅ Done — {total} total replacements across all files.")
    print("Commit and push in GitHub Desktop.")
else:
    print("\n⚠ No use_container_width found anywhere — nothing to fix.")
