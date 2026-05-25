from __future__ import annotations

from typing import Any, Protocol

from app.application.chat_message_result import ChatMessageResult
from app.domain.conversation import ChatSession
from app.domain.tooling import ToolResult


class LlmClient(Protocol):
    async def create_response(
        self, *, input_items: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Any: ...


class SessionRepository(Protocol):
    def get_or_create(self, session_id: str | None) -> tuple[ChatSession, bool]: ...

    def append_turn(
        self, session: ChatSession, user_message: str, assistant_message: str
    ) -> None: ...


class RateLimiterPort(Protocol):
    def check(self, client_key: str) -> None: ...


class BackendCatalogClient(Protocol):
    async def get_survey_catalogs(self) -> dict[str, Any]: ...

    async def get_optical_system_decision(
        self, modelo_id: int, anio_vehiculo: int
    ) -> dict[str, Any]: ...

    async def resolve_led_recommendation(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def get_gamas_luz(self) -> dict[str, Any]: ...

    async def get_product_detail(self, producto_id: int) -> dict[str, Any]: ...


class ToolExecutor(Protocol):
    @property
    def definitions(self) -> list[dict[str, Any]]: ...

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...


class HandleChatMessageUseCase(Protocol):
    async def handle_message(
        self, *, session_id: str | None, user_message: str, client_key: str
    ) -> ChatMessageResult: ...
