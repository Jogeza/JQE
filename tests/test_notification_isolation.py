"""Offline proof that test credentials and simulated events cannot reach transports."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import socket

import pytest

from config.settings import Settings
from notifications.events import JQENotificationEvents
from notifications.factory import notification_service_from_settings
from notifications.service import NotificationService, NotificationStatus
from notifications.types import Notification, NotificationType


@pytest.mark.asyncio
async def test_test_process_ignores_even_explicit_notification_credentials(monkeypatch):
    monkeypatch.setenv("JQE_TELEGRAM_BOT_TOKEN", "offline-sentinel")
    monkeypatch.setenv("JQE_TELEGRAM_ALLOWED_CHAT_ID", "123456")
    settings = Settings(
        _env_file=None, telegram_enabled=True, telegram_bot_token="offline-sentinel",
        telegram_allowed_chat_id=123456,
        slack_webhook_url="https://hooks.slack.com/services/offline/sentinel/value",
    )
    connect = MagicMock(side_effect=AssertionError("network call attempted"))
    monkeypatch.setattr(socket.socket, "connect", connect)
    service = notification_service_from_settings(settings)
    assert service.observation.status is NotificationStatus.DISABLED
    assert await service.publish(Notification(NotificationType.SIGNAL_GENERATED, "offline")) is False
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_simulated_trade_is_labelled_and_requires_external_opt_in():
    sink = SimpleNamespace(send=AsyncMock())
    blocked = JQENotificationEvents(NotificationService(
        sink, external_delivery=True,
    ))
    assert not await blocked.demo_trade(
        kind="OPENED", facts={"Order": "SIM-1", "Entry": "101.0"},
    )
    sink.send.assert_not_awaited()
    assert not await blocked.service.publish(Notification(
        NotificationType.POSITION_OPENED, "fixture order",
        {"Order": "SIM-prior", "Entry": "101.0"},
    ))
    sink.send.assert_not_awaited()

    preview = JQENotificationEvents(NotificationService(sink))
    assert await preview.demo_trade(
        kind="OPENED", facts={"Order": "SIM-1", "Entry": "101.0"},
    )
    message = sink.send.await_args.args[0]
    assert message.simulated is True
    assert message.title == "JQE SIMULATION TRADE OPENED"
    assert message.demo_account is False
    assert message.facts["Source"] == "SIMULATION"

    opted_in = JQENotificationEvents(NotificationService(
        sink, external_delivery=True, allow_simulated_external=True,
    ))
    assert await opted_in.demo_trade(
        kind="OPENED", facts={"Order": "SIM-prior", "Entry": "101.0"},
    )
    assert sink.send.await_count == 2
