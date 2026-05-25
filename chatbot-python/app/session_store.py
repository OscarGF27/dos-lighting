from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from app.domain.conversation import ChatSession, SessionMessage


class SessionStore:
    def __init__(
        self,
        ttl_minutes: int,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._sessions: dict[str, ChatSession] = {}
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return self._now_provider()

    def _expires_at(self) -> datetime:
        return self._now() + self._ttl

    def _is_expired(self, session: ChatSession) -> bool:
        return session.expires_at <= self._now()

    def cleanup_expired(self) -> None:
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if self._is_expired(session)
        ]
        for session_id in expired_ids:
            self._sessions.pop(session_id, None)

    def get_or_create(self, session_id: str | None) -> tuple[ChatSession, bool]:
        self.cleanup_expired()

        if session_id:
            current = self._sessions.get(session_id)
            if current and not self._is_expired(current):
                current.expires_at = self._expires_at()
                return current, False

        new_session = ChatSession(
            session_id=str(uuid4()),
            expires_at=self._expires_at(),
        )
        self._sessions[new_session.session_id] = new_session
        return new_session, bool(session_id)

    def append_turn(
        self, session: ChatSession, user_message: str, assistant_message: str
    ) -> None:
        session.history.append(SessionMessage(role="user", content=user_message))
        session.history.append(SessionMessage(role="assistant", content=assistant_message))
        session.expires_at = self._expires_at()

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
