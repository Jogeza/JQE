"""Application-layer mapping from factual JQE events to notifications."""

from __future__ import annotations

from notifications.service import NotificationService
from datetime import datetime
from collections.abc import Sequence

from notifications.types import DigestSnapshot, Notification, NotificationType


def masked_identifier(value: str) -> str:
    normalized = value.strip()
    if len(normalized) <= 4:
        return "****"
    return f"***{normalized[-4:]}"


class JQENotificationEvents:
    """Thin downstream observer; it owns no strategy, risk, or broker action."""

    def __init__(self, service: NotificationService) -> None:
        self._service = service

    @property
    def service(self) -> NotificationService:
        return self._service

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

    async def broker_connection(self, *, connected: bool, facts: dict[str, str]) -> bool:
        state = "CONNECTED" if connected else "DISCONNECTED"
        payload = dict(facts)
        payload["State"] = state
        return await self._service.publish(Notification(
            NotificationType.BROKER_CONNECTION,
            f"JQE MT5 {state}",
            payload,
        ))

    async def demo_trade(self, *, kind: str, facts: dict[str, str]) -> bool:
        mapping = {
            "OPENED": (NotificationType.POSITION_OPENED, "JQE DEMO TRADE OPENED"),
            "MODIFIED": (NotificationType.POSITION_MODIFIED, "JQE DEMO TRADE MODIFIED"),
            "CLOSED": (NotificationType.POSITION_CLOSED, "JQE DEMO TRADE CLOSED"),
        }
        if kind not in mapping:
            raise ValueError("unknown demo trade notification event")
        notification_type, title = mapping[kind]
        return await self._service.publish(Notification(notification_type, title, facts))

    async def trade_rejected(self, *, reason: str, facts: dict[str, str] | None = None) -> bool:
        payload = dict(facts or {})
        payload["Reason"] = reason
        return await self._service.publish(Notification(
            NotificationType.ORDER_REJECTED,
            "JQE TRADE REJECTED",
            payload,
        ))

    async def runtime_health(self, *, state: str, facts: dict[str, str]) -> bool:
        payload = dict(facts)
        payload["State"] = state
        return await self._service.publish(Notification(
            NotificationType.RUNTIME_HEALTH,
            f"JQE RUNTIME {state}",
            payload,
        ))

    async def daily_digest(
        self,
        *,
        snapshots: Sequence[DigestSnapshot],
        as_of: datetime | None = None,
    ) -> bool:
        return await self._service.publish(Notification(
            NotificationType.DAILY_DIGEST,
            "JQE DAILY PERFORMANCE / WATCHLIST DIGEST",
            {"Active Instruments": str(len(snapshots))},
            digest_snapshots=tuple(snapshots),
            occurred_at=as_of,
        ))

    async def paper_event(self, *, kind: str, facts: dict[str, str]) -> bool:
        mapping = {
            "OPENED": (NotificationType.PAPER_POSITION_OPENED, "JQE PAPER POSITION OPENED"),
            "CLOSED": (NotificationType.PAPER_POSITION_CLOSED, "JQE PAPER POSITION CLOSED"),
            "BLOCKED": (NotificationType.PAPER_TRADE_BLOCKED, "JQE PAPER TRADE BLOCKED"),
            "STOP_LOSS": (NotificationType.PAPER_STOP_LOSS, "JQE PAPER STOP LOSS"),
            "TAKE_PROFIT": (NotificationType.PAPER_TAKE_PROFIT, "JQE PAPER TAKE PROFIT"),
            "PERFORMANCE": (NotificationType.PAPER_PERFORMANCE, "JQE PAPER PERFORMANCE"),
            "RUNTIME_STARTED": (NotificationType.PAPER_RUNTIME_STARTED, "JQE PAPER RUNTIME STARTED"),
            "SIGNAL": (NotificationType.PAPER_SIGNAL, "JQE PAPER SIGNAL"),
            "RUNTIME_ERROR": (NotificationType.PAPER_RUNTIME_ERROR, "JQE PAPER RUNTIME ERROR"),
            "RUNTIME_STOPPED": (NotificationType.PAPER_RUNTIME_STOPPED, "JQE PAPER RUNTIME STOPPED"),
        }
        if kind not in mapping:
            raise ValueError("unknown paper notification event")
        notification_type, title = mapping[kind]
        return await self._service.publish(Notification(notification_type, title, facts))

    async def live_campaign_signal(
        self,
        *,
        facts: dict[str, str],
        actionable: bool,
        execution_enabled: bool,
    ) -> bool:
        """Publish a factual signal observation without granting execution authority."""
        if actionable:
            title = "JQE LIVE-PAPER SIGNAL — ACTIONABLE CONCLUSION"
            signal_state = "SIGNAL ONLY — ORDER NOT YET SUBMITTED"
        else:
            title = "JQE LIVE-PAPER SIGNAL — NO_TRADE / ANALYSIS ONLY"
            signal_state = "NO_TRADE — NO ORDER WILL BE SUBMITTED"
        payload = dict(facts)
        payload["Signal state"] = signal_state
        payload["Execution mode"] = (
            "ENABLED — STILL SUBJECT TO ALL SAFETY GATES"
            if execution_enabled
            else "DISABLED — ANALYSIS ONLY"
        )
        return await self._service.publish(
            Notification(NotificationType.PAPER_SIGNAL, title, payload)
        )

    async def paper_summary(self, *, facts: dict[str, str], public: bool = False) -> bool:
        safe_keys = {"Observations", "Signals", "Confirmed", "Trades", "Net R", "Drawdown R"}
        payload = {key: value for key, value in facts.items() if not public or key in safe_keys}
        payload["Audience"] = "PUBLIC_SANITIZED" if public else "PRIVATE_OPERATIONAL"
        return await self._service.publish(Notification(
            NotificationType.PAPER_PERFORMANCE, "JQE PAPER SUMMARY", payload
        ))
