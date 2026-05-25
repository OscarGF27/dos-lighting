from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.application.chat_message_result import ChatMessageResult
from app.backend_client import BackendClient
from app.chat_service import (
    ChatProcessingError,
    ChatService,
    ChatServiceUnavailable,
)
from app.config import Settings, get_settings
from app.openai_client import OpenAIResponsesClient
from app.ports import HandleChatMessageUseCase
from app.rate_limiter import RateLimitExceeded, RateLimiter
from app.schemas import ChatMessageRequest, ChatMessageResponse, HealthResponse
from app.session_store import SessionStore
from app.tools import ToolRunner


def map_chat_result_to_response(
    result: ChatMessageResult | dict[str, Any],
) -> ChatMessageResponse:
    if isinstance(result, ChatMessageResult):
        return ChatMessageResponse.model_validate(
            {
                "session_id": result.session_id,
                "reply_text": result.reply_text,
                "quick_replies": result.quick_replies,
                "missing_fields": result.missing_fields,
                "recommendation": result.recommendation,
                "reset_session": result.reset_session,
            }
        )

    if isinstance(result, dict):
        return ChatMessageResponse.model_validate(result)

    raise ChatProcessingError(
        "El servicio de chat devolvio un formato de respuesta no valido."
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    current_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        backend_client = BackendClient(current_settings.backend_api_base_url)
        tool_runner = ToolRunner(backend_client)
        openai_client = None

        if current_settings.openai_configured:
            openai_client = OpenAIResponsesClient(
                api_key=current_settings.openai_api_key or "",
                model=current_settings.openai_model,
            )

        app.state.chat_service = ChatService(
            openai_client=openai_client,
            tool_runner=tool_runner,
            session_store=SessionStore(
                ttl_minutes=current_settings.chat_session_ttl_minutes
            ),
            rate_limiter=RateLimiter(
                max_requests=current_settings.chat_rate_limit_requests,
                window_seconds=current_settings.chat_rate_limit_window_seconds,
            ),
            max_tool_rounds=current_settings.chat_max_tool_rounds,
        )
        app.state.backend_client = backend_client
        app.state.openai_client = openai_client
        app.state.settings = current_settings
        try:
            yield
        finally:
            await backend_client.aclose()
            if openai_client is not None:
                await openai_client.aclose()

    app = FastAPI(
        title="DOS Lighting Chatbot",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"message": "Solicitud invalida.", "details": details},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        _request: Request, exc: HTTPException
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            payload = detail
        else:
            payload = {"message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content=payload)

    def get_chat_service(request: Request) -> HandleChatMessageUseCase:
        return request.app.state.chat_service

    @app.get("/api/chat/health", response_model=HealthResponse)
    async def chat_health(request: Request) -> HealthResponse:
        backend_reachable = await request.app.state.backend_client.healthcheck()
        settings_from_app: Settings = request.app.state.settings
        status = "UP" if backend_reachable and settings_from_app.openai_configured else "DEGRADED"
        return HealthResponse(
            status=status,
            openaiConfigured=settings_from_app.openai_configured,
            backendReachable=backend_reachable,
        )

    @app.post("/api/chat/message", response_model=ChatMessageResponse)
    async def chat_message(
        payload: ChatMessageRequest,
        request: Request,
        chat_service: HandleChatMessageUseCase = Depends(get_chat_service),
    ) -> ChatMessageResponse:
        client_host = request.client.host if request.client else "anonymous"
        try:
            result = await chat_service.handle_message(
                session_id=payload.session_id,
                user_message=payload.message,
                client_key=client_host,
            )
            return map_chat_result_to_response(result)
        except ChatServiceUnavailable as error:
            raise HTTPException(status_code=503, detail={"message": str(error)}) from error
        except RateLimitExceeded as error:
            raise HTTPException(status_code=429, detail={"message": str(error)}) from error
        except ChatProcessingError as error:
            raise HTTPException(status_code=502, detail={"message": str(error)}) from error

    return app


app = create_app()
