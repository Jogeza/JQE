"""Best-effort notification application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from notifications.types import Notification


class NotificationGateway(Protocol):
    async def send(self, notification: Notification) -> None: ...


class NotificationStatus(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class NotificationObservation:
    status: NotificationStatus
    last_notification_at: datetime | None = None
    last_error: str | None = None


class NotificationService:
    """Deliver observations without ever becoming execution authority."""

    def __init__(self, gateway: NotificationGateway | None = None) -> None:
        self._gateway = gateway
        self._observation = NotificationObservation(
            NotificationStatus.READY if gateway is not None else NotificationStatus.DISABLED
        )

    @property
    def observation(self) -> NotificationObservation:
        return self._observation

    async def publish(self, notification: Notification) -> bool:
        if self._gateway is None:
            return False
        try:
            await self._gateway.send(notification)
        except Exception:
            self._observation = NotificationObservation(
                NotificationStatus.UNAVAILABLE,
                last_notification_at=self._observation.last_notification_at,
                last_error="NOTIFICATION_DELIVERY_FAILED",
            )
            return False
        self._observation = NotificationObservation(
            NotificationStatus.READY,
            last_notification_at=datetime.now(timezone.utc),
        )
        return True
