"""Authentication primitives for Argus.

Four concerns, one file:

  1. **Password hashing** — bcrypt with a per-password salt. The stored
     value never reveals the password. ``verify_password`` runs a
     constant-time comparison so timing doesn't leak whether the hash
     matched.

  2. **JWT issuance** — signed tokens carrying the user id in the ``sub``
     claim and an expiry. The signing key comes from ``JWT_SECRET`` in
     the environment. Missing key = fail loudly at import time, so a
     misconfigured deploy never silently issues unsigned tokens.

  3. **JWT validation** — decode + verify signature + check expiry.
     Raises a typed error the caller can map to HTTP 401.

  4. **One-time exchange tokens** — short-lived opaque tokens used to
     bridge the Google OAuth callback to the frontend without setting
     the session cookie on a cross-domain navigation. See google_auth.py
     for the full rationale (Chrome bounce-tracking mitigations).

Nothing in this file touches the database or FastAPI. It is pure
functions over bytes and dicts. That makes it easy to unit-test and
impossible to accidentally couple to a route.
"""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7
COOKIE_NAME = "argus_session"

# Fail at import time if the secret is missing. A default value here
# would silently ship in production and let anyone forge tokens.
_JWT_SECRET: Optional[str] = os.getenv("JWT_SECRET")
if not _JWT_SECRET:
    raise RuntimeError(
        "JWT_SECRET is not set. Add a long random string to your .env file. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
    )


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt.

    bcrypt includes the salt in the output, so storing the whole string
    is sufficient — no separate salt column.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check of a plaintext password against a stored hash.

    Returns False on any failure — malformed hash, wrong password, empty
    input — so the caller never has to distinguish "user exists but
    password wrong" from "hash was corrupt". That's the correct behavior
    for a login endpoint: never leak which half was wrong.
    """
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
class InvalidTokenError(Exception):
    """Raised when a token is missing, malformed, expired, or forged."""


def create_jwt(user_id: str) -> str:
    """Sign a JWT carrying the user id in ``sub`` with a 7-day expiry."""
    if not user_id:
        raise ValueError("user_id cannot be empty")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=JWT_EXPIRE_DAYS)).timestamp()),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> str:
    """Decode a JWT and return the user id from the ``sub`` claim.

    Raises ``InvalidTokenError`` on any failure — missing token, bad
    signature, expired, malformed payload. The caller maps that to a 401.
    """
    if not token:
        raise InvalidTokenError("Missing token")
    try:
        payload = jwt.decode(
            token,
            _JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError("Invalid token") from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise InvalidTokenError("Token missing subject")
    return user_id


# ---------------------------------------------------------------------------
# One-time exchange tokens (Google OAuth bridge)
# ---------------------------------------------------------------------------
# Short-lived, single-use tokens used to hand off a completed Google login
# from the backend callback to the frontend, so the session cookie can be
# set on a fetch response instead of a cross-domain navigation response.
#
# Storage note: this is in-memory, which is correct for a single Railway
# replica. If you scale horizontally, move this to Redis or your user
# store — otherwise a token minted on replica A won't be redeemable on
# replica B.
#
# Format: { token: (user_id, expires_at_unix) }
_EXCHANGE_TOKENS: dict[str, tuple[str, float]] = {}

# How long a minted token stays valid. Two minutes is generous for a
# redirect + one fetch round-trip and tight enough to be safe if a token
# leaks into a referrer header.
_EXCHANGE_TOKEN_TTL_SECONDS = 120


def create_exchange_token(user_id: str, ttl_seconds: int = _EXCHANGE_TOKEN_TTL_SECONDS) -> str:
    """Mint a single-use token that can be exchanged for a session cookie.

    The token is a URL-safe random string; it carries no data itself,
    which means it cannot leak the user id if intercepted. Redemption
    looks the user id up server-side.

    Expired tokens are garbage-collected opportunistically on each call.
    """
    if not user_id:
        raise ValueError("user_id cannot be empty")

    token = secrets.token_urlsafe(32)
    expires_at = time.time() + ttl_seconds
    _EXCHANGE_TOKENS[token] = (user_id, expires_at)

    # Opportunistic GC — cheap since the dict is tiny.
    now = time.time()
    for key in [k for k, (_, exp) in _EXCHANGE_TOKENS.items() if exp < now]:
        _EXCHANGE_TOKENS.pop(key, None)

    return token


def consume_exchange_token(token: str) -> Optional[str]:
    """Validate and burn a one-time token.

    Returns the user id on success, or ``None`` if the token was missing,
    unknown, or expired. Always removes the token from the store, so a
    second call with the same token returns ``None`` even if the first
    call succeeded — that's the "single-use" guarantee.
    """
    if not token:
        return None

    entry = _EXCHANGE_TOKENS.pop(token, None)
    if not entry:
        return None

    user_id, expires_at = entry
    if time.time() > expires_at:
        return None
    return user_id


__all__ = [
    "COOKIE_NAME",
    "JWT_ALGORITHM",
    "JWT_EXPIRE_DAYS",
    "InvalidTokenError",
    "consume_exchange_token",
    "create_exchange_token",
    "create_jwt",
    "decode_jwt",
    "hash_password",
    "verify_password",
]