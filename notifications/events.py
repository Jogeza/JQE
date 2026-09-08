"""Application-layer mapping from factual JQE events to notifications."""

from __future__ import annotations

from notifications.service import NotificationService
from notifications.types import Notification, NotificationType


def masked_identifier(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 4:
        return "****"
    return f"***{normalized[-4:]}"


class JQENotificationEvents:
    """Thin downstream observer; it owns no strategy, risk, or broker action."""

    def __init__(self, service: NotificationService) -> None:
        self._service = service

    async def deriv_identity_verified(self, *, account_id: str) -> bool:
        return await self._service.publish(Notification(
            NotificationType.DERIV_IDENTITY_VERIFIED,
            "🟢 JQE DERIV DEMO VERIFIED",
            {
                "Broker": "Deriv",
                "Environment": "DEMO",
                "Account": masked_identifier(account_id),
                "Execution": "BLOCKED",
                "Reason": "Contract semantics unverified",
            },
        ))

    async def deriv_identity_rejected(self, *, reason: str) -> bool:
        return await self._service.publish(Notification(
            NotificationType.DERIV_IDENTITY_REJECTED,
            "JQE DERIV IDENTITY REJECTED",
            {"Reason": reason},
        ))

    async def trade_blocked(self, *, reason: str) -> bool:
        return await self._service.publish(Notification(
            NotificationType.TRADE_BLOCKED,
            "JQE TRADE BLOCKED",
            {"Reason": reason},
        ))

    async def emergency_stop(self, *, state: str) -> bool:
        return await self._service.publish(Notification(
            NotificationType.EMERGENCY_STOP,
            "JQE EMERGENCY STOP",
            {"State": state},
        ))
