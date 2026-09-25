"""Outbound-only Slack Incoming Webhook transport."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from notifications.types import Notification, NotificationType


class SlackConfigurationError(ValueError):
    pass


class SlackDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SlackConfig:
    webhook_url: str = field(repr=False)
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        parsed = urlparse(self.webhook_url.strip())
        if parsed.scheme != "https" or parsed.hostname not in {"hooks.slack.com", "hooks.slack-gov.com"}:
            raise SlackConfigurationError("Slack Incoming Webhook URL is invalid")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 30:
            raise SlackConfigurationError("Slack timeout is invalid")


SlackPost = Callable[[str, bytes, float], Awaitable[None]]

_RED = "#D92D20"
_GREEN = "#2E8B57"
_AMBER = "#EAAA08"
_BLUE = "#2F80ED"
_NEUTRAL = "#6B7280"


def _slack_escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _presentation(notification: Notification) -> tuple[str, str]:
    reason = notification.facts.get("Reason", "")
    if notification.kind is NotificationType.ORDER_REJECTED:
        is_cap = "CAP" in reason.upper() or "CAP" in notification.title.upper()
        return ("⚠️", _AMBER) if is_cap else ("❌", _RED)
    if notification.kind in {
        NotificationType.TRADE_BLOCKED,
        NotificationType.PAPER_TRADE_BLOCKED,
        NotificationType.DERIV_IDENTITY_REJECTED,
    }:
        return "❌", _RED
    if notification.kind in {
        NotificationType.EMERGENCY_STOP,
        NotificationType.RUNTIME_HEALTH,
        NotificationType.PAPER_RUNTIME_ERROR,
    }:
        return "⚠️", _RED
    if notification.kind in {
        NotificationType.POSITION_OPENED,
        NotificationType.POSITION_MODIFIED,
        NotificationType.POSITION_CLOSED,
        NotificationType.PAPER_POSITION_OPENED,
        NotificationType.PAPER_POSITION_CLOSED,
        NotificationType.DERIV_IDENTITY_VERIFIED,
    }:
        return "✅", _GREEN
    if notification.kind in {
        NotificationType.DAILY_DIGEST,
        NotificationType.PAPER_PERFORMANCE,
    }:
        return "📊", _BLUE
    if notification.kind is NotificationType.BROKER_CONNECTION:
        return "🔌", _BLUE
    return "ℹ️", _NEUTRAL


def render_slack(notification: Notification) -> dict[str, object]:
    emoji, color = _presentation(notification)
    title = f"{emoji} *{_slack_escape(notification.title)}*"
    detail_blocks: list[dict[str, object]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": title}}
    ]
    if notification.kind is NotificationType.DAILY_DIGEST:
        date = notification.occurred_at.strftime("%Y-%m-%d UTC") if notification.occurred_at else "Current UTC day"
        detail_blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*Date:* {_slack_escape(date)}  •  *Active Instruments:* {len(notification.digest_snapshots)}"}],
        })
        for item in notification.digest_snapshots:
            score = f"{item.quality_score:.0f}" if isinstance(item.quality_score, (int, float)) else "N/A"
            steady = "YES (STEADY)" if item.is_steady else "NO (UNSTEADY)"
            detail_blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{_slack_escape(item.symbol)} ({_slack_escape(item.timeframe)})*\n"
                        f"• Conclusion: `{_slack_escape(item.conclusion)}`\n"
                        f"• Quality Score: `{score}`\n"
                        f"• Steady / Worth Trading: `{steady}`\n"
                        f"• Daily Cap Usage: `{item.cap_count}/{item.cap_limit}`"
                    ),
                },
            })
    elif notification.facts:
        fields = [
            {"type": "mrkdwn", "text": f"*{_slack_escape(key)}*\n`{_slack_escape(value)}`"}
            for key, value in notification.facts.items()
        ]
        for i in range(0, len(fields), 10):
            detail_blocks.append({"type": "section", "fields": fields[i : i + 10]})
    if notification.chart_snapshot is not None:
        snapshot = notification.chart_snapshot
        detail_blocks.append({
            "type": "image",
            # Slack webhooks accept Block Kit image blocks. Deployments that
            # provide an externally reachable URL use it; the data URL keeps
            # the rendered snapshot available to formatters and test clients.
            "image_url": snapshot.image_url or snapshot.data_url,
            "alt_text": f"{notification.title} chart snapshot",
        })
    return {
        "blocks": [{"type": "context", "elements": [{"type": "mrkdwn", "text": "*JQE ALERTS*"}]}],
        "attachments": [{"color": color, "blocks": detail_blocks}],
    }


class SlackGateway:
    """Posts notifications to one webhook; it has no inbound surface."""

    def __init__(self, config: SlackConfig, post: SlackPost | None = None) -> None:
        self._config = config
        self._post = post or self._default_post

    async def send(self, notification: Notification) -> None:
        payload = json.dumps(render_slack(notification), ensure_ascii=False).encode("utf-8")
        try:
            await self._post(self._config.webhook_url, payload, self._config.timeout_seconds)
        except Exception as exc:
            raise SlackDeliveryError("Slack delivery failed") from exc

    @staticmethod
    async def _default_post(url: str, payload: bytes, timeout: float) -> None:
        def post() -> None:
            request = Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=timeout) as response:
                    if not 200 <= int(response.status) < 300:
                        raise SlackDeliveryError("Slack delivery failed")
            except (HTTPError, URLError, TimeoutError) as exc:
                raise SlackDeliveryError("Slack delivery failed") from exc

        await asyncio.to_thread(post)


def slack_gateway_from_settings(settings: object) -> SlackGateway | None:
    webhook_url = getattr(settings, "slack_webhook_url", None)
    if webhook_url is None or not str(webhook_url).strip():
        return None
    return SlackGateway(SlackConfig(
        webhook_url=str(webhook_url),
        timeout_seconds=getattr(settings, "slack_request_timeout_seconds", 10.0),
    ))
