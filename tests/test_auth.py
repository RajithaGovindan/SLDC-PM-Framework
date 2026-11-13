"""Sign in with Google: redirect to Google, state check, token checks, allow-list, session, sign-out."""
from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers import auth


@pytest.fixture()
def signin(monkeypatch):
    s = app.state  # noqa: F841 - keep app imported
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "client-123.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(settings, "allowed_emails", "Lead@Example.com, qa@example.com")
    return settings


def _fake_token_exchange(monkeypatch, info: dict):
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"id_token": "tok"}))
    monkeypatch.setattr(auth, "verify_id_token", lambda token: info)


def _login(c, nxt="/projects/1"):
    r = c.get(f"/auth/login?next={nxt}", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith(auth.AUTH_URL)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["client_id"] == ["client-123.apps.googleusercontent.com"] and q["scope"] == ["openid email"]
    assert q["redirect_uri"][0].endswith("/auth/callback")
    return q["state"][0]


def test_pages_need_sign_in(signin):
    with TestClient(app) as c:
        r = c.get("/projects/1", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/auth/login?next=%2Fprojects%2F1"
        assert c.post("/projects", data={"name": "x"}, follow_redirects=False).status_code == 401
        assert c.get("/healthz").status_code == 200
        assert c.get("/static/app.css").status_code == 200


def test_allowed_user_signs_in_and_out(signin, monkeypatch):
    _fake_token_exchange(monkeypatch, {"email": "lead@example.com", "email_verified": True, "iss": "accounts.google.com"})
    with TestClient(app) as c:
        state = _login(c)
        r = c.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/projects/1"
        page = c.get("/").text
        assert "lead@example.com" in page and "Sign out" in page
        assert "Signed out" in c.get("/auth/logout").text
        assert c.get("/", follow_redirects=False).status_code == 303


def test_refused_cases(signin, monkeypatch):
    with TestClient(app) as c:
        _fake_token_exchange(monkeypatch, {"email": "stranger@gmail.com", "email_verified": True, "iss": "accounts.google.com"})
        state = _login(c)
        r = c.get(f"/auth/callback?code=abc&state={state}")
        assert r.status_code == 403 and "stranger@gmail.com" in r.text
        assert c.get("/", follow_redirects=False).status_code == 303  # no session was created

        _fake_token_exchange(monkeypatch, {"email": "qa@example.com", "email_verified": False, "iss": "accounts.google.com"})
        state = _login(c)
        assert c.get(f"/auth/callback?code=abc&state={state}").status_code == 403

        _fake_token_exchange(monkeypatch, {"email": "qa@example.com", "email_verified": True, "iss": "accounts.google.com"})
        _login(c)
        assert c.get("/auth/callback?code=abc&state=forged").status_code == 400  # state mismatch

        def bad_token(token):
            raise ValueError("bad signature")
        monkeypatch.setattr(auth, "verify_id_token", bad_token)
        state = _login(c)
        assert c.get(f"/auth/callback?code=abc&state={state}").status_code == 400


def test_next_cannot_leave_the_site(signin, monkeypatch):
    _fake_token_exchange(monkeypatch, {"email": "qa@example.com", "email_verified": True, "iss": "accounts.google.com"})
    with TestClient(app) as c:
        state = _login(c, nxt="//evil.example/x")
        r = c.get(f"/auth/callback?code=abc&state={state}", follow_redirects=False)
        assert r.headers["location"] == "/"
