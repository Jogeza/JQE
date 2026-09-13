"""Offline Telegram observability and authorization tests."""

from __future__ import annotations

from dataclasses import dataclass
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from notifications.service import NotificationService, NotificationStatus
from notifications.events import JQENotificationEvents
from notifications.telegram import (
    TelegramCommandProcessor,
    TelegramConfig,
    TelegramConfigurationError,
    TelegramDeliveryError,
    TelegramGateway,
    telegram_gateway_from_settings,
)
from notifications.types import Notification, NotificationType


@dataclass
class DTO:
    value: str
    def model_dump(self, mode="json"):
        return {"value": self.value}


class Reads:
    def __init__(self) -> None:
        self.get_system_status = AsyncMock(return_value=DTO("system"))
        self.get_risk_status = AsyncMock(return_value=DTO("risk"))
        self.get_execution_safety = MagicMock(return_value=DTO("safety"))
        self.get_execution_state = AsyncMock(return_value=DTO("positions"))
        self.get_performance_summary = AsyncMock(return_value=DTO("performance"))


def update(command: str, chat_id: int = 7) -> dict:
    return {"message": {"chat": {"id": chat_id}, "text": command}}


def test_disabled_by_default_and_secret_repr_is_redacted() -> None:
    settings = Settings(_env_file=None)
    assert telegram_gateway_from_settings(settings) is None
    config = TelegramConfig("super-secret-token", 7)
    assert "super-secret-token" not in repr(config)


@pytest.mark.parametrize("kwargs", [
    {"telegram_enabled": True, "telegram_allowed_chat_id": 7},
    {"telegram_enabled": True, "telegram_bot_token": "token"},
])
def test_incomplete_enabled_configuration_fails_safely(kwargs) -> None:
    with pytest.raises(TelegramConfigurationError) as exc:
        telegram_gateway_from_settings(Settings(_env_file=None, **kwargs))
    assert "token" not in str(exc.value).lower() or "missing" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_gateway_uses_https_and_escapes_factual_message() -> None:
    post = AsyncMock()
    gateway = TelegramGateway(TelegramConfig("secret-token", 7), post=post)
    await gateway.send(Notification(NotificationType.TRADE_BLOCKED, "Blocked <trade>", {"Reason": "risk & safety"}))
    url, payload, timeout = post.await_args.args
    assert url.startswith("https://api.telegram.org/")
    assert b"Blocked &lt;trade&gt;" in payload
    assert b"risk &amp; safety" in payload
    assert timeout == 10.0


@pytest.mark.asyncio
async def test_gateway_fans_out_over_private_chat_ids() -> None:
    post = AsyncMock()
    gateway = TelegramGateway(TelegramConfig("secret-token", (7, 8)), post=post)
    await gateway.send_text("signal")
    assert [json.loads(call.args[1])["chat_id"] for call in post.await_args_list] == [7, 8]


@pytest.mark.asyncio
async def test_delivery_failure_is_generic_and_does_not_authorize_anything() -> None:
    async def fail(*_args):
        raise RuntimeError("secret-token")
    gateway = TelegramGateway(TelegramConfig("secret-token", 7), post=fail)
    service = NotificationService(gateway)
    assert not await service.publish(Notification(NotificationType.EMERGENCY_STOP, "Emergency stop"))
    assert service.observation.status is NotificationStatus.UNAVAILABLE
    assert service.observation.last_error == "NOTIFICATION_DELIVERY_FAILED"
    assert "secret-token" not in repr(service.observation)


@pytest.mark.asyncio
async def test_authorized_commands_are_read_only_projections() -> None:
    reads = Reads()
    processor = TelegramCommandProcessor(7, reads)
    for command, expected in [
        ("/status", "system"), ("/health", "system"), ("/risk", "risk"),
        ("/safety", "safety"), ("/positions", "positions"),
        ("/performance", "performance"),
    ]:
        assert expected in (await processor.process_update(update(command)))
    signal = await processor.process_update(update("/signal"))
    assert "UNAVAILABLE" in signal
    assert not hasattr(reads, "submit_order")


@pytest.mark.asyncio
async def test_unauthorized_chat_invokes_no_read_model() -> None:
    reads = Reads()
    processor = TelegramCommandProcessor(7, reads)
    assert await processor.process_update(update("/status", chat_id=8)) is None
    reads.get_system_status.assert_not_awaited()
    reads.get_risk_status.assert_not_awaited()
    reads.get_execution_safety.assert_not_called()
    reads.get_execution_state.assert_not_awaited()
    reads.get_performance_summary.assert_not_awaited()


@pytest.mark.asyncio
async def test_factual_event_adapter_masks_identity_and_preserves_block_reason() -> None:
    gateway = AsyncMock()
    service = NotificationService(gateway)
    events = JQENotificationEvents(service)
    await events.deriv_identity_verified(account_id="CR123456")
    identity = gateway.send.await_args.args[0]
    assert identity.facts["Account"] == "***3456"
    assert identity.facts["Execution"] == "BLOCKED"
    assert "CR123456" not in repr(identity)
    await events.trade_blocked(reason="DAILY_LIMIT_REACHED")
    blocked = gateway.send.await_args.args[0]
    assert blocked.facts["Reason"] == "DAILY_LIMIT_REACHED"


@pytest.mark.asyncio
async def test_live_campaign_signal_labels_actionable_and_no_trade() -> None:
    gateway = AsyncMock()
    events = JQENotificationEvents(NotificationService(gateway))
    facts = {
        "Symbol / timeframe": "XAUUSD / M15",
        "Conclusion": "BUY",
        "Quality score": "85",
        "Observed at": "2026-01-01T00:15:00+00:00",
        "Candle closed at": "2026-01-01T00:15:00+00:00",
        "Expires at": "2026-01-01T00:30:00+00:00",
        "Data freshness": "fresh",
    }
    await events.live_campaign_signal(
        facts=facts, actionable=True, execution_enabled=True
    )
    actionable = gateway.send.await_args.args[0]
    assert "ACTIONABLE CONCLUSION" in actionable.title
    assert actionable.facts["Signal state"] == "SIGNAL ONLY — ORDER NOT YET SUBMITTED"

    await events.live_campaign_signal(
        facts={**facts, "Conclusion": "NO_TRADE"},
        actionable=False,
        execution_enabled=False,
    )
    no_trade = gateway.send.await_args.args[0]
    assert "NO_TRADE / ANALYSIS ONLY" in no_trade.title
    assert no_trade.facts["Execution mode"] == "DISABLED — ANALYSIS ONLY"
