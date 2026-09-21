from __future__ import annotations

import pytest
from fastapi import HTTPException, Request

import api.assistant as assistant_api
from jqe_ai.models import AssistantChatRequest, AssistantChatResponse, AssistantStatusResponse
from jqe_ai.service import AssistantUnavailable


class FakeService:
    def status(self):
        return AssistantStatusResponse(
            state="READY", configured=True, enabled=True, healthy=True,
            model="claude-haiku-4-5-20251001",
        )

    async def chat(self, message, *, client_key):
        assert message == "Explain NO_TRADE"
        assert client_key
        return AssistantChatResponse(
            state="ANSWERED", answer="The canonical assessment is NO_TRADE.",
            generated_at="2026-09-21T00:00:00+00:00", model="claude-haiku-4-5-20251001",
        )


def request():
    return Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})


def test_status_reports_locally_ready_not_connected(monkeypatch):
    monkeypatch.setattr(assistant_api, "get_assistant_service", lambda: FakeService())
    response = assistant_api.get_assistant_status()
    assert response.state == "READY"
    assert "connected" not in response.model_dump_json().lower()


@pytest.mark.asyncio
async def test_chat_is_single_user_initiated_post(monkeypatch):
    monkeypatch.setattr(assistant_api, "get_assistant_service", lambda: FakeService())
    response = await assistant_api.chat_with_assistant(
        AssistantChatRequest(message="Explain NO_TRADE"), request(),
    )
    assert response.state == "ANSWERED"


@pytest.mark.asyncio
async def test_auth_failure_has_distinct_unavailable_message(monkeypatch):
    class Failed(FakeService):
        async def chat(self, message, *, client_key):
            raise AssistantUnavailable(
                "ANTHROPIC_AUTH_FAILED", "JQE AI is unavailable — Anthropic authentication failed.",
            )

    monkeypatch.setattr(assistant_api, "get_assistant_service", lambda: Failed())
    with pytest.raises(HTTPException) as caught:
        await assistant_api.chat_with_assistant(
            AssistantChatRequest(message="Explain NO_TRADE"), request(),
        )
    assert caught.value.status_code == 503
    assert caught.value.detail["reason_code"] == "ANTHROPIC_AUTH_FAILED"
    assert caught.value.detail["message"] == "JQE AI is unavailable — Anthropic authentication failed."
