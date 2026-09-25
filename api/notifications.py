"""Read-only notification configuration and digest telemetry projections."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from config.settings import settings


ChannelState = Literal["READY", "DISABLED", "UNAVAILABLE"]
DigestState = Literal["SENT", "NOT_OBSERVED", "UNAVAILABLE"]


class NotificationChannelStatus(BaseModel):
    channel: str
    state: ChannelState
    configured: bool
    reason_codes: list[str]


class DailyDigestStatus(BaseModel):
    state: DigestState
    utc_date: str
    last_sent_at: str | None = None
    reason_codes: list[str]


class NotificationStatusResponse(BaseModel):
    observed_at: str
    channels: list[NotificationChannelStatus]
    daily_digest: DailyDigestStatus


router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _channel_status() -> list[NotificationChannelStatus]:
    telegram_enabled = bool(settings.telegram_enabled)
    telegram_configured = bool(
        settings.telegram_bot_token and settings.telegram_allowed_chat_id is not None
    )
    if not telegram_enabled:
        telegram_state: ChannelState = "DISABLED"
        telegram_reasons = ["TELEGRAM_DISABLED"]
    elif telegram_configured:
        telegram_state = "READY"
        telegram_reasons = ["TELEGRAM_CONFIGURED"]
    else:
        telegram_state = "UNAVAILABLE"
        telegram_reasons = ["TELEGRAM_CONFIGURATION_INCOMPLETE"]

    slack_configured = bool(settings.slack_webhook_url)
    return [
        NotificationChannelStatus(
            channel="telegram",
            state=telegram_state,
            configured=telegram_configured,
            reason_codes=telegram_reasons,
        ),
        NotificationChannelStatus(
            channel="slack",
            state="READY" if slack_configured else "DISABLED",
            configured=slack_configured,
            reason_codes=["SLACK_CONFIGURED" if slack_configured else "SLACK_DISABLED"],
        ),
    ]


def _digest_status(now: datetime) -> DailyDigestStatus:
    utc_date = now.date().isoformat()
    path = Path(settings.observation_evidence_path).expanduser().resolve()
    if not path.is_file():
        return DailyDigestStatus(
            state="UNAVAILABLE", utc_date=utc_date,
            reason_codes=["OBSERVATION_EVIDENCE_UNAVAILABLE"],
        )
    try:
        with sqlite3.connect(path, timeout=1.0) as connection:
            row = connection.execute(
                "SELECT sent_at FROM digest_sent_log WHERE utc_date=?",
                (utc_date,),
            ).fetchone()
    except sqlite3.Error:
        return DailyDigestStatus(
            state="UNAVAILABLE", utc_date=utc_date,
            reason_codes=["DIGEST_TELEMETRY_UNAVAILABLE"],
        )
    if row and row[0]:
        return DailyDigestStatus(
            state="SENT", utc_date=utc_date, last_sent_at=str(row[0]),
            reason_codes=["DIGEST_SENT"],
        )
    return DailyDigestStatus(
        state="NOT_OBSERVED", utc_date=utc_date,
        reason_codes=["DIGEST_NOT_OBSERVED"],
    )


@router.get("/status", response_model=NotificationStatusResponse)
def get_notification_status() -> NotificationStatusResponse:
    now = datetime.now(timezone.utc)
    return NotificationStatusResponse(
        observed_at=now.isoformat(),
        channels=_channel_status(),
        daily_digest=_digest_status(now),
    )
