from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessageResult:
    session_id: str
    reply_text: str
    quick_replies: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    recommendation: dict[str, Any] | None = None
    reset_session: bool = False

