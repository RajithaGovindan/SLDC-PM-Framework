"""FastAPI application entry point.

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.database import DB_BACKEND, init_db
from app.routers import auth, dashboard, files, issues, stages, sync, team, traceability
from app.routers.auth import OPEN_PATHS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sdlc")


@asynccontextmanager
async def lifespan(_: FastAPI):
    s = get_settings()
    if s.auto_create_tables:
        init_db()
    log.info("Database backend: %s | AI mode: %s (%s)", DB_BACKEND, "LIVE" if s.ai_is_live else "MOCK",
             s.claude_model if s.ai_is_live else "offline generator")
    yield


app = FastAPI(title=get_settings().app_name, version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")

for r in (auth.router, dashboard.router, stages.router, traceability.router, team.router, sync.router, issues.router,
          files.router):
    app.include_router(r)


IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"


@app.middleware("http")
async def access_guard(request: Request, call_next):
    """Who is this, and may they in?

    - Identity-Aware Proxy (REQUIRE_IAP): IAP adds the signed-in e-mail as a header; requests without it are refused.
    - Sign in with Google (GOOGLE_CLIENT_ID set): the e-mail comes from the signed session cookie; anyone without a
      session is sent to /auth/login (pages) or gets 401 (anything else).
    The e-mail is kept on request.state.user_email for the pages to show.
    """
    s = get_settings()
    path = request.url.path
    raw = request.headers.get(IAP_EMAIL_HEADER, "")
    email = raw.split(":", 1)[-1] if raw else ""
    if s.google_sign_in:
        email = request.session.get("email", "")
    request.state.user_email = email
    if path == "/healthz" or (s.google_sign_in and path.startswith(OPEN_PATHS)):
        return await call_next(request)
    if s.require_iap and not raw:
        return PlainTextResponse("Sign in through the organisation's Google account to use this app.", status_code=403)
    if s.google_sign_in and not email:
        if request.method == "GET":
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/auth/login?{urlencode({'next': target})}", status_code=303)
        return PlainTextResponse("Sign in first.", status_code=401)
    return await call_next(request)


def _session_secret() -> str:
    s = get_settings()
    if s.google_sign_in and len(s.session_secret) < 32:
        raise RuntimeError("Google sign-in is on but SESSION_SECRET is missing or shorter than 32 characters.")
    return s.session_secret or secrets.token_urlsafe(32)  # sign-in off: cookies are unused, any key will do


# Added after the guard so it wraps it: the guard can read request.session.
app.add_middleware(SessionMiddleware, secret_key=_session_secret(), session_cookie="sdlc_session",
                   max_age=12 * 3600, same_site="lax", https_only=get_settings().public_url.startswith("https://"))


@app.get("/healthz")
def healthz():
    s = get_settings()
    return {"status": "ok", "db": DB_BACKEND, "ai": "live" if s.ai_is_live else "mock", "version": __version__}
