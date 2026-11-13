"""Test settings, applied before any test module imports the app.

Every test runs in mock mode against a throwaway SQLite database and attachment folder, whatever the developer's
.env says. Without this, a test file that sorts before the others could import the app with the real .env
(live Claude, the real database).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sdlc_test_"))
os.environ.update(
    MOCK_AI="true",
    ANTHROPIC_API_KEY="",
    DATABASE_URL=f"sqlite:///{(TMP / 'test.db').as_posix()}",
    CLOUDSQL_INSTANCE="",
    ATTACHMENTS_BUCKET="",
    ATTACHMENTS_DIR=str(TMP / "attachments"),
    REPO_CACHE_DIR=str(TMP / "repos"),
    REQUIRE_IAP="false",
    DB_FALLBACK_TO_SQLITE="true",
)


def pytest_sessionstart(session):
    from app.config import get_settings

    s = get_settings()
    assert not s.ai_is_live, "tests must not call live Claude"
    assert str(TMP.as_posix()) in s.database_url, "tests must use the throwaway database"
