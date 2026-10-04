"""Offline-only signal formatter and optional channel delivery tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from notifications.signal_formatter import render_signal_alert
from notifications.telegram_channel import (
    TelegramChannelConfig, TelegramChannelGateway, telegram_channel_from_settings,
)
from notifications.types import Notification, NotificationType
from notifications import telegram_channel as channel_module


DATE = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


def _opened(side="BUY", *, targets=True, symbol="FX Vol <60> & Co"):
    facts = {
        "Symbol": symbol, "Timeframe": "M5", "Side": side,
        "Entry": "123.45", "Stop loss": "120.00", "Quantity": "0.01",
        "Risk at stop %": "0.500", "Account mode": "DEMO",
    }
    if targets:
        facts.update({"TP1": "130.00", "TP2": "135.00"})
    return Notification(NotificationType.POSITION_OPENED, "opened", facts,
                        occurred_at=DATE, event_id="OPEN:ticket-1")


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("targets", [True, False])
def test_opened_formatter_uses_only_factual_targets_and_escapes(side, targets):
    text = render_signal_alert(_opened(side, targets=targets))
    assert text.startswith("JQE ✨ Demo trade opened | 28 SEP 2026 | DEMO ACCOUNT")
    assert "BROKER: Weltrade" in text
    assert "ASSET: FX Vol &lt;60&gt; &amp; Co M5" in text
    assert f"ACTION | DIRECTION: {side}" in text
    assert "ENTRY PRICE: 123.45" in text
    assert "STOP LOSS: 120.00" in text
    assert "VOLUME: 0.01" in text
    assert "RISK AT PLANNED STOP: 0.500%" in text
    assert ("TP1: 130.00" in text) is targets
    assert ("TP2: 135.00" in text) is targets
    assert "TP3:" not in text and "TP4:" not in text
    assert "<60>" not in text
    assert "Watching the setup with you 👀 Demo update; outcomes aren't guaranteed." in text
    assert "http" not in text.lower() and "+256" not in text


def test_closed_and_rejected_formatter_have_result_and_reason():
    closed = Notification(NotificationType.POSITION_CLOSED, "closed", {
        "Symbol": "PainX 800", "Timeframe": "M1", "Side": "SELL",
        "Result": "+1.2 USD", "Reason": "Stop moved & hit",
        "Account mode": "DEMO",
    }, occurred_at=DATE, event_id="CLOSE:ticket-1")
    rendered = render_signal_alert(closed)
    assert "JQE 📝 Trade wrapped up | 28 SEP 2026 | DEMO ACCOUNT" in rendered
    assert "RESULT: +1.2 USD" in rendered
    assert "REASON: Stop moved &amp; hit" in rendered
    assert "TP1:" not in rendered
    rejected = Notification(NotificationType.ORDER_REJECTED, "rejected", {
        "Symbol": "FX Vol 20", "Timeframe": "M5", "Reason": "Risk &lt; minimum",
        "Account mode": "DEMO",
    }, occurred_at=DATE, event_id="REJECT:intent-1")
    assert "JQE 🛑 Sitting this one out" in render_signal_alert(rejected)
    assert "REASON: Risk &amp;lt; minimum" in render_signal_alert(rejected)


def _config(tmp_path, chat_id="-100123456789"):
    return TelegramChannelConfig("test-secret-token", chat_id,
                                 tmp_path / "claims.sqlite3", timeout_seconds=1)


def test_channel_config_repr_redacts_destination_and_token(tmp_path):
    rendered = repr(_config(tmp_path))
    assert "test-secret-token" not in rendered
    assert "-100123456789" not in rendered


@pytest.mark.asyncio
async def test_channel_flag_off_and_shared_env_cannot_arm(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, telegram_channel_enabled=True,
                        telegram_channel_chat_id="-100123456789",
                        telegram_bot_token="test-secret-token",
                        telegram_channel_claim_store_path=tmp_path / "claims.sqlite3")
    monkeypatch.delenv("JQE_TELEGRAM_CHANNEL_ENABLED", raising=False)
    assert telegram_channel_from_settings(settings) is None
    monkeypatch.setenv("JQE_TELEGRAM_CHANNEL_ENABLED", "true")
    channel = telegram_channel_from_settings(settings)
    assert channel is not None
    assert telegram_channel_from_settings(settings) is channel
    disabled = settings.model_copy(update={"telegram_channel_enabled": False})
    assert telegram_channel_from_settings(disabled) is None


@pytest.mark.asyncio
async def test_channel_sends_once_per_event_and_destination(tmp_path):
    post = AsyncMock()
    sleep = AsyncMock()
    first = TelegramChannelGateway(_config(tmp_path), post=post, sleep=sleep)
    event = _opened()
    await first.send(event)
    await first.send(event)
    await first.drain()
    assert post.await_count == 1
    _, payload, _ = post.await_args.args
    assert json.loads(payload)["chat_id"] == "-100123456789"
    assert "JQE ✨ Demo trade opened" in json.loads(payload)["text"]
    retry = TelegramChannelGateway(_config(tmp_path), post=post, sleep=sleep)
    await retry.send(event)
    await retry.drain()
    assert post.await_count == 1
    second = TelegramChannelGateway(_config(tmp_path, "@example_channel"), post=post, sleep=sleep)
    await second.send(event)
    await second.drain()
    assert post.await_count == 2


@pytest.mark.asyncio
async def test_closed_and_rejected_events_require_stable_id(tmp_path):
    post = AsyncMock()
    channel = TelegramChannelGateway(_config(tmp_path), post=post, sleep=AsyncMock())
    without_id = Notification(NotificationType.ORDER_REJECTED, "rejected",
                              {"Reason": "BROKER_REJECTED"}, occurred_at=DATE)
    assert await channel.send(without_id) is False
    closed = Notification(NotificationType.POSITION_CLOSED, "closed", {
        "Symbol": "PainX 800", "Result": "+1.2 USD", "Reason": "Target reached",
        "Account mode": "DEMO",
    }, occurred_at=DATE, event_id="CLOSE:ticket-1")
    rejected = Notification(NotificationType.ORDER_REJECTED, "rejected", {
        "Symbol": "PainX 800", "Reason": "BROKER_REJECTED", "Account mode": "DEMO",
    }, occurred_at=DATE, event_id="REJECT:intent-1")
    await channel.send(closed)
    await channel.send(rejected)
    await channel.drain()
    assert post.await_count == 2
    assert "JQE 📝 Trade wrapped up" in json.loads(post.await_args_list[0].args[1])["text"]
    assert "JQE 🛑 Sitting this one out" in json.loads(post.await_args_list[1].args[1])["text"]


@pytest.mark.asyncio
async def test_channel_failure_and_429_are_isolated_and_logs_redacted(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(channel_module.logger, "warning", lambda message, *args: warnings.append(message))
    post = AsyncMock(side_effect=RuntimeError("test-secret-token -100123456789"))
    channel = TelegramChannelGateway(_config(tmp_path), post=post, sleep=AsyncMock())
    assert await channel.send(_opened()) is False
    await channel.drain()
    assert post.await_count == 1
    assert warnings and all("test-secret-token" not in x and "-100123456789" not in x for x in warnings)

    class RateLimited(Exception):
        code = 429
        headers = {"Retry-After": "0.2"}

    retry_post = AsyncMock(side_effect=[RateLimited(), None])
    sleep = AsyncMock()
    retry_channel = TelegramChannelGateway(_config(tmp_path, "@another_channel"),
                                           post=retry_post, sleep=sleep)
    await retry_channel.send(_opened())
    await retry_channel.drain()
    assert retry_post.await_count == 2
    assert any(call.args == (0.2,) for call in sleep.await_args_list)


@pytest.mark.asyncio
async def test_bounded_queue_never_blocks_caller(tmp_path, monkeypatch):
    channel = TelegramChannelGateway(_config(tmp_path), post=AsyncMock(), queue_limit=1)
    channel._queue.put_nowait(_opened())
    assert await channel.send(_opened()) is False
    assert channel._queue.qsize() == 1
