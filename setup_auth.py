"""
setup_auth.py — One-shot script to reset and rebuild the auth database.

Deletes the old auth.db, creates a fresh one with the correct schema,
seeds all users, and verifies everything works.

Run from the backend folder:
    cd "/Users/ade-macmini/Library/Mobile Documents/com~apple~CloudDocs/Documents/Value Screener v3"
    python setup_auth.py

Delete this file after running.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Ensure JWT secret
if not os.environ.get("JWT_SECRET_KEY"):
    os.environ["JWT_SECRET_KEY"] = "dev-secret-change-in-production"

from pathlib import Path

DB_PATH = Path(__file__).parent / "auth.db"

# Step 1: Delete old database
if DB_PATH.exists():
    DB_PATH.unlink()
    # Also remove WAL/SHM files if present
    for suffix in ["-wal", "-shm"]:
        p = DB_PATH.with_name(DB_PATH.name + suffix)
        if p.exists():
            p.unlink()
    print("[1/4] Deleted old auth.db")
else:
    print("[1/4] No existing auth.db found (clean start)")

# Step 2: Initialise fresh database
from database import init_db
init_db()
print("[2/4] Database schema created")

# Step 3: Add auth columns + seed users
from auth_api import init_auth_db, seed_sample_users
init_auth_db()
seed_sample_users()
print("[3/4] Auth columns added and users seeded")

# Step 4: Verify
from database import fetch_all
from auth_utils import verify_password

print("[4/4] Verifying users:\n")

test_creds = [
    ("ade.h",       "maple42"),
    ("marc.d",      "Sophie25"),
    ("elan.d",      "Kestrel47"),
]

rows = fetch_all("SELECT username, display_name, role, must_change_password FROM users ORDER BY created_at")
for row in rows:
    u = dict(row)
    username = u["username"]
    # Find matching test creds
    expected_passcode = next((p for un, p in test_creds if un == username), None)
    if expected_passcode:
        from database import fetch_one
        full = dict(fetch_one("SELECT password_hash FROM users WHERE username = ?", (username,)))
        ok = verify_password(expected_passcode, full["password_hash"])
        status = "PASS" if ok else "FAIL"
    else:
        status = "SKIP (no test creds)"

    print(f"  {username:<15} {u['display_name']:<20} role={u['role']:<8} passcode={status}")

print("\nDone. You can now start the backend with:")
print('  uvicorn main:app --reload --port 8000')
