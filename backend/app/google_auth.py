"""Google OAuth 2.0 endpoints.

Three routes:
  GET  /auth/google/start     — redirects the browser to Google's consent
                                screen.
  GET  /auth/google/callback  — Google redirects back here with a `code`
                                query param. We exchange it for an ID
                                token, extract the `sub` and `email`,
                                find-or-create the user, then redirect
                                to the FRONTEND with a short-lived
                                one-time exchange token.
  POST /auth/exchange         — called by the frontend (via fetch) with
                                the one-time token. Returns the user and
                                sets the session cookie on THIS response.

Why the extra hop?
------------------
Chrome's Bounce Tracking Mitigations (on by default) delete cookies for
domains that appear only as intermediate navigation hops in a redirect
chain. The old design set the session cookie on the /callback redirect
response — but `argus-grounded-...` is never the *destination* of a
navigation, only a stopover between Google and the frontend. Chrome
detected that and deleted the cookie.

Fix: the callback no longer sets the session cookie. Instead it redirects
to the frontend with a one-time token. The frontend then calls
/auth/exchange via fetch(). The cookie is set on that fetch response —
which is not a navigation chain, so bounce tracking ignores it.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from . import auth, storage as storage_mod
from .config import get_settings

logger = logging.getLogger("argus.google_auth")

router = APIRouter()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPES = "openid email profile"


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _set_session_cookie(response: Response, user_id: str) -> None:
    """Same cookie the password login sets, so /auth/me works identically."""
    response.set_cookie(
        key=auth.COOKIE_NAME,
        value=auth.create_jwt(user_id),
        httponly=True,
        samesite="none",
        secure=(os.getenv("ENV") or "").strip().lower() == "production",
        max_age=auth.JWT_EXPIRE_DAYS * 24 * 3600,
        path="/",
    )


@router.get("/auth/google/start")
def google_start() -> RedirectResponse:
    """Redirect the browser to Google's consent screen."""
    client_id = _env("GOOGLE_CLIENT_ID")
    redirect_uri = _env("GOOGLE_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured",
        )

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "online",
        "prompt": "select_account",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/google/callback")
def google_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    """Handle Google's redirect. Exchanges code, finds-or-creates user,
    then redirects to the frontend with a one-time exchange token."""
    settings = get_settings()
    frontend = settings.frontend_url.rstrip("/")

    if error or not code:
        # User clicked "deny", or Google returned an error.
        return RedirectResponse(f"{frontend}/login?google_error=1")

    client_id = _env("GOOGLE_CLIENT_ID")
    client_secret = _env("GOOGLE_CLIENT_SECRET")
    redirect_uri = _env("GOOGLE_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        return RedirectResponse(f"{frontend}/login?google_error=config")

    # Exchange the authorization code for an access token.
    try:
        token_resp = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        token_json = token_resp.json()
    except Exception:
        logger.exception("Google token exchange failed")
        return RedirectResponse(f"{frontend}/login?google_error=token")

    access_token = token_json.get("access_token")
    if not access_token:
        return RedirectResponse(f"{frontend}/login?google_error=token")

    # Fetch the user profile.
    try:
        info_resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        info_resp.raise_for_status()
        info = info_resp.json()
    except Exception:
        logger.exception("Google userinfo fetch failed")
        return RedirectResponse(f"{frontend}/login?google_error=userinfo")

    google_sub = str(info.get("sub") or "").strip()
    email = str(info.get("email") or "").strip().lower()
    email_verified = bool(info.get("email_verified", False))

    if not google_sub or not email:
        return RedirectResponse(f"{frontend}/login?google_error=missing")
    if not email_verified:
        return RedirectResponse(f"{frontend}/login?google_error=unverified")

    # Find-or-create the user.
    user_id: Optional[str] = None

    # 1. Already linked by Google sub.
    existing = storage_mod.get_user_by_google_sub(google_sub)
    if existing:
        user_id = existing["id"]
    else:
        # 2. Same email exists — link Google to that account.
        by_email = storage_mod.get_user_by_email(email)
        if by_email:
            storage_mod.link_google_sub(by_email["id"], google_sub)
            user_id = by_email["id"]
        else:
            # 3. Brand new user.
            user_id = storage_mod.create_google_user(email, google_sub)

    if not user_id:
        return RedirectResponse(f"{frontend}/login?google_error=create")

    try:
        storage_mod.record_auth_event(user_id, "login")
    except Exception:
        pass

    # IMPORTANT: do NOT set the session cookie here. Chrome's bounce
    # tracking mitigation deletes cookies set on domains that only appear
    # as redirect hops. Instead, mint a one-time token and send the browser
    # to the frontend, which will call /auth/exchange via fetch.
    exchange_token = auth.create_exchange_token(user_id, ttl_seconds=120)
    return RedirectResponse(
        f"{frontend}/auth/google/callback?token={exchange_token}"
    )


@router.post("/auth/exchange")
async def google_exchange(payload: dict, response: Response) -> dict:
    """Exchange a one-time OAuth token for a session cookie.

    Called via fetch() from the frontend's /auth/google/callback route.
    Sets the session cookie on THIS response — a fetch response from the
    frontend's origin, which Chrome does not treat as a bounce hop.
    """
    token = (payload or {}).get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    user_id = auth.consume_exchange_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = storage_mod.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    _set_session_cookie(response, user_id)

    return {
        "user_id": user_id,
        "email": user["email"],
        "is_admin": bool(user.get("is_admin", False)),
    }