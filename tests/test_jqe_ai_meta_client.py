"""Tests for MetaModelClient and Meta Model API routing in JQEAIService."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from config.settings import Settings
from jqe_ai.client import MetaModelClient, ProviderResult
from jqe_ai.models import ContextItem, GlossaryBundle
from jqe_ai.service import AssistantUnavailable, JQEAIService


META_KEY = "meta-test-secret-key-12345"


class MockUrllibResponse:
    def __init__(self, data: dict, status: int = 200) -> None:
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> MockUrllibResponse:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


class StubReader:
    def read(self):
        names = (
            "broker_status", "execution_safety", "risk", "offline_monitoring",
            "observation_health", "watchlist", "watchlist_cap_usage",
        )
        return [
            ContextItem(
                name=name, source=f"GET /api/v1/{name}", observed_at=None,
                age_seconds=None, stale=False, available=True,
                data={"reason_codes": ["NO_TRADE"], "count": 1},
            )
            for name in names
        ], GlossaryBundle(version="v1", items=[])


@pytest.mark.asyncio
async def test_meta_client_sends_openai_compatible_payload() -> None:
    client = MetaModelClient(
        api_key=META_KEY,
        model="llama-3.3-70b-instruct",
        api_base="https://api.llama.com/v1",
        max_tokens=256,
        timeout=5.0,
    )

    captured_request = {}

    def mock_urlopen(req, timeout=None):
        captured_request["url"] = req.full_url
        captured_request["headers"] = dict(req.headers)
        captured_request["body"] = json.loads(req.data.decode("utf-8"))
        return MockUrllibResponse({
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Deterministic explanation"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 15},
        })

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        result = await client.answer(
            system="System rules here",
            context="Telemetry evidence",
            message="Why was trade blocked?",
        )

    assert result.text == "Deterministic explanation"
    assert result.input_tokens == 120
    assert result.output_tokens == 15
    assert result.stop_reason == "end_turn"

    assert captured_request["url"] == "https://api.llama.com/v1/chat/completions"
    assert captured_request["headers"]["Authorization"] == f"Bearer {META_KEY}"
    assert captured_request["body"]["model"] == "llama-3.3-70b-instruct"
    assert captured_request["body"]["max_tokens"] == 256
    messages = captured_request["body"]["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "System rules here"
    assert "<workspace_context>Telemetry evidence</workspace_context>" in messages[1]["content"]
    assert "<user_question>Why was trade blocked?</user_question>" in messages[1]["content"]


@pytest.mark.asyncio
async def test_meta_client_sanitizes_errors_never_leaking_key() -> None:
    import urllib.error

    client = MetaModelClient(
        api_key=META_KEY,
        model="llama-3.3-70b-instruct",
        timeout=5.0,
    )

    def mock_fail(req, timeout=None):
        fp = MagicMock()
        fp.read.return_value = b'{"error": "Unauthorized"}'
        raise urllib.error.HTTPError(
            url="https://api.llama.com/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=fp,
        )

    with patch("urllib.request.urlopen", side_effect=mock_fail):
        with pytest.raises(RuntimeError) as exc_info:
            await client.answer(system="sys", context="ctx", message="msg")

        err_msg = str(exc_info.value)
        assert META_KEY not in err_msg
        assert "401" in err_msg


def test_meta_provider_status_reporting() -> None:
    # Unconfigured
    unconf_settings = Settings(
        _env_file=None,
        ai_assistant_provider="meta",
        meta_api_key=None,
        ai_assistant_enabled=True,
        ai_assistant_kill_switch=False,
    )
    svc = JQEAIService(settings=unconf_settings, projection_reader=StubReader())
    st = svc.status()
    assert st.state == "UNCONFIGURED"
    assert "META_API_KEY_MISSING" in st.reason_codes

    # Ready
    ready_settings = Settings(
        _env_file=None,
        ai_assistant_provider="meta",
        meta_api_key=META_KEY,
        ai_assistant_enabled=True,
        ai_assistant_kill_switch=False,
        ai_assistant_model="llama-3.3-70b-instruct",
    )
    svc_ready = JQEAIService(settings=ready_settings, projection_reader=StubReader())
    st_ready = svc_ready.status()
    assert st_ready.state == "READY"
    assert st_ready.healthy is True
    assert st_ready.model == "llama-3.3-70b-instruct"
    assert st_ready.provider == "meta"


@pytest.mark.asyncio
async def test_meta_provider_chat_maps_auth_error_sanitized() -> None:
    settings = Settings(
        _env_file=None,
        ai_assistant_provider="meta",
        meta_api_key=META_KEY,
        ai_assistant_enabled=True,
        ai_assistant_kill_switch=False,
    )

    class FailingClient:
        async def answer(self, **kwargs):
            raise RuntimeError("HTTP 401: Unauthorized")

    svc = JQEAIService(settings=settings, projection_reader=StubReader(), client=FailingClient())
    with pytest.raises(AssistantUnavailable) as exc_info:
        await svc.chat("Why?")

    assert exc_info.value.code == "META_AUTH_FAILED"
    assert META_KEY not in str(exc_info.value)
    assert META_KEY not in exc_info.value.user_message


@pytest.mark.asyncio
async def test_meta_provider_chat_successful_response() -> None:
    settings = Settings(
        _env_file=None,
        ai_assistant_provider="meta",
        meta_api_key=META_KEY,
        ai_assistant_enabled=True,
        ai_assistant_kill_switch=False,
        ai_assistant_model="llama-3.3-70b-instruct",
    )

    class SuccessfulClient:
        async def answer(self, **kwargs):
            return ProviderResult(
                text="The strategy indicates NO_TRADE due to high volatility count 1.",
                input_tokens=150,
                output_tokens=20,
                stop_reason="end_turn",
            )

    svc = JQEAIService(settings=settings, projection_reader=StubReader(), client=SuccessfulClient())
    resp = await svc.chat("Status?")
    assert resp.state == "ANSWERED"
    assert resp.provider == "meta"
    assert resp.model == "llama-3.3-70b-instruct"
    assert "NO_TRADE" in resp.answer
