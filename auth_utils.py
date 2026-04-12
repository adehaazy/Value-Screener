"""
auth_utils.py - Core authentication utilities.
Handles password hashing, token generation, user registration, login, and session management.
"""

import hashlib
import hmac
import json
import logging
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from database import fetch_one, execute_write, fetch_all
from security import (
    validate_email,
    validate_password_strength,
    sanitize_input,
    anonymize_ip,
    check_rate_limit,
    increment_rate_limit,
)
from audit import log_audit_event

logger = logging.getLogger(__name__)

# ─── Argon2id hasher with OWASP-recommended parameters ────────────────────────
_ph = PasswordHasher(
    memory_cost=65536,   # 64 MB
    time_cost=3,
    parallelism=4,
)

# ─── Password helpers ──────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2id hash (constant-time)."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ─── Token helpers ─────────────────────────────────────────────────────────────

def generate_secure_token(length: int = 32) -> str:
    """Generate a cryptographically secure URL-safe token (hex encoded)."""
    return secrets.token_hex(length)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token (for safe database storage)."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_random_password(length: int = 12) -> str:
    """Generate a secure random password meeting complexity requirements."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        valid, _ = validate_password_strength(pwd)
        if valid:
            return pwd


# ─── JWT helpers ───────────────────────────────────────────────────────────────

def _get_jwt_secret() -> str:
    """Retrieve the JWT secret from Streamlit secrets or environment."""
    try:
        import streamlit as st
        return st.secrets["JWT_SECRET_KEY"]
    except Exception:
        import os
        secret = os.environ.get("JWT_SECRET_KEY", "")
        if not secret:
            raise RuntimeError("JWT_SECRET_KEY is not configured.")
        return secret


def create_jwt(user_id: str, email: str, expiry_hours: int = 24) -> str:
    """Create a signed JWT token for the given user."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": now,
        "exp": now + timedelta(hours=expiry_hours),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def decode_jwt(token: str) -> Optional[dict]:
    """Decode and validate a JWT. Returns payload dict or None on failure."""
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired.")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
    return None


# ─── Invitation management ─────────────────────────────────────────────────────

def create_invitation(admin_email: str, invitee_email: str) -> dict:
    """
    Generate an invitation for invitee_email.
    Returns {"success": True, "token": <raw_token>} or {"success": False, "error": ...}.
    """
    invitee_email = sanitize_input(invitee_email).lower().strip()
    if not validate_email(invitee_email):
        return {"success": False, "error": "Invalid email address."}

    # Check for existing unused invitation
    existing = fetch_one(
        "SELECT invitation_id FROM invitations WHERE email = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP",
        (invitee_email,),
    )
    if existing:
        return {"success": False, "error": "An active invitation already exists for this email."}

    invitation_id = str(uuid.uuid4())
    token = generate_secure_token(32)
    token_h = hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    execute_write(
        """INSERT INTO invitations (invitation_id, email, token_hash, created_by, expires_at)
           VALUES (?, ?, ?, ?, ?)""",
        (invitation_id, invitee_email, token_h, admin_email, expires_at.isoformat()),
    )
    logger.info(f"Invitation created for {invitee_email} by {admin_email}.")
    return {"success": True, "token": token, "email": invitee_email}


# ─── User registration ─────────────────────────────────────────────────────────

def register_user(invitation_token: str, email: str) -> dict:
    """
    Register a new user using a valid invitation token.
    Returns {"success": True, ...} or {"success": False, "error": ...}.
    """
    email = sanitize_input(email).lower().strip()
    if not validate_email(email):
        return {"success": False, "error": "Invalid email address."}

    token_h = hash_token(invitation_token)
    invitation = fetch_one(
        """SELECT * FROM invitations
           WHERE email = ? AND token_hash = ? AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP""",
        (email, token_h),
    )
    if not invitation:
        return {"success": False, "error": "Invalid or expired invitation."}

    # Check email not already registered
    existing_user = fetch_one("SELECT user_id FROM users WHERE email = ?", (email,))
    if existing_user:
        return {"success": False, "error": "An account with this email already exists."}

    # Create user with temporary password
    user_id = str(uuid.uuid4())
    anonymized_id = str(uuid.uuid4())
    temp_password = generate_random_password()
    password_hash = hash_password(temp_password)

    execute_write(
        """INSERT INTO users
               (user_id, email, email_verified, password_hash, anonymized_id, must_change_password)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, email, False, password_hash, anonymized_id, True),
    )

    # Mark invitation as used
    execute_write(
        "UPDATE invitations SET used_at = CURRENT_TIMESTAMP, used_by = ? WHERE invitation_id = ?",
        (user_id, invitation["invitation_id"]),
    )

    # Create email verification token (24-hour expiry)
    verification_token = _create_verification_token(user_id, "email_verification", hours=24)

    logger.info(f"User registered: {email} (id={user_id})")
    return {
        "success": True,
        "user_id": user_id,
        "email": email,
        "temp_password": temp_password,
        "verification_token": verification_token,
    }


def _create_verification_token(user_id: str, token_type: str, hours: int = 24) -> str:
    """Insert a new verification token and return the raw token string."""
    token_id = str(uuid.uuid4())
    raw_token = generate_secure_token(32)
    token_h = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    execute_write(
        """INSERT INTO verification_tokens (token_id, user_id, token_hash, token_type, expires_at)
           VALUES (?, ?, ?, ?, ?)""",
        (token_id, user_id, token_h, token_type, expires_at.isoformat()),
    )
    return raw_token


def verify_email(verification_token: str) -> bool:
    """Mark the user's email as verified if the token is valid. Returns success bool."""
    token_h = hash_token(verification_token)
    record = fetch_one(
        """SELECT vt.token_id, vt.user_id FROM verification_tokens vt
           WHERE vt.token_hash = ? AND vt.token_type = 'email_verification'
             AND vt.used_at IS NULL AND vt.expires_at > CURRENT_TIMESTAMP""",
        (token_h,),
    )
    if not record:
        return False

    # Mark token used
    execute_write(
        "UPDATE verification_tokens SET used_at = CURRENT_TIMESTAMP WHERE token_id = ?",
        (record["token_id"],),
    )
    # Verify user email
    execute_write(
        "UPDATE users SET email_verified = TRUE, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        (record["user_id"],),
    )
    logger.info(f"Email verified for user_id={record['user_id']}.")
    return True


# ─── Login / Logout ────────────────────────────────────────────────────────────

def login_user(email: str, password: str, ip_address: str) -> dict:
    """
    Authenticate a user. Returns session data or an error dict.
    """
    email = sanitize_input(email).lower().strip()
    anon_ip = anonymize_ip(ip_address)

    # Rate limiting check (raises RateLimitError on violation)
    try:
        check_rate_limit(email, ip_address)
    except PermissionError as e:
        log_audit_event(None, "rate_limit_exceeded", ip_address, False, {"email": email})
        return {"success": False, "error": str(e)}

    user = fetch_one("SELECT * FROM users WHERE email = ?", (email,))

    # Generic error to prevent email enumeration
    _generic_fail = {"success": False, "error": "Invalid email or password."}

    if not user:
        increment_rate_limit(email)
        log_audit_event(None, "failed_login", ip_address, False, {"email": email, "reason": "user_not_found"})
        return _generic_fail

    # Check account lockout
    if user["locked_until"]:
        locked_until = datetime.fromisoformat(user["locked_until"])
        if datetime.now(timezone.utc) < locked_until.replace(tzinfo=timezone.utc):
            remaining = int((locked_until.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds() / 60)
            log_audit_event(user["user_id"], "login_locked", ip_address, False, {"email": email})
            return {"success": False, "error": f"Account is locked. Try again in {remaining} minutes."}

    if not verify_password(password, user["password_hash"]):
        # Increment failed attempts
        new_attempts = (user["login_attempts"] or 0) + 1
        locked_until_val = None
        if new_attempts >= 5:
            locked_until_val = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        execute_write(
            "UPDATE users SET login_attempts = ?, locked_until = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (new_attempts, locked_until_val, user["user_id"]),
        )
        increment_rate_limit(email)
        log_audit_event(user["user_id"], "failed_login", ip_address, False, {"email": email, "attempt": new_attempts})
        return _generic_fail

    if not user["email_verified"]:
        log_audit_event(user["user_id"], "login_unverified", ip_address, False, {"email": email})
        return {"success": False, "error": "Please verify your email address before logging in."}

    # Reset failed attempts on success
    execute_write(
        "UPDATE users SET login_attempts = 0, locked_until = NULL, last_login = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
        (user["user_id"],),
    )

    # Create JWT + session record
    jwt_token = create_jwt(user["user_id"], email)
    token_h = hash_token(jwt_token)
    session_id = str(uuid.uuid4())
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    execute_write(
        """INSERT INTO sessions (session_id, user_id, token_hash, expires_at, last_activity, ip_address)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
        (session_id, user["user_id"], token_h, expires_at, anon_ip),
    )

    log_audit_event(user["user_id"], "login", ip_address, True, {"email": email})
    logger.info(f"User logged in: {email}")

    return {
        "success": True,
        "user_id": user["user_id"],
        "email": email,
        "jwt_token": jwt_token,
        "session_id": session_id,
        "must_change_password": bool(user["must_change_password"]),
    }


def logout_user(user_id: str, jwt_token: str) -> bool:
    """Revoke the session associated with the JWT token. Returns success bool."""
    token_h = hash_token(jwt_token)
    rows = execute_write(
        "DELETE FROM sessions WHERE user_id = ? AND token_hash = ?",
        (user_id, token_h),
    )
    log_audit_event(user_id, "logout", "", True, {})
    return rows > 0


# ─── Password reset ────────────────────────────────────────────────────────────

def request_password_reset(email: str) -> dict:
    """
    Initiate a password reset for the given email.
    Always returns success to prevent email enumeration.
    """
    email = sanitize_input(email).lower().strip()

    # Rate limiting for reset requests
    try:
        check_rate_limit(f"reset:{email}", "")
    except PermissionError as e:
        return {"success": False, "error": str(e)}

    user = fetch_one("SELECT user_id FROM users WHERE email = ? AND email_verified = TRUE", (email,))
    if not user:
        # Silent success to prevent enumeration
        return {"success": True}

    # Invalidate existing reset tokens for this user
    execute_write(
        """UPDATE verification_tokens SET used_at = CURRENT_TIMESTAMP
           WHERE user_id = ? AND token_type = 'password_reset' AND used_at IS NULL""",
        (user["user_id"],),
    )

    # Create 64-byte reset token (1-hour expiry)
    raw_token = generate_secure_token(64)
    token_id = str(uuid.uuid4())
    token_h = hash_token(raw_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    execute_write(
        """INSERT INTO verification_tokens (token_id, user_id, token_hash, token_type, expires_at)
           VALUES (?, ?, ?, 'password_reset', ?)""",
        (token_id, user["user_id"], token_h, expires_at),
    )

    increment_rate_limit(f"reset:{email}")
    log_audit_event(user["user_id"], "password_reset_requested", "", True, {"email": email})
    return {"success": True, "reset_token": raw_token, "user_id": user["user_id"], "email": email}


def reset_password(token: str, new_password: str) -> dict:
    """
    Reset the user's password using a valid reset token.
    Returns {"success": True} or {"success": False, "error": ...}.
    """
    valid, msg = validate_password_strength(new_password)
    if not valid:
        return {"success": False, "error": msg}

    token_h = hash_token(token)
    record = fetch_one(
        """SELECT vt.token_id, vt.user_id FROM verification_tokens vt
           WHERE vt.token_hash = ? AND vt.token_type = 'password_reset'
             AND vt.used_at IS NULL AND vt.expires_at > CURRENT_TIMESTAMP""",
        (token_h,),
    )
    if not record:
        return {"success": False, "error": "Invalid or expired password reset link."}

    new_hash = hash_password(new_password)

    # Update password and clear must_change_password flag
    execute_write(
        """UPDATE users
           SET password_hash = ?, must_change_password = FALSE,
               login_attempts = 0, locked_until = NULL, updated_at = CURRENT_TIMESTAMP
           WHERE user_id = ?""",
        (new_hash, record["user_id"]),
    )

    # Mark token as used
    execute_write(
        "UPDATE verification_tokens SET used_at = CURRENT_TIMESTAMP WHERE token_id = ?",
        (record["token_id"],),
    )

    # Revoke all existing sessions for security
    execute_write("DELETE FROM sessions WHERE user_id = ?", (record["user_id"],))

    log_audit_event(record["user_id"], "password_reset", "", True, {})
    return {"success": True}


def change_password(user_id: str, current_password: str, new_password: str) -> dict:
    """Allow an authenticated user to change their password."""
    user = fetch_one("SELECT password_hash FROM users WHERE user_id = ?", (user_id,))
    if not user or not verify_password(current_password, user["password_hash"]):
        return {"success": False, "error": "Current password is incorrect."}

    valid, msg = validate_password_strength(new_password)
    if not valid:
        return {"success": False, "error": msg}

    new_hash = hash_password(new_password)
    execute_write(
        """UPDATE users
           SET password_hash = ?, must_change_password = FALSE, updated_at = CURRENT_TIMESTAMP
           WHERE user_id = ?""",
        (new_hash, user_id),
    )
    # Invalidate all other sessions
    execute_write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    log_audit_event(user_id, "password_changed", "", True, {})
    return {"success": True}


# ─── Session validation ────────────────────────────────────────────────────────

def validate_session(jwt_token: str) -> Optional[dict]:
    """
    Validate a JWT token and confirm the session is still active in the database.
    Returns the decoded payload or None.
    """
    payload = decode_jwt(jwt_token)
    if not payload:
        return None

    token_h = hash_token(jwt_token)
    session = fetch_one(
        """SELECT session_id FROM sessions
           WHERE user_id = ? AND token_hash = ? AND expires_at > CURRENT_TIMESTAMP""",
        (payload["user_id"], token_h),
    )
    if not session:
        return None

    # Update last_activity
    execute_write(
        "UPDATE sessions SET last_activity = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session["session_id"],),
    )
    return payload
