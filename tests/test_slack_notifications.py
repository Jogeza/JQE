"""Outbound-only Slack notification transport and fan-out tests."""

from __future__ import annotations

import ast
import inspect
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService, NotificationStatus
from notifications.slack import (
    SlackConfig,
    SlackConfigurationError,
    SlackDeliveryError,
    SlackGateway,
    render_slack,
    slack_gateway_from_settings,
)
from notifications import slack as slack_module
from notifications.telegram import render_telegram
from notifications.types import DigestSnapshot, Notification, NotificationType


def test_slack_webhook_configuration_is_optional_and_secret() -> None:
    assert slack_gateway_from_settings(Settings(_env_file=None)) is None
    configured = Settings(
        _env_file=None,
        slack_webhook_url="https://hooks.slack.com/services/T000/B000/secret",
    )
    assert isinstance(slack_gateway_from_settings(configured), SlackGateway)
    assert "secret" not in repr(configured)


@pytest.mark.parametrize(
    "url",
    ("", "http://hooks.slack.com/services/a/b/c", "https://example.com/hook", "not-a-url"),
)
def test_slack_rejects_bad_webhook_urls(url: str) -> None:
    with pytest.raises(SlackConfigurationError):
        SlackConfig(url)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(NotificationType))
async def test_slack_posts_block_kit_payload_for_every_event_type(kind: NotificationType) -> None:
    post = AsyncMock()
    gateway = SlackGateway(
        SlackConfig("https://hooks.slack.com/services/T000/B000/secret"),
        post=post,
    )
    await gateway.send(Notification(kind, f"JQE {kind.value}", {"Reason": "test reason"}))
    url, payload, timeout = post.await_args.args
    assert url == "https://hooks.slack.com/services/T000/B000/secret"
    assert timeout == 10.0
    decoded = json.loads(payload)
    assert "text" not in decoded
    assert decoded["blocks"][0]["type"] == "context"
    assert decoded["attachments"][0]["blocks"][0]["type"] == "section"


@pytest.mark.parametrize(
    "notification,emoji,color",
    (
        (Notification(NotificationType.ORDER_REJECTED, "Rejected", {"Reason": "ORDER_TYPE_UNSUPPORTED_BY_BROKER"}), "❌", "#D92D20"),
        (Notification(NotificationType.ORDER_REJECTED, "Cap", {"Reason": "DAILY_INSTRUMENT_CAP_REACHED"}), "⚠️", "#EAAA08"),
        (Notification(NotificationType.POSITION_OPENED, "Opened"), "✅", "#2E8B57"),
        (Notification(NotificationType.POSITION_CLOSED, "Closed"), "✅", "#2E8B57"),
        (Notification(NotificationType.EMERGENCY_STOP, "Emergency"), "⚠️", "#D92D20"),
        (Notification(NotificationType.DAILY_DIGEST, "Digest"), "📊", "#2F80ED"),
        (Notification(NotificationType.BROKER_CONNECTION, "Connected"), "🔌", "#2F80ED"),
    ),
)
def test_slack_category_rendering(notification: Notification, emoji: str, color: str) -> None:
    payload = render_slack(notification)
    attachment = payload["attachments"][0]
    assert attachment["color"] == color
    assert emoji in attachment["blocks"][0]["text"]["text"]


@pytest.mark.parametrize(
    "notification,emoji",
    (
        (Notification(NotificationType.ORDER_REJECTED, "Rejected", {"Reason": "BROKER_REJECTED"}), "❌"),
        (Notification(NotificationType.POSITION_OPENED, "Opened", {"Risk": "1%"}), "✅"),
        (Notification(NotificationType.POSITION_CLOSED, "Closed", {"P/L": "+2R"}), "✅"),
        (Notification(NotificationType.EMERGENCY_STOP, "Emergency"), "⚠️"),
        (Notification(NotificationType.DAILY_DIGEST, "Digest"), "📊"),
        (Notification(NotificationType.BROKER_CONNECTION, "Connected"), "🔌"),
    ),
)
def test_telegram_category_rendering(notification: Notification, emoji: str) -> None:
    rendered = render_telegram(notification)
    assert rendered.startswith(emoji)
    assert "<b>" in rendered


@pytest.mark.asyncio
async def test_notification_fanout_delivers_to_telegram_and_slack() -> None:
    telegram = AsyncMock()
    slack = AsyncMock()
    service = NotificationService(gateways=(telegram, slack))
    notification = Notification(NotificationType.EMERGENCY_STOP, "JQE EMERGENCY STOP")
    assert await service.publish(notification) is True
    telegram.send.assert_awaited_once_with(notification)
    slack.send.assert_awaited_once_with(notification)


@pytest.mark.asyncio
async def test_cap_and_digest_fan_out_without_detail_loss() -> None:
    telegram = AsyncMock()
    slack = AsyncMock()
    events = JQENotificationEvents(NotificationService(gateways=(telegram, slack)))

    await events.trade_rejected(
        reason="DAILY_INSTRUMENT_CAP_REACHED",
        facts={
            "Instrument": "R_75",
            "Submission starts": "20/20",
            "Reset": "2026-09-18T00:00:00+00:00 UTC",
        },
    )
    snapshot = DigestSnapshot(
        "R_75", "H1", "BUY", 85, True, 20, 20
    )
    as_of = datetime(2026, 9, 18, tzinfo=timezone.utc)
    await events.daily_digest(snapshots=(snapshot,), as_of=as_of)

    for gateway in (telegram, slack):
        assert gateway.send.await_count == 2
        cap_event = gateway.send.await_args_list[0].args[0]
        assert cap_event.kind is NotificationType.ORDER_REJECTED
        assert cap_event.facts == {
            "Instrument": "R_75",
            "Submission starts": "20/20",
            "Reset": "2026-09-18T00:00:00+00:00 UTC",
            "Reason": "DAILY_INSTRUMENT_CAP_REACHED",
        }
        digest_event = gateway.send.await_args_list[1].args[0]
        assert digest_event.kind is NotificationType.DAILY_DIGEST
        assert digest_event.digest_snapshots == (snapshot,)

    cap_event = telegram.send.await_args_list[0].args[0]
    telegram_cap = render_telegram(cap_event)
    slack_cap = render_slack(cap_event)
    assert "20/20" in telegram_cap
    assert "20/20" in json.dumps(slack_cap)
    digest_event = telegram.send.await_args_list[1].args[0]
    telegram_digest = render_telegram(digest_event)
    slack_digest = render_slack(digest_event)
    for detail in ("R_75", "BUY", "20/20"):
        assert detail in telegram_digest
        assert detail in json.dumps(slack_digest)


@pytest.mark.asyncio
async def test_detail_preservation_across_all_event_categories() -> None:
    telegram = AsyncMock()
    slack = AsyncMock()
    events = JQENotificationEvents(NotificationService(gateways=(telegram, slack)))

    test_cases = [
        # 1. Rejection
        (
            events.trade_rejected(
                reason="ORDER_TYPE_UNSUPPORTED_BY_BROKER",
                facts={"Symbol": "EURUSD", "Details": "Broker rejected <order> & type"},
            ),
            NotificationType.ORDER_REJECTED,
            "❌",
            "#D92D20",
            ["ORDER_TYPE_UNSUPPORTED_BY_BROKER", "EURUSD", "Broker rejected &lt;order&gt; &amp; type"],
            ["ORDER_TYPE_UNSUPPORTED_BY_BROKER", "EURUSD", "Broker rejected &lt;order&gt; &amp; type"],
        ),
        # 2. Trade opened
        (
            events.demo_trade(
                kind="OPENED",
                facts={
                    "Symbol": "R_75",
                    "Side": "BUY",
                    "Position": "98765",
                    "Entry": "100.50",
                    "Stop loss": "99.00",
                    "Take profit": "103.50",
                    "Volume": "2.5",
                    "Risk amount": "10.00",
                },
            ),
            NotificationType.POSITION_OPENED,
            "✅",
            "#2E8B57",
            ["R_75", "BUY", "98765", "<code>100.50</code>", "<code>99.00</code>", "<code>103.50</code>", "<code>2.5</code>", "<code>10.00</code>"],
            ["R_75", "BUY", "98765", "100.50", "99.00", "103.50", "2.5", "10.00"],
        ),
        # 3. Trade closed
        (
            events.demo_trade(
                kind="CLOSED",
                facts={
                    "Symbol": "R_75",
                    "Position": "98765",
                    "Exit": "103.50",
                    "P/L": "+30.0",
                    "Exit reason": "TAKE_PROFIT",
                },
            ),
            NotificationType.POSITION_CLOSED,
            "✅",
            "#2E8B57",
            ["R_75", "98765", "<code>103.50</code>", "<code>+30.0</code>", "TAKE_PROFIT"],
            ["R_75", "98765", "103.50", "+30.0", "TAKE_PROFIT"],
        ),
        # 4. Emergency / Safety
        (
            events.emergency_stop(state="ACTIVE"),
            NotificationType.EMERGENCY_STOP,
            "⚠️",
            "#D92D20",
            ["ACTIVE"],
            ["ACTIVE"],
        ),
        # 5. Connection
        (
            events.broker_connection(
                connected=True,
                facts={"Broker": "MT5", "Environment": "DEMO"},
            ),
            NotificationType.BROKER_CONNECTION,
            "🔌",
            "#2F80ED",
            ["MT5", "DEMO", "CONNECTED"],
            ["MT5", "DEMO", "CONNECTED"],
        ),
        # 6. Digest
        (
            events.daily_digest(
                snapshots=(
                    DigestSnapshot("R_75", "H1", "BUY", 85.0, True, 5, 20),
                    DigestSnapshot("FX Vol 20", "H1", "NO_TRADE", None, False, 0, 20),
                ),
                as_of=datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
            ),
            NotificationType.DAILY_DIGEST,
            "📊",
            "#2F80ED",
            ["R_75", "H1", "BUY", "85", "YES (STEADY)", "5/20", "FX Vol 20", "NO_TRADE", "N/A", "NO (UNSTEADY)", "0/20"],
            ["R_75", "H1", "BUY", "85", "YES (STEADY)", "5/20", "FX Vol 20", "NO_TRADE", "N/A", "NO (UNSTEADY)", "0/20"],
        ),
    ]

    for coroutine, expected_kind, expected_emoji, expected_color, tg_expectations, slack_expectations in test_cases:
        telegram.send.reset_mock()
        slack.send.reset_mock()
        await coroutine

        telegram.send.assert_awaited_once()
        slack.send.assert_awaited_once()

        notification = telegram.send.await_args.args[0]
        assert notification.kind is expected_kind

        # Verify Telegram rendering
        tg_rendered = render_telegram(notification)
        assert tg_rendered.startswith(expected_emoji)
        for expected in tg_expectations:
            assert expected in tg_rendered

        # Verify Slack rendering
        slack_rendered = render_slack(notification)
        assert "text" not in slack_rendered
        assert slack_rendered["blocks"][0]["type"] == "context"
        attachment = slack_rendered["attachments"][0]
        assert attachment["color"] == expected_color
        assert expected_emoji in attachment["blocks"][0]["text"]["text"]
        slack_json = json.dumps(slack_rendered)
        for expected in slack_expectations:
            assert expected in slack_json


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", (TimeoutError("timeout"), SlackDeliveryError("bad webhook")))
async def test_failed_slack_post_never_raises_or_blocks_other_channels(failure: Exception) -> None:
    telegram = AsyncMock()
    slack = AsyncMock()
    slack.send.side_effect = failure
    service = NotificationService(gateways=(slack, telegram))
    delivered = await service.publish(
        Notification(NotificationType.RUNTIME_HEALTH, "JQE RUNTIME STALE")
    )
    assert delivered is True
    telegram.send.assert_awaited_once()
    assert service.observation.status is NotificationStatus.UNAVAILABLE
    assert service.observation.last_error == "NOTIFICATION_DELIVERY_FAILED"


@pytest.mark.asyncio
async def test_requested_event_mappings_are_plain_factual_notifications() -> None:
    gateway = AsyncMock()
    events = JQENotificationEvents(NotificationService(gateway))
    await events.broker_connection(connected=False, facts={"Reason": "VPS_NETWORK"})
    await events.demo_trade(kind="OPENED", facts={"SL": "99", "TP": "103", "Risk": "1%"})
    await events.demo_trade(kind="MODIFIED", facts={"SL": "100", "TP": "103", "Risk": "0.5%"})
    await events.demo_trade(kind="CLOSED", facts={"P/L": "+2R", "Risk": "1%"})
    await events.trade_rejected(reason="ORDER_TYPE_UNSUPPORTED_BY_BROKER")
    await events.emergency_stop(state="ACTIVE")
    await events.daily_digest(
        snapshots=(DigestSnapshot("R_75", "H1", "NO_TRADE", 40, False, 0, 20),)
    )
    await events.runtime_health(state="STALE", facts={"Reason": "STALE_HEARTBEAT"})
    kinds = [call.args[0].kind for call in gateway.send.await_args_list]
    assert kinds == [
        NotificationType.BROKER_CONNECTION,
        NotificationType.POSITION_OPENED,
        NotificationType.POSITION_MODIFIED,
        NotificationType.POSITION_CLOSED,
        NotificationType.ORDER_REJECTED,
        NotificationType.EMERGENCY_STOP,
        NotificationType.DAILY_DIGEST,
        NotificationType.RUNTIME_HEALTH,
    ]


def test_slack_module_has_zero_execution_or_inbound_command_surface() -> None:
    source = inspect.getsource(slack_module)
    forbidden_tokens = (
        "AsyncTradeExecutor", "OrderRequest", "OrderSide", "submit_order", "order_send",
        "execution.policy", "ExecutionPolicy", "ExecutionIntent", "process_update",
        "slash_command", "request_handler",
    )
    for token in forbidden_tokens:
        assert token not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("execution") for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("execution")
