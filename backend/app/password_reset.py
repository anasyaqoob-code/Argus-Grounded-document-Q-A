"""Password reset endpoints.

Two routes:
  POST /auth/forgot-password  — accepts an email, sends a reset link if
                                the account exists. Always returns 200,
                                never reveals whether the email is
                                registered (matches the login endpoint's
                                non-disclosure policy).
  POST /auth/reset-password   — accepts a token + new password, validates
                                the token, hashes the password with
                                bcrypt, updates the user, deletes the
                                token.
"""

from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from . import auth, storage as storage_mod
from .config import get_settings
from .email import send_password_reset

logger = logging.getLogger("argus.password_reset")

router = APIRouter()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/forgot-password")
def forgot_password(body: ForgotPasswordRequest) -> dict:
    """Kick off a password reset.

    Always returns 200 with the same message, regardless of whether the
    email is registered. This is intentional — the same non-disclosure
    rule the login endpoint follows.
    """
    settings = get_settings()
    normalized = body.email.strip().lower()

    user = storage_mod.get_user_by_email(normalized)

    # If the user exists and has a real password (not a Google-only
    # account), create a token and send the email.
    if user:
        # Google-only accounts have password_hash == "*" — those users
        # should be told to sign in with Google, not reset a password.
        password_hash = user.get("password_hash") or ""
        if password_hash and password_hash != "*":
            token = secrets.token_urlsafe(32)
            try:
                storage_mod.create_password_reset(user["id"], token, ttl_seconds=1800)
            except Exception:
                logger.exception("Failed to store password reset token")
            else:
                reset_url = (
                    f"{settings.frontend_url.rstrip('/')}"
                    f"/reset-password?token={token}"
                )
                try:
                    send_password_reset(normalized, reset_url)
                except Exception:
                    logger.exception("Failed to send password reset email")

    return {
        "ok": True,
        "message": (
            "If an account exists for that email, we've sent a reset link. "
            "Check your inbox (and spam) — the link expires in 30 minutes."
        ),
    }


@router.post("/auth/reset-password")
def reset_password(body: ResetPasswordRequest) -> dict:
    """Consume a reset token and set a new password."""
    user_id = storage_mod.consume_password_reset(body.token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid or has expired. Request a new one.",
        )

    password_hash = auth.hash_password(body.new_password)
    if not storage_mod.update_user_password(user_id, password_hash):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update password. Please try again.",
        )

    # Analytics — record the reset, best-effort.
    try:
        storage_mod.record_auth_event(user_id, "password_reset")
    except Exception:
        pass

    return {"ok": True, "message": "Password updated. You can sign in now."}