"""
email_service.py - Email sending functions via Mailgun SMTP.
All emails are sent using smtplib with TLS.
"""

import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)

# Max retries for transient email failures
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


def _get_email_config() -> dict:
    """Load email configuration from Streamlit secrets or environment variables."""
    try:
        import streamlit as st
        return {
            "host": st.secrets["MAILGUN_SMTP_HOST"],
            "user": st.secrets["MAILGUN_SMTP_USER"],
            "password": st.secrets["MAILGUN_SMTP_PASSWORD"],
            "sender": st.secrets["MAILGUN_SENDER"],
            "app_url": st.secrets.get("APP_URL", "https://your-app.streamlit.app"),
        }
    except Exception:
        import os
        return {
            "host": os.environ.get("MAILGUN_SMTP_HOST", "smtp.mailgun.org"),
            "user": os.environ.get("MAILGUN_SMTP_USER", ""),
            "password": os.environ.get("MAILGUN_SMTP_PASSWORD", ""),
            "sender": os.environ.get("MAILGUN_SENDER", "noreply@example.com"),
            "app_url": os.environ.get("APP_URL", "https://your-app.streamlit.app"),
        }


def _send_email(to_address: str, subject: str, html_body: str, text_body: str) -> bool:
    """
    Send an email via Mailgun SMTP with retry logic.
    Returns True on success, False on failure.
    """
    config = _get_email_config()

    if not config["user"] or not config["password"]:
        logger.warning("Email credentials not configured. Skipping email send.")
        # In development, log the email content instead
        logger.info(f"[DEV EMAIL] To: {to_address}\nSubject: {subject}\n{text_body}")
        return True  # Treat as success in dev

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["sender"]
    msg["To"] = to_address

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with smtplib.SMTP(config["host"], 587, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(config["user"], config["password"])
                server.sendmail(config["sender"], [to_address], msg.as_string())
            logger.info(f"Email sent successfully to {to_address}: {subject}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP authentication failed. Check Mailgun credentials.")
            return False
        except Exception as e:
            logger.warning(f"Email send attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    logger.error(f"Failed to send email to {to_address} after {MAX_RETRIES} attempts.")
    return False


# ─── Public email functions ────────────────────────────────────────────────────

def send_invitation_email(email: str, token: str) -> None:
    """Send an invitation email with a registration link."""
    config = _get_email_config()
    app_url = config["app_url"]
    registration_link = f"{app_url}/?page=signup&token={token}&email={email}"

    subject = "You're invited to join the platform"
    text_body = f"""
Hello,

You've been invited to create an account on our platform.

Click the link below to complete your registration (expires in 7 days):
{registration_link}

If you did not expect this invitation, please ignore this email.

Best regards,
The Platform Team
"""
    html_body = f"""
<html><body>
<h2>You're invited!</h2>
<p>You've been invited to create an account on our platform.</p>
<p><a href="{registration_link}" style="background:#4CAF50;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
   Accept Invitation
</a></p>
<p>This link expires in <strong>7 days</strong>.</p>
<p>If you did not expect this invitation, please ignore this email.</p>
</body></html>
"""
    _send_email(email, subject, html_body, text_body)


def send_password_email(email: str, temp_password: str) -> None:
    """Send the temporary password to the newly registered user."""
    subject = "Your temporary password"
    text_body = f"""
Hello,

Your account has been created. Here is your temporary password:

    {temp_password}

You will be required to change this password the first time you log in.
This temporary password expires in 24 hours.

Please verify your email using the separate verification email you received.

Best regards,
The Platform Team
"""
    html_body = f"""
<html><body>
<h2>Your temporary password</h2>
<p>Your account has been created. Here is your temporary password:</p>
<p style="font-size:1.4em;letter-spacing:2px;font-family:monospace;background:#f4f4f4;padding:10px;border-radius:4px;">
  <strong>{temp_password}</strong>
</p>
<p>You will be required to <strong>change this password</strong> on first login.</p>
<p>This password expires in <strong>24 hours</strong>.</p>
</body></html>
"""
    _send_email(email, subject, html_body, text_body)


def send_verification_email(email: str, token: str) -> None:
    """Send an email verification link."""
    config = _get_email_config()
    app_url = config["app_url"]
    verification_link = f"{app_url}/?page=verify_email&token={token}"

    subject = "Please verify your email address"
    text_body = f"""
Hello,

Please verify your email address by clicking the link below (expires in 24 hours):
{verification_link}

You must verify your email before you can log in.

Best regards,
The Platform Team
"""
    html_body = f"""
<html><body>
<h2>Verify your email address</h2>
<p>Please verify your email address to activate your account.</p>
<p><a href="{verification_link}" style="background:#2196F3;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
   Verify Email
</a></p>
<p>This link expires in <strong>24 hours</strong>.</p>
</body></html>
"""
    _send_email(email, subject, html_body, text_body)


def send_password_reset_email(email: str, token: str) -> None:
    """Send a password reset link."""
    config = _get_email_config()
    app_url = config["app_url"]
    reset_link = f"{app_url}/?page=reset_password&token={token}"

    subject = "Reset your password"
    text_body = f"""
Hello,

We received a request to reset your password. Click the link below (expires in 1 hour):
{reset_link}

If you did not request a password reset, please ignore this email. Your password will not change.

Best regards,
The Platform Team
"""
    html_body = f"""
<html><body>
<h2>Reset your password</h2>
<p>We received a request to reset your password.</p>
<p><a href="{reset_link}" style="background:#FF5722;color:white;padding:10px 20px;text-decoration:none;border-radius:4px;">
   Reset Password
</a></p>
<p>This link expires in <strong>1 hour</strong>.</p>
<p>If you did not request this, please ignore this email.</p>
</body></html>
"""
    _send_email(email, subject, html_body, text_body)
