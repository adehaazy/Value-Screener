"""
database.py - Database connection and schema management for the authentication system.
Uses SQLite for MVP with easy migration path to PostgreSQL/Supabase.
"""

import sqlite3
import uuid
import logging
from contextlib import contextmanager
from typing import Optional, Any

logger = logging.getLogger(__name__)

DB_PATH = "auth.db"


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create and return a database connection with row factory."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db(db_path: str = DB_PATH):
    """Context manager for database connections with automatic commit/rollback."""
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize the database with all required tables."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                email_verified BOOLEAN DEFAULT FALSE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                login_attempts INTEGER DEFAULT 0,
                locked_until TIMESTAMP,
                must_change_password BOOLEAN DEFAULT TRUE,
                anonymized_id TEXT UNIQUE
            )
        """)

        # Invitations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invitations (
                invitation_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                token_hash TEXT NOT NULL,
                created_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used_at TIMESTAMP,
                used_by TEXT
            )
        """)

        # Verification tokens table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verification_tokens (
                token_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                token_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                last_activity TIMESTAMP,
                device_info TEXT,
                ip_address TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Audit logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id TEXT PRIMARY KEY,
                user_id TEXT,
                event_type TEXT NOT NULL,
                event_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ip_address_hash TEXT,
                success BOOLEAN,
                metadata TEXT
            )
        """)

        # Rate limits table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                identifier TEXT PRIMARY KEY,
                attempt_count INTEGER DEFAULT 0,
                window_start TIMESTAMP,
                locked_until TIMESTAMP
            )
        """)

        # Per-user app data tables (watchlist, holdings, preferences)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_watchlist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                name        TEXT,
                data        TEXT NOT NULL DEFAULT '{}',
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, ticker)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_holdings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                name        TEXT,
                data        TEXT NOT NULL DEFAULT '{}',
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, ticker)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id     TEXT PRIMARY KEY,
                data        TEXT NOT NULL DEFAULT '{}',
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_custom_tickers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                ticker      TEXT NOT NULL,
                name        TEXT,
                group_name  TEXT,
                asset_class TEXT DEFAULT 'Stock',
                added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                UNIQUE(user_id, ticker)
            )
        """)

        # Indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_event_timestamp ON audit_logs(event_timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_verification_tokens_user_id ON verification_tokens(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_watchlist_uid ON user_watchlist(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_holdings_uid ON user_holdings(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_custom_tickers_uid ON user_custom_tickers(user_id)")

        logger.info("Database initialized successfully.")


# ─── Query helpers ────────────────────────────────────────────────────────────

def fetch_one(query: str, params: tuple = (), db_path: str = DB_PATH) -> Optional[sqlite3.Row]:
    """Execute a SELECT query and return a single row (or None)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()


def fetch_all(query: str, params: tuple = (), db_path: str = DB_PATH) -> list:
    """Execute a SELECT query and return all rows."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()


def execute_write(query: str, params: tuple = (), db_path: str = DB_PATH) -> int:
    """Execute an INSERT/UPDATE/DELETE query; returns rowcount."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.rowcount


def execute_many(query: str, params_list: list, db_path: str = DB_PATH) -> None:
    """Execute a query with many parameter sets (batch inserts, etc.)."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)


def cleanup_expired_sessions(db_path: str = DB_PATH) -> int:
    """Remove expired sessions from the database. Returns count deleted."""
    return execute_write(
        "DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP",
        db_path=db_path,
    )


def cleanup_expired_tokens(db_path: str = DB_PATH) -> int:
    """Remove expired verification/reset tokens. Returns count deleted."""
    return execute_write(
        "DELETE FROM verification_tokens WHERE expires_at < CURRENT_TIMESTAMP AND used_at IS NULL",
        db_path=db_path,
    )
