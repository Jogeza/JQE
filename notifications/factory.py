"""Compose every configured outbound notification transport."""

from __future__ import annotations

import os

from core.logger import logger
from notifications.service import NotificationService
from notifications.telegram_channel import telegram_channel_from_settings
from notifications.slack import SlackConfigurationError, slack_gateway_from_settings
from notifications.telegram import (
    TelegramConfigurationError,
    telegram_gateways_from_settings,
)


def notification_service_from_settings(settings: object) -> NotificationService:
    if os.environ.get("JQE_TEST_NO_EXTERNAL_NOTIFICATIONS") == "1":
        return NotificationService()
    gateways = []
    for label, builder, error_type in (
        ("Telegram", telegram_gateways_from_settings, TelegramConfigurationError),
        ("Slack", slack_gateway_from_settings, SlackConfigurationError),
    ):
        try:
            gateway = builder(settings)
        except error_type:
            logger.warning("{} notifications are unavailable: invalid configuration", label)
        else:
            if gateway is not None:
                if isinstance(gateway, tuple):
                    gateways.extend(gateway)
                else:
                    gateways.append(gateway)
    try:
        channel = telegram_channel_from_settings(settings)
    except Exception:
        logger.warning("Telegram channel alerts are unavailable: invalid configuration")
    else:
        if channel is not None:
            gateways.append(channel)
    return NotificationService(
        gateways=gateways, external_delivery=True,
        allow_simulated_external=(
            os.environ.get("JQE_SIMULATION_NOTIFICATIONS_ENABLED", "").strip().lower() == "true"
        ),
    )
