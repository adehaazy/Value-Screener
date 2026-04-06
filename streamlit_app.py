"""
streamlit_app.py - Main Streamlit application.
Handles page routing and all UI flows for authentication.
"""

import logging

import streamlit as st

from auth_utils import (
    create_invitation,
    login_user,
    logout_user,
    register_user,
    request_password_reset,
    reset_password,
    change_password,
    validate_session,
    verify_email,
)
from database import cleanup_expired_sessions, cleanup_expired_tokens, init_db
from user_data import migrate_legacy_data_for_user
from email_service import (
    send_invitation_email,
    send_password_email,
    send_password_reset_email,
    send_verification_email,
)
from security import validate_password_strength

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── App configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Secure App",
    page_icon="🔐",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ─── One-time initialisation ───────────────────────────────────────────────────
@st.cache_resource
def _init():
    init_db()
    cleanup_expired_sessions()
    cleanup_expired_tokens()

_init()


# ─── Session state defaults ────────────────────────────────────────────────────
def _init_session_state():
    defaults = {
        "authenticated": False,
        "user_id": None,
        "jwt_token": None,
        "email": None,
        "page": "login",
        "must_change_password": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

_init_session_state()


# ─── URL parameter routing ─────────────────────────────────────────────────────
def _apply_url_params():
    """Route to correct page based on URL query parameters."""
    params = st.query_params
    if "page" in params:
        st.session_state["page"] = params["page"]


_apply_url_params()


# ─── Auth guard ────────────────────────────────────────────────────────────────
def _check_existing_session():
    """Re-validate JWT on every page load to handle expiry."""
    if st.session_state.get("jwt_token"):
        payload = validate_session(st.session_state["jwt_token"])
        if not payload:
            st.session_state["authenticated"] = False
            st.session_state["jwt_token"] = None
            st.session_state["user_id"] = None
            st.session_state["page"] = "login"

_check_existing_session()


# ─── Helper: password strength indicator ──────────────────────────────────────
def _password_checklist(password: str):
    checks = [
        ("At least 8 characters", len(password) >= 8),
        ("1 uppercase letter", any(c.isupper() for c in password)),
        ("1 lowercase letter", any(c.islower() for c in password)),
        ("1 number", any(c.isdigit() for c in password)),
        ("1 special character", bool(__import__("re").search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", password))),
    ]
    for label, passed in checks:
        icon = "✅" if passed else "❌"
        st.markdown(f"{icon} {label}")


# ─── Pages ─────────────────────────────────────────────────────────────────────

def page_login():
    st.title("🔐 Sign In")

    with st.form("login_form"):
        email = st.text_input("Email address", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", use_container_width=True)

    if submitted:
        if not email or not password:
            st.error("Please enter your email and password.")
        else:
            # Get client IP (Streamlit Cloud sets X-Forwarded-For)
            ip = st.context.headers.get("X-Forwarded-For", "127.0.0.1").split(",")[0].strip() if hasattr(st, "context") else "127.0.0.1"
            result = login_user(email.strip(), password, ip)
            if result["success"]:
                st.session_state["authenticated"] = True
                st.session_state["user_id"] = result["user_id"]
                st.session_state["jwt_token"] = result["jwt_token"]
                st.session_state["email"] = result["email"]
                st.session_state["must_change_password"] = result.get("must_change_password", False)
                if result.get("must_change_password"):
                    st.session_state["page"] = "change_password"
                else:
                    st.session_state["page"] = "app"
                st.rerun()
            else:
                st.error(result["error"])

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Forgot password?", use_container_width=True):
            st.session_state["page"] = "forgot_password"
            st.rerun()


def page_signup():
    """Invitation-based signup page."""
    st.title("📝 Create Your Account")

    params = st.query_params
    prefill_email = params.get("email", "")
    prefill_token = params.get("token", "")

    st.info(
        "**How registration works:**\n\n"
        "1. Enter your email and the invitation token you received.\n"
        "2. A **temporary password** will be sent to your email.\n"
        "3. A **verification link** will also be sent — you must verify before logging in.\n"
        "4. On first login you will be prompted to set a new password."
    )

    with st.form("signup_form"):
        email = st.text_input("Email address", value=prefill_email, placeholder="you@example.com")
        token = st.text_input("Invitation token", value=prefill_token)
        submitted = st.form_submit_button("Complete Registration", use_container_width=True)

    if submitted:
        if not email or not token:
            st.error("Please provide your email and invitation token.")
        else:
            result = register_user(token.strip(), email.strip())
            if result["success"]:
                # Send emails
                send_password_email(result["email"], result["temp_password"])
                send_verification_email(result["email"], result["verification_token"])
                st.success(
                    "✅ Account created! Check your email for:\n"
                    "- Your **temporary password**\n"
                    "- An **email verification link** (must verify before logging in)"
                )
                if st.button("Go to Login"):
                    st.session_state["page"] = "login"
                    st.rerun()
            else:
                st.error(result["error"])

    st.markdown("---")
    if st.button("← Back to Login"):
        st.session_state["page"] = "login"
        st.rerun()


def page_verify_email():
    """Email verification page — auto-verifies on load."""
    st.title("📧 Email Verification")

    params = st.query_params
    token = params.get("token", "")

    if not token:
        st.error("No verification token found in the URL.")
    else:
        with st.spinner("Verifying your email…"):
            success = verify_email(token)
        if success:
            st.success("✅ Your email has been verified! You can now log in.")
        else:
            st.error("❌ Verification failed. The link may have expired or already been used.")

    if st.button("Go to Login", use_container_width=True):
        st.session_state["page"] = "login"
        st.query_params.clear()
        st.rerun()


def page_forgot_password():
    """Step 1: request a password reset link."""
    st.title("🔑 Reset Your Password")
    st.write("Enter your email address and we'll send you a reset link if an account exists.")

    with st.form("forgot_form"):
        email = st.text_input("Email address", placeholder="you@example.com")
        submitted = st.form_submit_button("Send Reset Link", use_container_width=True)

    if submitted:
        if not email:
            st.error("Please enter your email address.")
        else:
            result = request_password_reset(email.strip())
            if result.get("success"):
                if result.get("reset_token"):
                    # Account exists — send email
                    send_password_reset_email(result["email"], result["reset_token"])
                # Always show same message to prevent enumeration
                st.success("If an account exists for that email, a reset link has been sent.")
            else:
                st.error(result.get("error", "An error occurred. Please try again."))

    if st.button("← Back to Login"):
        st.session_state["page"] = "login"
        st.rerun()


def page_reset_password():
    """Step 2: set a new password using a reset token."""
    st.title("🔑 Set New Password")

    params = st.query_params
    token = params.get("token", "")

    if not token:
        st.error("No reset token found. Please request a new password reset link.")
        if st.button("Request Reset"):
            st.session_state["page"] = "forgot_password"
            st.rerun()
        return

    with st.form("reset_form"):
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Reset Password", use_container_width=True)

    if new_password:
        _password_checklist(new_password)

    if submitted:
        if not new_password or not confirm_password:
            st.error("Please fill in both password fields.")
        elif new_password != confirm_password:
            st.error("Passwords do not match.")
        else:
            result = reset_password(token, new_password)
            if result["success"]:
                st.success("✅ Password reset successfully! You can now log in.")
                st.query_params.clear()
                if st.button("Go to Login"):
                    st.session_state["page"] = "login"
                    st.rerun()
            else:
                st.error(result["error"])


def page_change_password():
    """Force password change on first login."""
    st.title("🔒 Change Your Password")
    st.info("For your security, you must set a new password before continuing.")

    with st.form("change_pw_form"):
        current = st.text_input("Temporary / current password", type="password")
        new_pw = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        submitted = st.form_submit_button("Update Password", use_container_width=True)

    if new_pw:
        _password_checklist(new_pw)

    if submitted:
        if not current or not new_pw or not confirm:
            st.error("Please fill in all fields.")
        elif new_pw != confirm:
            st.error("New passwords do not match.")
        else:
            result = change_password(st.session_state["user_id"], current, new_pw)
            if result["success"]:
                st.success("✅ Password updated successfully! Please log in again.")
                # Clear session — user must log in fresh
                for k in ("authenticated", "user_id", "jwt_token", "email", "must_change_password"):
                    st.session_state[k] = None if k != "authenticated" else False
                st.session_state["page"] = "login"
                st.rerun()
            else:
                st.error(result["error"])


def page_app():
    """Protected main app content."""
    # One-time migration of legacy JSON data into per-user DB rows
    _uid = st.session_state.get("user_id")
    _migrated_key = f"_legacy_migrated_{_uid}"
    if _uid and not st.session_state.get(_migrated_key):
        migrate_legacy_data_for_user(_uid)
        st.session_state[_migrated_key] = True

    # Session expiry warning (show 30 min before expiry)
    st.sidebar.markdown(f"👤 **{st.session_state.get('email', 'User')}**")
    if st.sidebar.button("🚪 Sign Out"):
        logout_user(st.session_state["user_id"], st.session_state["jwt_token"])
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

    st.title("🏠 Welcome")
    st.success(f"You are signed in as **{st.session_state.get('email')}**.")
    st.markdown("---")
    st.write("Your protected app content goes here.")


def page_admin():
    """Admin panel: create invitations."""
    if not st.session_state.get("authenticated"):
        st.warning("Please log in first.")
        st.session_state["page"] = "login"
        st.rerun()

    st.title("⚙️ Admin: Create Invitation")
    with st.form("invite_form"):
        invitee_email = st.text_input("Invitee email address")
        submitted = st.form_submit_button("Generate Invitation", use_container_width=True)

    if submitted:
        if not invitee_email:
            st.error("Please enter an email address.")
        else:
            result = create_invitation(
                admin_email=st.session_state.get("email", "admin"),
                invitee_email=invitee_email.strip(),
            )
            if result["success"]:
                send_invitation_email(result["email"], result["token"])
                st.success(f"✅ Invitation sent to **{invitee_email}**.")
                st.code(result["token"], language=None)
                st.caption("Share this token with the invitee or they will receive it by email.")
            else:
                st.error(result["error"])


# ─── Router ────────────────────────────────────────────────────────────────────
PAGES = {
    "login": page_login,
    "signup": page_signup,
    "verify_email": page_verify_email,
    "forgot_password": page_forgot_password,
    "reset_password": page_reset_password,
    "change_password": page_change_password,
    "app": page_app,
    "admin": page_admin,
}

# Guard protected pages
PROTECTED_PAGES = {"app", "admin", "change_password"}
current_page = st.session_state.get("page", "login")

if current_page in PROTECTED_PAGES and not st.session_state.get("authenticated"):
    st.session_state["page"] = "login"
    current_page = "login"

page_fn = PAGES.get(current_page, page_login)
page_fn()
