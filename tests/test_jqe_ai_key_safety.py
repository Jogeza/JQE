from __future__ import annotations

import importlib
import logging
from datetime import datetime, timezone

import pytest

import api.assistant as assistant_api
import jqe_ai.client as client_module
from api.app import create_app
from config.settings import Settings
from jqe_ai.client import ProviderResult
from jqe_ai.models import ContextItem, GlossaryBundle
from jqe_ai.prompt import SYSTEM_PROMPT
from jqe_ai.service import AssistantUnavailable, JQEAIService


KEY = "key-that-must-never-be-serialized-or-logged"
NOW = datetime(2026, 9, 21, tzinfo=timezone.utc)


class Reader:
    def read(self):
        names = (
            "broker_status", "execution_safety", "risk", "offline_monitoring",
            "observation_health", "watchlist", "watchlist_cap_usage",
        )
        return [ContextItem(
            name=name, source=name, stale=False, available=True,
            data={"reason_codes": ["NO_TRADE"]},
        ) for name in names], GlossaryBundle(version="v1", items=[])


def safe_settings(**changes):
    values = {
        "anthropic_api_key": KEY,
        "ai_assistant_enabled": True,
        "ai_assistant_kill_switch": False,
    }
    values.update(changes)
    return Settings(_env_file=None, **values)


def test_key_is_excluded_and_fail_closed_defaults_are_explicit():
    configured = safe_settings()
    assert configured.anthropic_api_key == KEY
    assert KEY not in repr(configured)
    assert "anthropic_api_key" not in configured.model_dump()
    assert KEY not in configured.model_dump_json()

    defaults = Settings(
        _env_file=None, anthropic_api_key=None,
        ai_assistant_enabled=False, ai_assistant_kill_switch=True,
    )
    assert defaults.ai_assistant_enabled is False
    assert defaults.ai_assistant_kill_switch is True


@pytest.mark.asyncio
async def test_key_never_appears_in_prompt_responses_exceptions_or_logs(caplog):
    class CapturingClient:
        async def answer(self, **kwargs):
            assert KEY not in kwargs["system"]
            assert KEY not in kwargs["context"]
            assert KEY not in kwargs["message"]
            raise RuntimeError(f"provider rejected {KEY}")

    service = JQEAIService(
        settings=safe_settings(), projection_reader=Reader(),
        client=CapturingClient(), clock=lambda: NOW,
    )
    caplog.set_level(logging.DEBUG)
    assert KEY not in SYSTEM_PROMPT
    assert KEY not in service.status().model_dump_json()
    with pytest.raises(AssistantUnavailable) as caught:
        await service.chat("Explain")
    assert KEY not in caught.value.user_message
    assert KEY not in str(caught.value)
    assert KEY not in caplog.text


def test_backend_and_status_load_when_anthropic_import_is_unavailable(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)
    importlib.reload(client_module)
    app = create_app()
    assert app is not None
    monkeypatch.setattr(assistant_api, "settings", safe_settings())
    status = assistant_api.get_assistant_status()
    assert status.state == "READY"
    assert KEY not in status.model_dump_json()


@pytest.mark.asyncio
async def test_successful_chat_response_never_contains_key():
    class SuccessfulClient:
        async def answer(self, **kwargs):
            return ProviderResult("Evidence is available.", 1, 1, "end_turn")

    response = await JQEAIService(
        settings=safe_settings(), projection_reader=Reader(),
        client=SuccessfulClient(), clock=lambda: NOW,
    ).chat("Explain")
    assert KEY not in response.model_dump_json()
