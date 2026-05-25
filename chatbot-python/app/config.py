from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.4-mini", alias="OPENAI_MODEL")
    chatbot_port: int = Field(default=8001, alias="CHATBOT_PORT")
    backend_api_base_url: str = Field(
        default="http://localhost:8080", alias="BACKEND_API_BASE_URL"
    )
    chat_session_ttl_minutes: int = Field(default=30, alias="CHAT_SESSION_TTL_MINUTES")
    chat_rate_limit_requests: int = Field(default=20, alias="CHAT_RATE_LIMIT_REQUESTS")
    chat_rate_limit_window_seconds: int = Field(
        default=60, alias="CHAT_RATE_LIMIT_WINDOW_SECONDS"
    )
    chat_max_tool_rounds: int = Field(default=6, alias="CHAT_MAX_TOOL_ROUNDS")

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def session_ttl_seconds(self) -> int:
        return self.chat_session_ttl_minutes * 60

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
