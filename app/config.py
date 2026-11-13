"""Application settings loaded from environment / .env."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SDLC Orchestrator"
    database_url: str = ""
    sqlite_path: str = str(BASE_DIR / "sdlc_pm.db")
    auto_create_tables: bool = True

    mock_ai: bool = True
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "high"  # low | medium | high | xhigh | max
    claude_max_tokens: int = 64000
    claude_enable_fallbacks: bool = True
    attachments_dir: str = str(BASE_DIR / "data" / "attachments")
    max_attachment_mb: int = 20
    attachments_bucket: str = ""      # Cloud Storage bucket; empty = store under attachments_dir

    # Cloud deployment
    cloudsql_instance: str = ""       # e.g. my-project:asia-south1:my-instance -> Cloud SQL connector, IAM sign-in
    db_name: str = "sdlc_pm"
    db_iam_user: str = ""             # service account e-mail without ".gserviceaccount.com"
    db_pool_size: int = 2             # a shared, small instance: keep this low
    db_fallback_to_sqlite: bool = True  # set false in the cloud: fail loudly instead of using a throwaway file
    require_iap: bool = False         # reject requests that did not come through Identity-Aware Proxy
    # App-level "Sign in with Google" (for accounts outside the cloud project's organisation)
    google_client_id: str = ""        # OAuth client ID; setting it turns sign-in on
    google_client_secret: str = ""
    allowed_emails: str = ""          # allow-list separated by commas, semicolons or spaces
    session_secret: str = ""          # random string that signs the session cookie
    public_url: str = ""              # e.g. https://app.example.com; used to build the OAuth redirect URI
    github_token: str = ""            # read-only token for cloning project repos given as https URLs
    repo_cache_dir: str = str(BASE_DIR / "data" / "repos")

    @field_validator("anthropic_api_key", "github_token", "google_client_secret", "session_secret", mode="before")
    @classmethod
    def _strip_secret(cls, v):
        # Secrets pasted into Secret Manager on Windows often carry a trailing line break.
        return v.strip() if isinstance(v, str) else v

    @property
    def google_sign_in(self) -> bool:
        return bool(self.google_client_id)

    @property
    def allowed_email_set(self) -> set[str]:
        # Commas, semicolons or spaces: gcloud --set-env-vars already uses commas between variables.
        return {e.lower() for e in re.split(r"[,;\s]+", self.allowed_emails) if e}

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{Path(self.sqlite_path).as_posix()}"

    @property
    def ai_is_live(self) -> bool:
        return (not self.mock_ai) and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
