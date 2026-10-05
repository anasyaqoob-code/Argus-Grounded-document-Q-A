"""Resend wrapper — thin layer over resend.Emails.send.

Reads RESEND_API_KEY, RESEND_FROM_EMAIL, RESEND_FROM_NAME from env.
Failures are logged but never raised to the caller; a broken email
send must not 500 a password-reset request that already wrote its
token to the database.
"""

from __future__ import annotations

import logging
import os

import resend

logger = logging.getLogger("argus.email")


def _configure() -> None:
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    if key:
        resend.api_key = key


def _from_header() -> str:
    name = (os.getenv("RESEND_FROM_NAME") or "Argus").strip()
    addr = (os.getenv("RESEND_FROM_EMAIL") or "onboarding@resend.dev").strip()
    return f"{name} <{addr}>"


def send_password_reset(to_email: str, reset_url: str) -> bool:
    """Send a password reset link. Returns True on success, False on any failure."""
    _configure()
    if not os.getenv("RESEND_API_KEY"):
        logger.warning("RESEND_API_KEY not set — skipping password reset email")
        return False

    html = f"""
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

    try:
        resend.Emails.send({
            "from": _from_header(),
            "to": to_email,
            "subject": "Reset your Argus password",
            "html": html,
        })
        return True
    except Exception:
        logger.exception("Failed to send password reset email to %s", to_email)
        return False


__all__ = ["send_password_reset"]