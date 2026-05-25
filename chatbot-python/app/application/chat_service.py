from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.application.fallback_assistant import FallbackAssistant
from app.application.chat_message_result import ChatMessageResult
from app.domain.errors import LlmServiceError
from app.ports import LlmClient, RateLimiterPort, SessionRepository, ToolExecutor
from app.prompts import STARTER_QUICK_REPLIES, SYSTEM_PROMPT, build_session_snapshot
from app.rate_limiter import RateLimitExceeded
from app.domain.conversation import ChatSession, SessionMetadata
from app.domain.tooling import ToolContextUpdate


class ChatServiceUnavailable(Exception):
    pass


class ChatProcessingError(Exception):
    pass


class ModelClientProtocol(LlmClient, Protocol):
    pass


@dataclass
class PendingFunctionCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


class ChatService:
    def __init__(
        self,
        *,
        openai_client: LlmClient | None,
        tool_runner: ToolExecutor,
        session_store: SessionRepository,
        rate_limiter: RateLimiterPort,
        max_tool_rounds: int,
    ) -> None:
        self._openai_client = openai_client
        self._tool_runner = tool_runner
        self._session_store = session_store
        self._rate_limiter = rate_limiter
        self._max_tool_rounds = max_tool_rounds
        self._fallback_assistant = FallbackAssistant(tool_runner)

    async def handle_message(
        self,
        *,
        session_id: str | None,
        user_message: str,
        client_key: str,
    ) -> ChatMessageResult:
        self._rate_limiter.check(client_key)
        session, reset_session = self._session_store.get_or_create(session_id)

        if self._openai_client is None:
            return await self._handle_fallback_response(
                session=session,
                user_message=user_message,
                reset_session=reset_session,
            )

        input_items = self._build_input_items(session, user_message)
        context_update = ToolContextUpdate()

        try:
            response = await self._openai_client.create_response(
                input_items=input_items, tools=self._tool_runner.definitions
            )
            for _ in range(self._max_tool_rounds):
                function_calls = self._extract_function_calls(response)
                if not function_calls:
                    break

                input_items.extend(self._sanitize_output_items(response))

                for function_call in function_calls:
                    result = await self._tool_runner.execute(
                        function_call.name, function_call.arguments
                    )
                    self._merge_context_update(context_update, result.context)
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": function_call.call_id,
                            "output": result.output_text,
                        }
                    )

                response = await self._openai_client.create_response(
                    input_items=input_items, tools=self._tool_runner.definitions
                )
            else:
                raise ChatProcessingError(
                    "El chatbot excedio el numero maximo de herramientas en este turno."
                )
        except RateLimitExceeded:
            raise
        except ChatProcessingError:
            raise
        except LlmServiceError:
            return await self._handle_fallback_response(
                session=session,
                user_message=user_message,
                reset_session=reset_session,
            )
        except Exception as error:
            raise ChatProcessingError(
                "No se pudo completar la conversacion del chatbot."
            ) from error

        reply_text = self._extract_reply_text(response).strip()
        if not reply_text:
            reply_text = self._build_fallback_reply(context_update)

        self._session_store.append_turn(session, user_message, reply_text)
        self._merge_session_metadata(session.metadata, context_update)

        quick_replies = self._build_quick_replies(session, context_update)
        return ChatMessageResult(
            session_id=session.session_id,
            reply_text=reply_text,
            quick_replies=quick_replies,
            missing_fields=context_update.last_missing_fields
            or session.metadata.last_missing_fields,
            recommendation=context_update.last_recommendation,
            reset_session=reset_session,
        )

    async def _handle_fallback_response(
        self,
        *,
        session: ChatSession,
        user_message: str,
        reset_session: bool,
    ) -> ChatMessageResult:
        fallback = await self._fallback_assistant.respond(session, user_message)
        reply_text = fallback.reply_text.strip() or "Listo, sigamos con la recomendacion."

        self._session_store.append_turn(session, user_message, reply_text)
        self._merge_session_metadata(session.metadata, fallback.context_update)

        return ChatMessageResult(
            session_id=session.session_id,
            reply_text=reply_text,
            quick_replies=fallback.quick_replies or STARTER_QUICK_REPLIES,
            missing_fields=fallback.context_update.last_missing_fields
            or session.metadata.last_missing_fields,
            recommendation=fallback.context_update.last_recommendation,
            reset_session=reset_session,
        )

    def _build_input_items(
        self, session: ChatSession, user_message: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": build_session_snapshot(session.metadata.to_prompt_payload()),
            },
        ]

        for message in session.history[-12:]:
            items.append({"role": message.role, "content": message.content})

        items.append({"role": "user", "content": user_message})
        return items

    def _extract_function_calls(self, response: Any) -> list[PendingFunctionCall]:
        output_items = getattr(response, "output", []) or []
        function_calls: list[PendingFunctionCall] = []

        for item in output_items:
            item_type = self._read_attr(item, "type")
            if item_type != "function_call":
                continue

            raw_arguments = self._read_attr(item, "arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}

            function_calls.append(
                PendingFunctionCall(
                    call_id=str(self._read_attr(item, "call_id")),
                    name=str(self._read_attr(item, "name")),
                    arguments=arguments,
                )
            )

        return function_calls

    def _sanitize_output_items(self, response: Any) -> list[dict[str, Any]]:
        sanitized: list[dict[str, Any]] = []
        for item in getattr(response, "output", []) or []:
            if hasattr(item, "model_dump"):
                raw = item.model_dump(exclude_none=True)
            elif isinstance(item, dict):
                raw = dict(item)
            else:
                raw = dict(getattr(item, "__dict__", {}))
            raw.pop("id", None)
            sanitized.append(raw)
        return sanitized

    def _extract_reply_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if output_text:
            return str(output_text)

        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            if self._read_attr(item, "type") != "message":
                continue

            for content in self._read_attr(item, "content") or []:
                content_type = self._read_attr(content, "type")
                if content_type in {"output_text", "text"}:
                    text_value = self._read_attr(content, "text")
                    if isinstance(text_value, dict):
                        text_value = text_value.get("value")
                    if text_value:
                        chunks.append(str(text_value))

        return "\n".join(chunks).strip()

    def _merge_context_update(
        self, current: ToolContextUpdate, new: ToolContextUpdate
    ) -> None:
        current.known_values.update(new.known_values)
        current.catalogs_loaded = current.catalogs_loaded or new.catalogs_loaded
        if new.last_missing_fields:
            current.last_missing_fields = list(new.last_missing_fields)
        if new.last_recommendation is not None:
            current.last_recommendation = new.last_recommendation
            current.last_missing_fields = []

    def _merge_session_metadata(
        self, metadata: SessionMetadata, context_update: ToolContextUpdate
    ) -> None:
        metadata.known_values.update(context_update.known_values)
        metadata.catalogs_loaded = metadata.catalogs_loaded or context_update.catalogs_loaded
        if context_update.last_recommendation is not None:
            metadata.last_recommendation = context_update.last_recommendation
            metadata.last_missing_fields = []
        elif context_update.last_missing_fields:
            metadata.last_missing_fields = list(context_update.last_missing_fields)

    def _build_quick_replies(
        self, session: ChatSession, context_update: ToolContextUpdate
    ) -> list[str]:
        if len(session.history) <= 2:
            return STARTER_QUICK_REPLIES

        if context_update.last_recommendation is not None:
            return [
                "Que significa el nivel de confianza?",
                "Cual producto top me conviene mas?",
                "Que diferencia hay entre gama media y premium?",
            ]

        return []

    def _build_fallback_reply(self, context_update: ToolContextUpdate) -> str:
        if context_update.last_recommendation is not None:
            return "Ya tengo una recomendacion lista para tu vehiculo."
        if context_update.last_missing_fields:
            return "Necesito un dato adicional para continuar con la recomendacion."
        return "Listo, continuemos con el siguiente paso."

    @staticmethod
    def _read_attr(value: Any, name: str) -> Any:
        if isinstance(value, dict):
            return value.get(name)
        return getattr(value, name, None)
