"""Sign in with Google (OAuth 2.0 authorisation-code flow) with an e-mail allow-list.

Turned on by setting GOOGLE_CLIENT_ID. Google confirms who the user is; the app accepts the ID token only after
verifying its signature, audience and issuer, and only for a verified e-mail on ALLOWED_EMAILS. The session is a
signed, HTTPS-only cookie (Starlette SessionMiddleware, keyed by SESSION_SECRET).
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings

log = logging.getLogger("sdlc.auth")
router = APIRouter()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
OPEN_PATHS = ("/healthz", "/auth/", "/static/")


def redirect_uri(request: Request) -> str:
    base = get_settings().public_url.rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/auth/callback"


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


def verify_id_token(token: str) -> dict:
    """Check the ID token's signature (Google's keys), audience and issuer. Raises ValueError if invalid."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    info = id_token.verify_oauth2_token(token, g_requests.Request(), get_settings().google_client_id)
    if info.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("Unexpected token issuer.")
    return info


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · SDLC Orchestrator</title>
<style>body{{font-family:system-ui,sans-serif;background:#f8fafc;color:#0f172a;display:grid;place-items:center;min-height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:32px 36px;max-width:420px;text-align:center}}
a.btn{{display:inline-block;margin-top:16px;background:#4f46e5;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600}}
p{{color:#475569;font-size:14px}}</style></head><body><div class="card"><h2>{title}</h2>{body}</div></body></html>""",
        status_code=status)


@router.get("/auth/login")
def login(request: Request, next: str = "/"):
    s = get_settings()
    if not s.google_sign_in:
        return RedirectResponse("/")
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["next"] = _safe_next(next)
    params = {"client_id": s.google_client_id, "redirect_uri": redirect_uri(request), "response_type": "code",
              "scope": "openid email", "state": state, "prompt": "select_account"}
    return RedirectResponse(f"{AUTH_URL}?{urlencode(params)}")


@router.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    s = get_settings()
    expected = request.session.pop("oauth_state", None)
    if error or not code or not expected or not secrets.compare_digest(state, expected):
        return _page("Sign-in failed", "<p>The sign-in was cancelled or expired.</p><a class='btn' href='/auth/login'>Try again</a>", 400)
    try:
        resp = httpx.post(TOKEN_URL, timeout=15, data={
            "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
            "redirect_uri": redirect_uri(request), "grant_type": "authorization_code"})
        resp.raise_for_status()
        info = verify_id_token(resp.json()["id_token"])
    except Exception as exc:  # noqa: BLE001 - any failure means no session
        log.warning("Google sign-in failed: %s", exc)
        return _page("Sign-in failed", "<p>Google could not confirm the sign-in.</p><a class='btn' href='/auth/login'>Try again</a>", 400)
    email = str(info.get("email", "")).lower()
    if not info.get("email_verified") or email not in s.allowed_email_set:
        log.info("Sign-in refused for %s", email or "(no e-mail)")
        request.session.clear()
        return _page("No access", f"<p><b>{email or 'This account'}</b> is not on this app's access list. "
                     "Ask the administrator to add it.</p><a class='btn' href='/auth/login'>Use another account</a>", 403)
    nxt = request.session.pop("next", "/")
    request.session.clear()
    request.session["email"] = email
    log.info("Signed in: %s", email)
    return RedirectResponse(_safe_next(nxt), status_code=303)


@router.get("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return _page("Signed out", "<p>You have signed out of the SDLC Orchestrator.</p><a class='btn' href='/auth/login'>Sign in again</a>")
