"""Authentication primitives for Argus.

Three concerns, one file:

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

Nothing in this file touches the database or FastAPI. It is pure
functions over bytes and dicts. That makes it easy to unit-test and
impossible to accidentally couple to a route.
"""

from __future__ import annotations

import os
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


__all__ = [
    "COOKIE_NAME",
    "JWT_ALGORITHM",
    "JWT_EXPIRE_DAYS",
    "InvalidTokenError",
    "create_jwt",
    "decode_jwt",
    "hash_password",
    "verify_password",
]