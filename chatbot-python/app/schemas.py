from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageRequest(BaseModel):
    session_id: str | None = Field(default=None, alias="sessionId")
    message: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(populate_by_name=True)


class ChatMessageResponse(BaseModel):
    session_id: str = Field(alias="sessionId")
    reply_text: str = Field(alias="replyText")
    quick_replies: list[str] = Field(default_factory=list, alias="quickReplies")
    missing_fields: list[str] = Field(default_factory=list, alias="missingFields")
    recommendation: dict[str, Any] | None = None
    reset_session: bool = Field(default=False, alias="resetSession")

    model_config = ConfigDict(populate_by_name=True)


class HealthResponse(BaseModel):
    status: str
    openai_configured: bool = Field(alias="openaiConfigured")
    backend_reachable: bool = Field(alias="backendReachable")

    model_config = ConfigDict(populate_by_name=True)
