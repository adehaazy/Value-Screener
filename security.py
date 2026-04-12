"""
security.py - Security utilities: validation, sanitization, rate limiting, and IP handling.
"""

import hashlib
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Tuple

from database import fetch_one, execute_write

logger = logging.getLogger(__name__)

# ─── Constants ─────────────────────────────────────────────────────────────────
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_MINUTES = 15
LOGIN_LOCK_MINUTES = 30

RESET_MAX_ATTEMPTS = 3
RESET_WINDOW_MINUTES = 60

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


# ─── Input validation ──────────────────────────────────────────────────────────

def validate_email(email: str) -> bool:
    """Return True if email is a valid format."""
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email))


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Check password against complexity requirements.
    Returns (True, "") on pass, or (False, reason) on failure.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password):
        return False, "Password must contain at least one special character."
    return True, ""


def sanitize_input(user_input: str) -> str:
    """
    Sanitize user input to prevent XSS and SQL injection.
    - HTML-escapes special characters
    - Strips leading/trailing whitespace
    - Limits length to prevent abuse
    """
    if not isinstance(user_input, str):
        return ""
    # Strip whitespace
    cleaned = user_input.strip()
    # HTML escape to prevent XSS
    cleaned = html.escape(cleaned)
    # Limit length
    return cleaned[:500]


# ─── IP address handling ───────────────────────────────────────────────────────

def anonymize_ip(ip_address: str) -> str:
    """
    Anonymize IPv4 by masking the last octet: 192.168.1.100 → 192.168.1.xxx
    For IPv6, keep only the first 3 groups.
    """
    if not ip_address:
        return "unknown"
    # IPv4
    if "." in ip_address:
        parts = ip_address.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
    # IPv6 - keep first 3 groups
    if ":" in ip_address:
        groups = ip_address.split(":")
        return ":".join(groups[:3]) + ":xxxx:xxxx:xxxx:xxxx:xxxx"
    return "unknown"


def hash_ip(ip_address: str) -> str:
    """Return SHA-256 hash of IP for audit log storage."""
    if not ip_address:
        return ""
    return hashlib.sha256(ip_address.encode()).hexdigest()


# ─── Rate limiting (token bucket via database) ────────────────────────────────

def check_rate_limit(identifier: str, ip_address: str) -> None:
    """
    Check if the identifier (email or reset:email) has exceeded rate limits.
    Raises PermissionError with a human-readable message if limited.
    """
    # Determine limits based on identifier prefix
    if identifier.startswith("reset:"):
        max_attempts = RESET_MAX_ATTEMPTS
        window_minutes = RESET_WINDOW_MINUTES
        lock_minutes = LOGIN_LOCK_MINUTES
    else:
        max_attempts = LOGIN_MAX_ATTEMPTS
        window_minutes = LOGIN_WINDOW_MINUTES
        lock_minutes = LOGIN_LOCK_MINUTES

    now = datetime.now(timezone.utc)
    record = fetch_one("SELECT * FROM rate_limits WHERE identifier = ?", (identifier,))

    if record:
        # Check if currently locked
        if record["locked_until"]:
            locked_until = datetime.fromisoformat(record["locked_until"]).replace(tzinfo=timezone.utc)
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds() / 60)
                raise PermissionError(
                    f"Too many attempts. Please wait {remaining} minute(s) before trying again."
                )
            else:
                # Lock expired — reset record
                execute_write(
                    "UPDATE rate_limits SET attempt_count = 0, locked_until = NULL, window_start = ? WHERE identifier = ?",
                    (now.isoformat(), identifier),
                )
                return

        # Check if within window
        if record["window_start"]:
            window_start = datetime.fromisoformat(record["window_start"]).replace(tzinfo=timezone.utc)
            window_end = window_start + timedelta(minutes=window_minutes)
            if now < window_end and (record["attempt_count"] or 0) >= max_attempts:
                # Lock the identifier
                locked_until = now + timedelta(minutes=lock_minutes)
                execute_write(
                    "UPDATE rate_limits SET locked_until = ? WHERE identifier = ?",
                    (locked_until.isoformat(), identifier),
                )
                remaining = lock_minutes
                raise PermissionError(
                    f"Too many attempts. Please wait {remaining} minutes before trying again."
                )
            elif now >= window_end:
                # Window has passed — reset
                execute_write(
                    "UPDATE rate_limits SET attempt_count = 0, window_start = ?, locked_until = NULL WHERE identifier = ?",
                    (now.isoformat(), identifier),
                )


def increment_rate_limit(identifier: str) -> None:
    """Increment the attempt counter for an identifier."""
    now = datetime.now(timezone.utc)
    record = fetch_one("SELECT * FROM rate_limits WHERE identifier = ?", (identifier,))
    if record:
        execute_write(
            "UPDATE rate_limits SET attempt_count = attempt_count + 1 WHERE identifier = ?",
            (identifier,),
        )
    else:
        execute_write(
            "INSERT INTO rate_limits (identifier, attempt_count, window_start) VALUES (?, 1, ?)",
            (identifier, now.isoformat()),
        )
