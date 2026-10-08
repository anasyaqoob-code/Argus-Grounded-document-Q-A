"""Email wrapper — Gmail SMTP with Resend fallback.

Primary: Gmail SMTP (sends to any recipient, free, no domain needed).
Fallback: Resend (used if GMAIL_USER is not configured).

Reads GMAIL_USER, GMAIL_APP_PASSWORD, RESEND_API_KEY, RESEND_FROM_EMAIL,
RESEND_FROM_NAME from env. Failures are logged but never raised to the
caller; a broken email send must not 500 a password-reset request that
already wrote its token to the database.
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import resend

logger = logging.getLogger("argus.email")


def _gmail_user() -> str:
    return (os.getenv("GMAIL_USER") or "").strip()


def _gmail_password() -> str:
    return (os.getenv("GMAIL_APP_PASSWORD") or "").replace(" ", "").strip()


def _configure_resend() -> None:
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    if key:
        resend.api_key = key


def _resend_from_header() -> str:
    name = (os.getenv("RESEND_FROM_NAME") or "Argus").strip()
    addr = (os.getenv("RESEND_FROM_EMAIL") or "onboarding@resend.dev").strip()
    return f"{name} <{addr}>"


def _reset_html(reset_url: str) -> str:
    return f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                max-width: 520px; margin: 0 auto; padding: 32px 24px;
                background: #0B0B14; color: #E8E8F0; border-radius: 12px;">
      <h1 style="color: #C4B5FD; font-size: 20px; margin: 0 0 16px 0;">
        Reset your Argus password
      </h1>
      <p style="color: #9CA3AF; font-size: 14px; line-height: 1.6; margin: 0 0 20px 0;">
        Someone (hopefully you) asked to reset the password for the Argus
        account associated with this email address. Click the button below
        to choose a new password. This link expires in 30 minutes.
      </p>
      <a href="{reset_url}"
         style="display: inline-block; padding: 12px 24px; background: #7C3AED;
                color: #FFFFFF; text-decoration: none; border-radius: 8px;
                font-weight: 600; font-size: 14px;">
        Reset password
      </a>
      <p style="color: #6B7280; font-size: 12px; line-height: 1.6; margin: 24px 0 0 0;">
        If you didn't request this, you can safely ignore this email —
        your password won't change until you click the link above.
      </p>
      <p style="color: #6B7280; font-size: 12px; margin: 16px 0 0 0;">
        Or paste this URL into your browser:<br>
        <span style="color: #C4B5FD; word-break: break-all;">{reset_url}</span>
      </p>
    </div>
    """


def _send_via_gmail(to_email: str, subject: str, html: str) -> bool:
    user = _gmail_user()
    password = _gmail_password()

    if not user or not password:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Argus <{user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        logger.info("Password reset email sent via Gmail to %s", to_email)
        return True
    except Exception:
        logger.exception("Gmail SMTP failed for %s", to_email)
        return False


def _send_via_resend(to_email: str, subject: str, html: str) -> bool:
    _configure_resend()
    if not os.getenv("RESEND_API_KEY"):
        return False

    try:
        resend.Emails.send({
            "from": _resend_from_header(),
            "to": to_email,
            "subject": subject,
            "html": html,
        })
        logger.info("Password reset email sent via Resend to %s", to_email)
        return True
    except Exception:
        logger.exception("Resend failed for %s", to_email)
        return False


def send_password_reset(to_email: str, reset_url: str) -> bool:
    """Send a password reset link.

    Tries Gmail SMTP first (works to any recipient without a verified
    domain). Falls back to Resend if Gmail creds are missing.
    Returns True on success, False on any failure.
    """
    subject = "Reset your Argus password"
    html = _reset_html(reset_url)

    if _gmail_user() and _gmail_password():
        if _send_via_gmail(to_email, subject, html):
            return True
        logger.warning("Gmail send failed; trying Resend fallback")

    if os.getenv("RESEND_API_KEY"):
        return _send_via_resend(to_email, subject, html)

    logger.warning("No email sender configured (GMAIL_USER or RESEND_API_KEY)")
    return False


__all__ = ["send_password_reset"]