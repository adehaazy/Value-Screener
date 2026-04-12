"""
auth_api.py — FastAPI authentication endpoints for Ben's Shed.

Username/passcode login, session management, JWT tokens.
Integrates with existing database.py, auth_utils.py, security.py, audit.py.
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel, Field

from auth_utils import (
    hash_password,
    verify_password,
    create_jwt,
    validate_session as _validate_session,
    hash_token,
)
from database import fetch_one, execute_write, get_db, init_db
from security import sanitize_input, check_rate_limit, increment_rate_limit
from audit import log_audit_event

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@bens-shed.app")

# Lockout constants (from spec)
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
CONSECUTIVE_LOCKOUT_THRESHOLD = 3
EXTENDED_LOCKOUT_MINUTES = 60

# Session expiry
DEFAULT_SESSION_HOURS = 7 * 24       # 7 days
EXTENDED_SESSION_HOURS = 30 * 24     # 30 days

MIN_PASSCODE_LENGTH = 6

# ─── Router ───────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ─── Pydantic models ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    passcode: str = Field(..., min_length=1)
    stay_in: bool = True


class ChangePasscodeRequest(BaseModel):
    current_passcode: str = Field(..., min_length=1)
    new_passcode: str = Field(..., min_length=1)


# ─── Database setup ──────────────────────────────────────────────────────────

def init_auth_db():
    """Add username/display_name/first_name/role columns to the users table."""
    # NOTE: SQLite ALTER TABLE ADD COLUMN does NOT support inline UNIQUE.
    # Add the column plain, then create a unique index separately.
    alter_statements = [
        "ALTER TABLE users ADD COLUMN username TEXT",
        "ALTER TABLE users ADD COLUMN display_name TEXT",
        "ALTER TABLE users ADD COLUMN first_name TEXT",
        "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'",
    ]
    with get_db() as conn:
        for sql in alter_statements:
            try:
                conn.execute(sql)
            except Exception:
                pass  # column already exists
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username)"
            )
        except Exception:
            pass
    logger.info("Auth DB columns ensured.")


def seed_sample_users():
    """Insert sample users from the spec (skip if they already exist)."""
    sample_users = [
        ("Ade H",         "ade.h",       "maple42",  "admin"),
        ("Marc D",        "marc.d",      "Sophie25", "user"),
        ("Elan D",        "elan.d",      "Kestrel47", "user"),
    ]
    for display_name, username, passcode, role in sample_users:
        existing = fetch_one(
            "SELECT user_id FROM users WHERE username = ?", (username,)
        )
        if existing:
            continue

        user_id = str(uuid.uuid4())
        first_name = display_name.split()[0]
        pw_hash = hash_password(passcode)
        now = datetime.now(timezone.utc).isoformat()

        try:
            execute_write(
                """INSERT INTO users
                       (user_id, email, email_verified, password_hash,
                        created_at, updated_at, login_attempts,
                        must_change_password, anonymized_id,
                        username, display_name, first_name, role)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    f"{username}@bens-shed.app",  # placeholder email
                    True,
                    pw_hash,
                    now, now,
                    0,
                    True,   # must change on first login
                    str(uuid.uuid4()),
                    username, display_name, first_name, role,
                ),
            )
            logger.info("Seeded user: %s (%s)", username, role)
        except Exception as e:
            logger.warning("Could not seed user %s: %s", username, e)


# ─── Auth dependency ─────────────────────────────────────────────────────────

def _extract_token(authorization: Optional[str] = Header(None)) -> str:
    """Pull the raw JWT string from the Authorization header."""
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid authorization header")
    return parts[1]


async def get_current_user(token: str = Depends(_extract_token)):
    """Validate session and return the user row as a dict."""
    payload = _validate_session(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")

    user_row = fetch_one("SELECT * FROM users WHERE user_id = ?", (payload["user_id"],))
    if not user_row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return dict(user_row)


# ─── Helper: user dict → frontend shape ──────────────────────────────────────

def _user_payload(u: dict) -> dict:
    """Standard user fields returned to the frontend."""
    display = u.get("display_name") or ""
    return {
        "user_id":     u["user_id"],
        "username":    u.get("username") or "",
        "display_name": display,
        "first_name":  display.split()[0] if display else "",
        "role":        u.get("role") or "user",
        "must_change_passcode": bool(u.get("must_change_password")),
    }


# ─── POST /api/auth/login ────────────────────────────────────────────────────

@router.post("/login")
async def login_endpoint(body: LoginRequest, request: Request):
    username = sanitize_input(body.username).lower().strip()
    ip = request.client.host if request.client else ""

    # Rate-limit (raises PermissionError if exceeded)
    try:
        check_rate_limit(username, ip)
    except PermissionError as exc:
        log_audit_event(None, "rate_limit_hit", ip, False, {"username": username})
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc))

    # Lookup
    row = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    user = dict(row) if row else None
    generic = "That's not right. Check your username and passcode."

    if not user:
        increment_rate_limit(username)
        log_audit_event(None, "login_fail", ip, False, {"username": username, "reason": "not_found"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, generic)

    uid = user["user_id"]

    # Check lockout
    if user.get("locked_until"):
        locked_dt = datetime.fromisoformat(user["locked_until"])
        if locked_dt.tzinfo is None:
            locked_dt = locked_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now < locked_dt:
            remaining = max(1, int((locked_dt - now).total_seconds() / 60))
            if remaining > LOCKOUT_MINUTES:
                msg = "Too many tries. Come back in 1 hour."
            else:
                msg = f"Too many tries. Come back in {remaining} minutes."
            log_audit_event(uid, "login_locked", ip, False, {"username": username})
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, msg)
        else:
            # Lock expired — reset
            execute_write(
                "UPDATE users SET login_attempts = 0, locked_until = NULL WHERE user_id = ?",
                (uid,),
            )
            user["login_attempts"] = 0
            user["locked_until"] = None

    # Verify passcode
    if not verify_password(body.passcode, user["password_hash"]):
        attempts = (user.get("login_attempts") or 0) + 1
        locked_until_val = None

        if attempts >= MAX_LOGIN_ATTEMPTS:
            # Determine lockout duration.
            # Simple heuristic: if they were locked before recently, escalate.
            lockout_mins = LOCKOUT_MINUTES
            # Check how many times they've been locked in the last 2 hours
            # by looking at audit logs for this user.
            from database import fetch_all as _fa
            recent_locks = _fa(
                """SELECT COUNT(*) as cnt FROM audit_logs
                   WHERE user_id = ? AND event_type = 'login_locked'
                   AND event_timestamp > datetime('now', '-2 hours')""",
                (uid,),
            )
            lock_count = dict(recent_locks[0])["cnt"] if recent_locks else 0
            if lock_count >= CONSECUTIVE_LOCKOUT_THRESHOLD - 1:
                lockout_mins = EXTENDED_LOCKOUT_MINUTES

            locked_until_val = (datetime.now(timezone.utc) + timedelta(minutes=lockout_mins)).isoformat()

        execute_write(
            "UPDATE users SET login_attempts = ?, locked_until = ?, updated_at = ? WHERE user_id = ?",
            (attempts, locked_until_val, datetime.now(timezone.utc).isoformat(), uid),
        )
        increment_rate_limit(username)
        log_audit_event(uid, "login_fail", ip, False, {"username": username, "attempt": attempts})

        if locked_until_val:
            if lockout_mins > LOCKOUT_MINUTES:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Too many tries. Come back in 1 hour.")
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                f"Too many tries. Come back in {lockout_mins} minutes.",
            )

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, generic)

    # ── Success ───────────────────────────────────────────────────────────
    execute_write(
        "UPDATE users SET login_attempts = 0, locked_until = NULL, last_login = ?, updated_at = ? WHERE user_id = ?",
        (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), uid),
    )

    expiry_hours = EXTENDED_SESSION_HOURS if body.stay_in else DEFAULT_SESSION_HOURS
    # create_jwt(user_id, email, expiry_hours) — use email field (it exists)
    jwt_token = create_jwt(uid, user.get("email") or username, expiry_hours)

    # Record session
    session_id = str(uuid.uuid4())
    token_h = hash_token(jwt_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expiry_hours)).isoformat()
    execute_write(
        """INSERT INTO sessions (session_id, user_id, token_hash, expires_at, last_activity, ip_address)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
        (session_id, uid, token_h, expires_at, ip),
    )

    log_audit_event(uid, "login", ip, True, {"username": username})
    logger.info("Login success: %s", username)

    return {
        "success": True,
        "jwt_token": jwt_token,
        **_user_payload(user),
    }


# ─── POST /api/auth/logout ──────────────────────────────────────────────────

@router.post("/logout")
async def logout_endpoint(
    token: str = Depends(_extract_token),
    user: dict = Depends(get_current_user),
):
    token_h = hash_token(token)
    execute_write(
        "DELETE FROM sessions WHERE user_id = ? AND token_hash = ?",
        (user["user_id"], token_h),
    )
    log_audit_event(user["user_id"], "logout", "", True, {"username": user.get("username")})
    return {"success": True}


# ─── POST /api/auth/change-passcode ─────────────────────────────────────────

@router.post("/change-passcode")
async def change_passcode_endpoint(body: ChangePasscodeRequest, user: dict = Depends(get_current_user)):
    # Verify current
    if not verify_password(body.current_passcode, user["password_hash"]):
        log_audit_event(user["user_id"], "change_passcode_fail", "", False, {"reason": "wrong_current"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current passcode is incorrect.")

    if len(body.new_passcode) < MIN_PASSCODE_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"New passcode must be at least {MIN_PASSCODE_LENGTH} characters.",
        )

    new_hash = hash_password(body.new_passcode)
    execute_write(
        "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE user_id = ?",
        (new_hash, datetime.now(timezone.utc).isoformat(), user["user_id"]),
    )
    log_audit_event(user["user_id"], "passcode_changed", "", True, {})
    return {"success": True}


# ─── GET /api/auth/me ────────────────────────────────────────────────────────

@router.get("/me")
async def me_endpoint(user: dict = Depends(get_current_user)):
    return _user_payload(user)


# ─── GET /api/auth/validate ──────────────────────────────────────────────────

@router.get("/validate")
async def validate_endpoint(user: dict = Depends(get_current_user)):
    return {"valid": True, **_user_payload(user)}


# ─── POST /api/auth/provision (admin only) ───────────────────────────────────

class ProvisionRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    passcode: str = Field(..., min_length=6)
    role: str = Field(default="user")


@router.post("/provision")
async def provision_endpoint(body: ProvisionRequest, user: dict = Depends(get_current_user)):
    """Create a new user. Admin only."""
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")

    username = sanitize_input(body.username).lower().strip()

    existing = fetch_one("SELECT user_id FROM users WHERE username = ?", (username,))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"User '{username}' already exists.")

    new_id = str(uuid.uuid4())
    first_name = body.display_name.strip().split()[0]
    pw_hash = hash_password(body.passcode)
    now = datetime.now(timezone.utc).isoformat()

    execute_write(
        """INSERT INTO users
               (user_id, email, email_verified, password_hash,
                created_at, updated_at, login_attempts,
                must_change_password, anonymized_id,
                username, display_name, first_name, role)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id,
            f"{username}@bens-shed.app",
            True,
            pw_hash,
            now, now,
            0,
            True,
            str(uuid.uuid4()),
            username, body.display_name.strip(), first_name, body.role,
        ),
    )

    log_audit_event(user["user_id"], "user_provisioned", "", True, {
        "new_username": username, "role": body.role,
    })

    return {
        "success": True,
        "username": username,
        "display_name": body.display_name.strip(),
        "role": body.role,
        "must_change_passcode": True,
    }


# ─── GET /api/auth/users (admin only) ────────────────────────────────────────

@router.get("/users")
async def list_users_endpoint(user: dict = Depends(get_current_user)):
    """List all users. Admin only."""
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required.")

    from database import fetch_all as _fa
    rows = _fa("SELECT user_id, username, display_name, first_name, role, last_login, must_change_password FROM users ORDER BY created_at")
    return {"users": [dict(r) for r in rows]}
