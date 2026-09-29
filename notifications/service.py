"""Best-effort notification application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from collections.abc import Iterable
from typing import Protocol

from notifications.types import Notification


class NotificationGateway(Protocol):
    async def send(self, notification: Notification) -> bool | None: ...


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

    def __init__(
        self,
        gateway: NotificationGateway | None = None,
        *,
        gateways: Iterable[NotificationGateway] = (),
        external_delivery: bool = False,
        allow_simulated_external: bool = False,
    ) -> None:
        configured = list(gateways)
        if gateway is not None:
            configured.insert(0, gateway)
        self._gateways = tuple(configured)
        self._external_delivery = external_delivery
        self._allow_simulated_external = allow_simulated_external
        self._observation = NotificationObservation(
            NotificationStatus.READY if self._gateways else NotificationStatus.DISABLED
        )

    @property
    def observation(self) -> NotificationObservation:
        return self._observation

    async def publish(self, notification: Notification) -> bool:
        simulated = notification.simulated or notification.facts.get("Source") == "SIMULATION" or any(
            notification.facts.get(key, "").upper().startswith("SIM-")
            for key in ("Order", "Position")
        )
        if (self._external_delivery and simulated
                and not self._allow_simulated_external):
            return False
        if not self._gateways:
            return False
        delivered = False
        failed = False
        for gateway in self._gateways:
            try:
                result = await gateway.send(notification)
                if result is not False:
                    delivered = True
            except Exception:
                failed = True
        if failed:
            self._observation = NotificationObservation(
                NotificationStatus.UNAVAILABLE,
                last_notification_at=self._observation.last_notification_at,
                last_error="NOTIFICATION_DELIVERY_FAILED",
            )
        else:
            self._observation = NotificationObservation(
                NotificationStatus.READY,
                last_notification_at=datetime.now(timezone.utc),
            )
        return delivered
