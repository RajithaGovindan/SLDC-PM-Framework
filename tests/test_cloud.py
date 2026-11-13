"""Cloud pieces: IAP guard, Cloud Storage attachments, remote repositories, no silent SQLite fallback."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.services import attachments, repo_sync, repo_tools


def test_iap_guard(monkeypatch):
    monkeypatch.setattr(app_main.get_settings(), "require_iap", True)  # the cached settings object
    with TestClient(app) as c:
        assert c.get("/").status_code == 403
        assert c.get("/healthz").status_code == 200
        r = c.get("/", headers={"x-goog-authenticated-user-email": "accounts.google.com:lead@example.com"})
        assert r.status_code == 200 and "lead@example.com" in r.text


class FakeBlob:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def upload_from_string(self, data, content_type=None):
        self.store[self.key] = data

    def download_as_bytes(self):
        return self.store[self.key]

    def exists(self):
        return self.key in self.store

    def delete(self):
        del self.store[self.key]


class FakeBucket:
    def __init__(self):
        self.store = {}

    def blob(self, key):
        return FakeBlob(self.store, key)

    def list_blobs(self, prefix=""):
        return [FakeBlob(self.store, k) for k in list(self.store) if k.startswith(prefix)]


def test_attachments_in_bucket(monkeypatch):
    bucket = FakeBucket()
    real = attachments.get_settings()
    monkeypatch.setattr(attachments, "get_settings",
                        lambda: SimpleNamespace(**{**real.__dict__, "attachments_bucket": "b"}))
    monkeypatch.setattr(attachments, "_bucket", lambda: bucket)
    attachments._write(7, "abc_note.txt", b"hello", "text/plain")
    att = SimpleNamespace(project_id=7, stored_name="abc_note.txt")
    assert bucket.store == {"7/abc_note.txt": b"hello"}
    assert attachments.read_bytes(att) == b"hello" and attachments.exists(att)
    attachments._write(7, "def_x.png", b"x", "image/png")
    attachments.remove_project_files(7)
    assert bucket.store == {}


def test_remote_repositories(monkeypatch):
    assert repo_tools.is_remote("https://github.com/owner/repo")
    assert not repo_tools.is_remote(r"D:\code\repo")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stderr="fatal: auth failed for token SECRET123", stdout="")

    monkeypatch.setattr(repo_tools.subprocess, "run", fake_run)
    with pytest.raises(repo_tools.RepoToolError) as err:
        repo_tools._git(["clone", "https://github.com/o/r.git", "x"], "SECRET123")
    assert "SECRET123" not in str(err.value) and "***" in str(err.value)
    assert any("http.extraHeader=Authorization: Basic" in part for part in calls[0])
    assert "SECRET123" not in " ".join(calls[0])  # only base64 in the header, never in the URL


def test_repo_sync_refuses_url():
    project = SimpleNamespace(target_repo_path="https://github.com/o/r", sync_logs=[], id=1, artifacts=[])
    log = repo_sync.sync_project(SimpleNamespace(flush=lambda: None), project)
    assert not log.success and "Download all" in log.message


def test_no_silent_sqlite_fallback(monkeypatch):
    from app import database

    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(
        cloudsql_instance="", database_url="", db_fallback_to_sqlite=False, sqlite_url="sqlite://", sqlite_path=""))
    with pytest.raises(RuntimeError):
        database.build_engine()
