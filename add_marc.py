"""
One-shot script: add Marc.D to the database.
Run from the backend folder:
    python add_marc.py
Then delete this file.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Ensure JWT secret is set (needed by auth_utils import chain)
if not os.environ.get("JWT_SECRET_KEY"):
    os.environ["JWT_SECRET_KEY"] = "dev-secret-change-in-production"

from database import init_db, fetch_one, execute_write
from auth_utils import hash_password
from auth_api import init_auth_db
import uuid
from datetime import datetime, timezone

init_db()
init_auth_db()

username = "marc.d"
existing = fetch_one("SELECT user_id FROM users WHERE username = ?", (username,))
if existing:
    print(f"User '{username}' already exists — nothing to do.")
    sys.exit(0)

user_id = str(uuid.uuid4())
pw_hash = hash_password("Sophie25")
now = datetime.now(timezone.utc).isoformat()

execute_write(
    """INSERT INTO users
           (user_id, email, email_verified, password_hash,
            created_at, updated_at, login_attempts,
            must_change_password, anonymized_id,
            username, display_name, first_name, role)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (
        user_id,
        f"{username}@bens-shed.app",
        True,
        pw_hash,
        now, now,
        0,
        True,
        str(uuid.uuid4()),
        username, "Marc D", "Marc", "user",
    ),
)

print(f"User '{username}' created successfully.")
print(f"  Display name: Marc D")
print(f"  Passcode:     Sophie25")
print(f"  Role:         user")
print(f"  Must change:  yes (on first login)")
