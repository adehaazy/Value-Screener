"""
audit.py - Audit logging and GDPR compliance functions.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from database import execute_write, fetch_all, fetch_one
from security import hash_ip

logger = logging.getLogger(__name__)


# ─── Audit logging ─────────────────────────────────────────────────────────────

def log_audit_event(
    user_id: Optional[str],
    event_type: str,
    ip_address: str,
    success: bool,
    metadata: dict,
) -> None:
    """
    Record an authentication event in the audit log.
    IP addresses are stored as SHA-256 hashes (GDPR-compliant).
    """
    log_id = str(uuid.uuid4())
    ip_hash = hash_ip(ip_address) if ip_address else None
    metadata_json = json.dumps(metadata) if metadata else None

    try:
        execute_write(
            """INSERT INTO audit_logs
                   (log_id, user_id, event_type, ip_address_hash, success, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (log_id, user_id, event_type, ip_hash, success, metadata_json),
        )
    except Exception as e:
        # Audit failures must never crash the main flow
        logger.error(f"Failed to write audit log: {e}")


def get_user_audit_trail(user_id: str) -> list:
    """
    Retrieve the full audit trail for a user (GDPR right to access).
    Returns a list of event dicts, sorted by timestamp descending.
    """
    rows = fetch_all(
        """SELECT log_id, event_type, event_timestamp, success, metadata
           FROM audit_logs
           WHERE user_id = ?
           ORDER BY event_timestamp DESC""",
        (user_id,),
    )
    result = []
    for row in rows:
        entry = {
            "log_id": row["log_id"],
            "event_type": row["event_type"],
            "event_timestamp": row["event_timestamp"],
            "success": bool(row["success"]),
            "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
        }
        result.append(entry)
    return result


# ─── GDPR compliance ───────────────────────────────────────────────────────────

def get_user_data(user_id: str) -> Optional[dict]:
    """
    Return all data stored for a user (GDPR right to access / data portability).
    Excludes sensitive fields like password_hash.
    """
    user = fetch_one(
        """SELECT user_id, email, email_verified, created_at, updated_at,
                  last_login, anonymized_id
           FROM users WHERE user_id = ?""",
        (user_id,),
    )
    if not user:
        return None

    audit_trail = get_user_audit_trail(user_id)
    sessions = fetch_all(
        """SELECT session_id, created_at, expires_at, last_activity, device_info, ip_address
           FROM sessions WHERE user_id = ?""",
        (user_id,),
    )

    return {
        "user": dict(user),
        "audit_trail": audit_trail,
        "sessions": [dict(s) for s in sessions],
    }


def delete_user_data(user_id: str) -> None:
    """
    Permanently delete all user data (GDPR right to erasure / right to be forgotten).
    Cascade deletes sessions, tokens, and audit logs.
    """
    try:
        # Anonymize audit logs (retain event types for security monitoring, remove user link)
        execute_write(
            "UPDATE audit_logs SET user_id = NULL WHERE user_id = ?",
            (user_id,),
        )
        # Delete sessions
        execute_write("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        # Delete verification tokens
        execute_write("DELETE FROM verification_tokens WHERE user_id = ?", (user_id,))
        # Delete invitations created for this user
        execute_write("DELETE FROM invitations WHERE used_by = ?", (user_id,))
        # Delete the user record
        execute_write("DELETE FROM users WHERE user_id = ?", (user_id,))

        logger.info(f"User data deleted for user_id={user_id} (GDPR erasure).")
    except Exception as e:
        logger.error(f"Error during user data deletion for user_id={user_id}: {e}")
        raise
