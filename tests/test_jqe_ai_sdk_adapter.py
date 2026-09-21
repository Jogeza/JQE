from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx2
import pytest

from jqe_ai.client import AnthropicModelClient
from jqe_ai.models import ContextItem, GlossaryBundle
from jqe_ai.prompt import SYSTEM_PROMPT
from jqe_ai.service import AssistantUnavailable, JQEAIService


KEY = "sdk-test-key-that-must-not-leak"
NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


def settings():
    return SimpleNamespace(
        anthropic_api_key=KEY, ai_assistant_enabled=True,
        ai_assistant_kill_switch=False, ai_assistant_model="claude-haiku-4-5-20251001",
        ai_assistant_max_output_tokens=512, ai_assistant_timeout_seconds=12,
        ai_assistant_max_message_chars=1000, ai_assistant_max_context_bytes=32768,
        ai_assistant_requests_per_minute=6, ai_assistant_daily_request_limit=100,
    )


class Reader:
    def read(self):
        names = (
            "broker_status", "execution_safety", "risk", "offline_monitoring",
            "observation_health", "watchlist", "watchlist_cap_usage",
        )
        return [ContextItem(
            name=name, source=f"GET /api/v1/{name}", observed_at=NOW.isoformat(),
            age_seconds=0, stale=False, available=True, data={"reason_codes": ["NO_TRADE"]},
        ) for name in names], GlossaryBundle(version="v1", items=[])


def response(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, request=request, json={
        "id": "msg_test", "type": "message", "role": "assistant",
        "content": [{"type": "text", "text": "The canonical assessment is NO_TRADE."}],
        "model": "claude-haiku-4-5-20251001", "stop_reason": "end_turn",
        "stop_sequence": None, "usage": {"input_tokens": 20, "output_tokens": 8},
    })


def client(handler) -> AnthropicModelClient:
    transport = httpx2.MockTransport(handler)
    http_client = httpx2.AsyncClient(transport=transport)
    return AnthropicModelClient(
        api_key=KEY, model="claude-haiku-4-5-20251001", max_tokens=512,
        timeout=12, http_client=http_client,
    )


@pytest.mark.asyncio
async def test_real_sdk_sends_exact_tool_free_single_turn_request():
    captured = []

    async def handler(request):
        captured.append(request)
        return response(request)

    adapter = client(handler)
    result = await adapter.answer(system=SYSTEM_PROMPT, context='{"safe":true}', message="Explain NO_TRADE")
    assert result.text == "The canonical assessment is NO_TRADE."
    assert len(captured) == 1
    request = captured[0]
    body = json.loads(request.content)
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["max_tokens"] == 512
    assert body["system"] == SYSTEM_PROMPT
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert "<workspace_context>" in body["messages"][0]["content"]
    assert "<user_question>Explain NO_TRADE</user_question>" in body["messages"][0]["content"]
    assert "tools" not in body
    assert "tool_choice" not in body
    assert "thinking" not in body
    assert request.headers["x-api-key"] == KEY
    assert KEY.encode() not in request.content


@pytest.mark.parametrize(("status", "code", "http_status"), [
    (401, "ANTHROPIC_AUTH_FAILED", 503),
    (429, "ANTHROPIC_RATE_LIMITED", 429),
    (500, "ANTHROPIC_STATUS_ERROR", 503),
])
@pytest.mark.asyncio
async def test_real_sdk_status_errors_map_without_partial_text(status, code, http_status):
    async def handler(request):
        return httpx2.Response(status, request=request, json={"type": "error", "error": {"type": "test_error", "message": "provider detail"}})

    service = JQEAIService(settings=settings(), projection_reader=Reader(), client=client(handler), clock=lambda: NOW)
    with pytest.raises(AssistantUnavailable) as caught:
        await service.chat("Explain")
    assert caught.value.code == code
    assert caught.value.status_code == http_status
    assert "provider detail" not in caught.value.user_message


@pytest.mark.parametrize(("transport_error", "code", "http_status"), [
    (httpx2.ReadTimeout("slow"), "ASSISTANT_TIMEOUT", 504),
    (httpx2.ConnectError("offline"), "ANTHROPIC_CONNECTION_ERROR", 503),
])
@pytest.mark.asyncio
async def test_real_sdk_transport_errors_map_without_partial_text(transport_error, code, http_status):
    async def handler(request):
        transport_error.request = request
        raise transport_error

    service = JQEAIService(settings=settings(), projection_reader=Reader(), client=client(handler), clock=lambda: NOW)
    with pytest.raises(AssistantUnavailable) as caught:
        await service.chat("Explain")
    assert caught.value.code == code
    assert caught.value.status_code == http_status
    assert caught.value.user_message.endswith("No answer was generated.")
