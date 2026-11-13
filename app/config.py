"""Application settings loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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

    @property
    def sqlite_url(self) -> str:
        return f"sqlite:///{Path(self.sqlite_path).as_posix()}"

    @property
    def ai_is_live(self) -> bool:
        return (not self.mock_ai) and bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
