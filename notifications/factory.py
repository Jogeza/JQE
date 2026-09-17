"""Compose every configured outbound notification transport."""

from __future__ import annotations

from core.logger import logger
from notifications.service import NotificationService
from notifications.slack import SlackConfigurationError, slack_gateway_from_settings
from notifications.telegram import TelegramConfigurationError, telegram_gateway_from_settings


def notification_service_from_settings(settings: object) -> NotificationService:
    gateways = []
    for label, builder, error_type in (
        ("Telegram", telegram_gateway_from_settings, TelegramConfigurationError),
        ("Slack", slack_gateway_from_settings, SlackConfigurationError),
    ):
        try:
            gateway = builder(settings)
        except error_type:
            logger.warning("{} notifications are unavailable: invalid configuration", label)
        else:
            if gateway is not None:
                gateways.append(gateway)
    return NotificationService(gateways=gateways)
