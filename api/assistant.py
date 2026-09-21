"""HTTP boundary for the read-only, stateless JQE AI assistant."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.workspace_projection_reader import WorkspaceProjectionReader
from config.settings import settings
from jqe_ai.models import AssistantChatRequest, AssistantChatResponse, AssistantStatusResponse
from jqe_ai.service import AssistantUnavailable, InMemoryRateLimiter, JQEAIService

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"])
_rate_limiter = InMemoryRateLimiter(
    settings.ai_assistant_requests_per_minute,
    settings.ai_assistant_daily_request_limit,
)


def get_assistant_service() -> JQEAIService:
    return JQEAIService(
        settings=settings,
        projection_reader=WorkspaceProjectionReader(settings),
        limiter=_rate_limiter,
    )


@router.get("/status", response_model=AssistantStatusResponse)
def get_assistant_status() -> AssistantStatusResponse:
    return get_assistant_service().status()


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(payload: AssistantChatRequest, request: Request) -> AssistantChatResponse:
    client_key = request.client.host if request.client else "local"
    try:
        return await get_assistant_service().chat(payload.message, client_key=client_key)
    except AssistantUnavailable as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"state": "UNAVAILABLE", "answer": None, "reason_code": exc.code, "message": exc.user_message},
        ) from exc
