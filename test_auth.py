"""
test_auth.py - Unit tests for the authentication system.
Run with: python -m pytest test_auth.py -v
"""

import hashlib
import os
import re
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# ─── Set up an in-memory test database ────────────────────────────────────────
TEST_DB = ":memory:"

# Patch database path before importing modules
import database
database.DB_PATH = TEST_DB

import security
from security import (
    validate_email,
    validate_password_strength,
    sanitize_input,
    anonymize_ip,
    hash_ip,
    check_rate_limit,
    increment_rate_limit,
)
from auth_utils import (
    hash_password,
    verify_password,
    generate_secure_token,
    hash_token,
    generate_random_password,
    create_invitation,
    register_user,
    verify_email,
    login_user,
    logout_user,
    request_password_reset,
    reset_password,
)
from database import init_db, fetch_one


def setup_test_db():
    """Initialize a fresh test database for each test."""
    init_db(TEST_DB)


class TestPasswordHashing(unittest.TestCase):
    def setUp(self):
        setup_test_db()

    def test_hash_password_returns_string(self):
        result = hash_password("TestPass1!")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 20)

    def test_verify_password_correct(self):
        pw = "CorrectPass1!"
        h = hash_password(pw)
        self.assertTrue(verify_password(pw, h))

    def test_verify_password_wrong(self):
        h = hash_password("CorrectPass1!")
        self.assertFalse(verify_password("WrongPass1!", h))

    def test_hash_is_not_plain_text(self):
        pw = "MySecret1!"
        h = hash_password(pw)
        self.assertNotIn(pw, h)

    def test_unique_hashes_for_same_password(self):
        """Argon2 uses random salts — two hashes of the same password should differ."""
        pw = "SamePass1!"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        self.assertNotEqual(h1, h2)


class TestTokenGeneration(unittest.TestCase):
    def test_generate_secure_token_default_length(self):
        token = generate_secure_token()
        # 32 bytes hex-encoded = 64 characters
        self.assertEqual(len(token), 64)

    def test_generate_secure_token_custom_length(self):
        token = generate_secure_token(64)
        self.assertEqual(len(token), 128)

    def test_token_uniqueness(self):
        tokens = {generate_secure_token() for _ in range(100)}
        self.assertEqual(len(tokens), 100)

    def test_hash_token_consistency(self):
        token = generate_secure_token()
        h1 = hash_token(token)
        h2 = hash_token(token)
        self.assertEqual(h1, h2)

    def test_hash_token_is_sha256(self):
        token = "test_token"
        expected = hashlib.sha256(token.encode()).hexdigest()
        self.assertEqual(hash_token(token), expected)

    def test_hash_token_length(self):
        token = generate_secure_token()
        h = hash_token(token)
        self.assertEqual(len(h), 64)  # SHA-256 = 64 hex chars


class TestPasswordStrengthValidation(unittest.TestCase):
    def test_valid_password(self):
        valid, msg = validate_password_strength("StrongPass1!")
        self.assertTrue(valid)
        self.assertEqual(msg, "")

    def test_too_short(self):
        valid, msg = validate_password_strength("Sh1!")
        self.assertFalse(valid)
        self.assertIn("8 characters", msg)

    def test_no_uppercase(self):
        valid, msg = validate_password_strength("lowercase1!")
        self.assertFalse(valid)
        self.assertIn("uppercase", msg)

    def test_no_lowercase(self):
        valid, msg = validate_password_strength("UPPERCASE1!")
        self.assertFalse(valid)
        self.assertIn("lowercase", msg)

    def test_no_number(self):
        valid, msg = validate_password_strength("NoNumber!")
        self.assertFalse(valid)
        self.assertIn("number", msg)

    def test_no_special_char(self):
        valid, msg = validate_password_strength("NoSpecial1")
        self.assertFalse(valid)
        self.assertIn("special character", msg)


class TestEmailValidation(unittest.TestCase):
    def test_valid_emails(self):
        valid_emails = [
            "user@example.com",
            "user.name+tag@domain.co.uk",
            "user123@sub.domain.org",
        ]
        for email in valid_emails:
            with self.subTest(email=email):
                self.assertTrue(validate_email(email))

    def test_invalid_emails(self):
        invalid_emails = [
            "not-an-email",
            "@nodomain.com",
            "user@",
            "user @example.com",
            "",
            "a" * 255 + "@example.com",
        ]
        for email in invalid_emails:
            with self.subTest(email=email):
                self.assertFalse(validate_email(email))


class TestInputSanitization(unittest.TestCase):
    def test_strips_whitespace(self):
        self.assertEqual(sanitize_input("  hello  "), "hello")

    def test_html_escape(self):
        result = sanitize_input("<script>alert('xss')</script>")
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_length_limit(self):
        long_input = "a" * 1000
        result = sanitize_input(long_input)
        self.assertLessEqual(len(result), 500)

    def test_sql_injection_safe(self):
        payload = "'; DROP TABLE users; --"
        result = sanitize_input(payload)
        # Should not contain dangerous SQL — HTML escaped
        self.assertNotIn("DROP TABLE", result)

    def test_empty_string(self):
        self.assertEqual(sanitize_input(""), "")

    def test_non_string_input(self):
        self.assertEqual(sanitize_input(None), "")


class TestIPAnonymization(unittest.TestCase):
    def test_ipv4_anonymization(self):
        result = anonymize_ip("192.168.1.100")
        self.assertEqual(result, "192.168.1.xxx")

    def test_ipv4_preserves_first_three_octets(self):
        result = anonymize_ip("10.0.5.200")
        self.assertTrue(result.startswith("10.0.5."))
        self.assertTrue(result.endswith(".xxx"))

    def test_empty_ip(self):
        result = anonymize_ip("")
        self.assertEqual(result, "unknown")

    def test_hash_ip_consistent(self):
        ip = "192.168.1.1"
        h1 = hash_ip(ip)
        h2 = hash_ip(ip)
        self.assertEqual(h1, h2)

    def test_hash_ip_different_ips(self):
        h1 = hash_ip("192.168.1.1")
        h2 = hash_ip("10.0.0.1")
        self.assertNotEqual(h1, h2)


class TestRateLimiting(unittest.TestCase):
    def setUp(self):
        setup_test_db()
        # Clean rate_limits table
        database.execute_write("DELETE FROM rate_limits", db_path=TEST_DB)

    def test_first_attempt_passes(self):
        # Should not raise
        check_rate_limit("test@example.com", "1.2.3.4")

    def test_lockout_after_max_attempts(self):
        identifier = "locktest@example.com"
        # Exceed attempts
        for _ in range(security.LOGIN_MAX_ATTEMPTS):
            increment_rate_limit(identifier)

        with self.assertRaises(PermissionError):
            check_rate_limit(identifier, "1.2.3.4")

    def test_increment_increases_count(self):
        identifier = "counter@example.com"
        increment_rate_limit(identifier)
        increment_rate_limit(identifier)
        row = fetch_one("SELECT attempt_count FROM rate_limits WHERE identifier = ?", (identifier,), TEST_DB)
        self.assertEqual(row["attempt_count"], 2)


class TestUserRegistrationAndLogin(unittest.TestCase):
    def setUp(self):
        setup_test_db()
        # Reset rate limits
        database.execute_write("DELETE FROM rate_limits", db_path=TEST_DB)

    def _create_verified_user(self, email="test@example.com"):
        """Helper: create an invitation, register a user, and verify their email."""
        # Create invitation
        inv = create_invitation("admin@example.com", email)
        self.assertTrue(inv["success"], inv)

        # Register
        reg = register_user(inv["token"], email)
        self.assertTrue(reg["success"], reg)

        # Verify email
        self.assertTrue(verify_email(reg["verification_token"]))

        return reg

    def test_register_with_valid_invitation(self):
        result = self._create_verified_user("newuser@example.com")
        self.assertTrue(result["success"])
        self.assertIn("temp_password", result)

    def test_register_with_invalid_token(self):
        result = register_user("invalid_token", "someone@example.com")
        self.assertFalse(result["success"])

    def test_register_duplicate_email(self):
        self._create_verified_user("dup@example.com")
        # Second invitation for same email
        inv2 = create_invitation("admin@example.com", "dup2@example.com")
        # Direct insert to simulate second attempt with same email in registration
        # (invitation is email-unique so test via duplicate user insert attempt)
        inv_dup = create_invitation("admin@example.com", "dup@example.com")
        self.assertFalse(inv_dup["success"])  # Should fail as invitation already used/exists

    def test_login_with_valid_credentials(self):
        reg = self._create_verified_user("logintest@example.com")
        result = login_user("logintest@example.com", reg["temp_password"], "127.0.0.1")
        self.assertTrue(result["success"])
        self.assertIn("jwt_token", result)

    def test_login_wrong_password(self):
        self._create_verified_user("wrongpw@example.com")
        result = login_user("wrongpw@example.com", "WrongPass99!", "127.0.0.1")
        self.assertFalse(result["success"])
        self.assertIn("Invalid", result["error"])

    def test_login_unverified_email(self):
        inv = create_invitation("admin@example.com", "unverified@example.com")
        reg = register_user(inv["token"], "unverified@example.com")
        result = login_user("unverified@example.com", reg["temp_password"], "127.0.0.1")
        self.assertFalse(result["success"])
        self.assertIn("verify", result["error"].lower())

    def test_account_lockout_after_5_failures(self):
        reg = self._create_verified_user("lockout@example.com")
        for _ in range(5):
            login_user("lockout@example.com", "WrongPass1!", "127.0.0.1")
        result = login_user("lockout@example.com", reg["temp_password"], "127.0.0.1")
        self.assertFalse(result["success"])
        self.assertIn("lock", result["error"].lower())

    def test_logout_revokes_session(self):
        reg = self._create_verified_user("logout@example.com")
        login_result = login_user("logout@example.com", reg["temp_password"], "127.0.0.1")
        self.assertTrue(login_result["success"])
        ok = logout_user(login_result["user_id"], login_result["jwt_token"])
        self.assertTrue(ok)
        # Session should be gone from DB
        from auth_utils import hash_token
        token_h = hash_token(login_result["jwt_token"])
        row = fetch_one(
            "SELECT session_id FROM sessions WHERE token_hash = ?", (token_h,), TEST_DB
        )
        self.assertIsNone(row)


class TestSessionExpiry(unittest.TestCase):
    def setUp(self):
        setup_test_db()
        database.execute_write("DELETE FROM rate_limits", db_path=TEST_DB)

    def test_validate_session_with_valid_token(self):
        from auth_utils import create_jwt, hash_token
        import uuid
        user_id = str(uuid.uuid4())
        # Insert a user
        database.execute_write(
            "INSERT INTO users (user_id, email, password_hash, email_verified, anonymized_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, "sess@example.com", "hash", True, str(uuid.uuid4())),
            TEST_DB,
        )
        with patch("auth_utils._get_jwt_secret", return_value="test_secret_key_256bits_long_enough_for_jwt"):
            jwt_token = create_jwt(user_id, "sess@example.com")
            token_h = hash_token(jwt_token)
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            session_id = str(uuid.uuid4())
            database.execute_write(
                "INSERT INTO sessions (session_id, user_id, token_hash, expires_at, last_activity) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (session_id, user_id, token_h, expires_at),
                TEST_DB,
            )
            from auth_utils import validate_session
            payload = validate_session(jwt_token)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["user_id"], user_id)


class TestPasswordReset(unittest.TestCase):
    def setUp(self):
        setup_test_db()
        database.execute_write("DELETE FROM rate_limits", db_path=TEST_DB)

    def _create_verified_user(self, email):
        inv = create_invitation("admin@example.com", email)
        reg = register_user(inv["token"], email)
        verify_email(reg["verification_token"])
        return reg

    def test_password_reset_flow(self):
        self._create_verified_user("resetme@example.com")
        result = request_password_reset("resetme@example.com")
        self.assertTrue(result["success"])
        self.assertIn("reset_token", result)

        new_pw = "NewSecurePass1!"
        reset_result = reset_password(result["reset_token"], new_pw)
        self.assertTrue(reset_result["success"])

        # Login with new password should work
        database.execute_write("DELETE FROM rate_limits", db_path=TEST_DB)
        login_result = login_user("resetme@example.com", new_pw, "127.0.0.1")
        self.assertTrue(login_result["success"])

    def test_reset_with_invalid_token(self):
        result = reset_password("invalid_token", "NewPass1!")
        self.assertFalse(result["success"])

    def test_reset_enforces_password_strength(self):
        self._create_verified_user("weakreset@example.com")
        result = request_password_reset("weakreset@example.com")
        reset_result = reset_password(result["reset_token"], "weak")
        self.assertFalse(reset_result["success"])

    def test_reset_for_nonexistent_email_silent(self):
        """Should silently succeed to prevent email enumeration."""
        result = request_password_reset("nobody@example.com")
        self.assertTrue(result["success"])
        self.assertNotIn("reset_token", result)


class TestTokenExpiry(unittest.TestCase):
    def setUp(self):
        setup_test_db()

    def test_expired_verification_token_rejected(self):
        import uuid
        user_id = str(uuid.uuid4())
        database.execute_write(
            "INSERT INTO users (user_id, email, password_hash, anonymized_id) VALUES (?, ?, ?, ?)",
            (user_id, "expired@example.com", "hash", str(uuid.uuid4())),
            TEST_DB,
        )
        # Insert an already-expired token
        token = generate_secure_token()
        token_h = hash_token(token)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        database.execute_write(
            """INSERT INTO verification_tokens
                   (token_id, user_id, token_hash, token_type, expires_at)
               VALUES (?, ?, ?, 'email_verification', ?)""",
            (str(uuid.uuid4()), user_id, token_h, past),
            TEST_DB,
        )
        result = verify_email(token)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
