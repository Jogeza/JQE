"""Application-layer mapping from factual JQE events to notifications."""

from __future__ import annotations

from notifications.service import NotificationService
from notifications.chart import ChartSnapshot
from datetime import datetime
from datetime import timezone
from collections.abc import Sequence
import math

from broker.types import Tick

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

    async def strategy_signal(self, *, symbol: str, timeframe: str, side: str,
                              confidence: object, bar_time: str,
                              tick: Tick | None = None,
                              planned_entry: float | None = None,
                              planned_stop_loss: float | None = None,
                              planned_take_profit: float | None = None,
                              simulated: bool = False) -> bool:
        """Report a canonical closed-bar decision without implying risk approval."""
        facts = {
            "Symbol": symbol, "Timeframe": timeframe, "Signal": side,
            "Confidence": str(confidence), "Closed bar time": bar_time,
            "Execution": "PENDING RISK AND BROKER CHECKS" if side in {"BUY", "SELL"}
                         else "NO TRADE",
        }
        now = datetime.now(timezone.utc)
        if (tick is not None and tick.time.tzinfo is not None
                and 0 <= (now - tick.time.astimezone(timezone.utc)).total_seconds() <= 15
                and all(math.isfinite(value) and value > 0 for value in (tick.bid, tick.ask))):
            facts.update({"Tick bid": str(tick.bid), "Tick ask": str(tick.ask),
                          "Tick time": tick.time.astimezone(timezone.utc).isoformat()})
        else:
            facts["Price"] = "price unavailable"
        for label, value in (
            ("Planned entry", planned_entry),
            ("Planned stop loss", planned_stop_loss),
            ("TP1", planned_take_profit),
        ):
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                facts[label] = str(value)
        if simulated:
            facts["Source"] = "SIMULATION"
        return await self._service.publish(Notification(
            NotificationType.SIGNAL_GENERATED,
            "JQE SIMULATION STRATEGY SIGNAL" if simulated else "JQE WELTRADE STRATEGY SIGNAL",
            facts, simulated=simulated,
        ))

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

    async def trade_blocked(self, *, reason: str, facts: dict[str, str] | None = None) -> bool:
        return await self._service.publish(Notification(
            NotificationType.TRADE_BLOCKED,
            "JQE TRADE BLOCKED",
            {**(facts or {}), "Reason": reason},
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

    async def demo_trade(
        self,
        *,
        kind: str,
        facts: dict[str, str],
        chart_snapshot: ChartSnapshot | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
        simulated: bool = False,
    ) -> bool:
        mapping = {
            "OPENED": (NotificationType.POSITION_OPENED, "JQE DEMO TRADE OPENED"),
            "MODIFIED": (NotificationType.POSITION_MODIFIED, "JQE DEMO TRADE MODIFIED"),
            "CLOSED": (NotificationType.POSITION_CLOSED, "JQE DEMO TRADE CLOSED"),
        }
        if kind not in mapping:
            raise ValueError("unknown demo trade notification event")
        notification_type, title = mapping[kind]
        simulated = simulated or any(
            str(facts.get(key, "")).strip().upper().startswith("SIM-")
            for key in ("Order", "Position")
        )
        if simulated:
            title = f"JQE SIMULATION TRADE {kind}"
            facts = {**facts, "Source": "SIMULATION", "Account mode": "SIMULATION"}
        return await self._service.publish(
            Notification(notification_type, title, facts, chart_snapshot=chart_snapshot,
                         event_id=event_id, demo_account=not simulated,
                         occurred_at=occurred_at, simulated=simulated)
        )

    async def pending_order_placed(
        self,
        *,
        facts: dict[str, str],
        chart_snapshot: ChartSnapshot | None = None,
    ) -> bool:
        return await self._service.publish(Notification(
            NotificationType.PENDING_ORDER_PLACED,
            "JQE PENDING ORDER PLACED",
            facts,
            chart_snapshot=chart_snapshot,
        ))

    async def trade_rejected(self, *, reason: str, facts: dict[str, str] | None = None,
                             event_id: str | None = None, demo_account: bool = False) -> bool:
        payload = dict(facts or {})
        payload["Reason"] = reason
        return await self._service.publish(Notification(
            NotificationType.ORDER_REJECTED,
            "JQE TRADE REJECTED",
            payload, event_id=event_id, demo_account=demo_account,
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
        chart_snapshot: ChartSnapshot | None = None,
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
            Notification(NotificationType.PAPER_SIGNAL, title, payload, chart_snapshot=chart_snapshot)
        )

    async def paper_summary(self, *, facts: dict[str, str], public: bool = False) -> bool:
        safe_keys = {"Observations", "Signals", "Confirmed", "Trades", "Net R", "Drawdown R"}
        payload = {key: value for key, value in facts.items() if not public or key in safe_keys}
        payload["Audience"] = "PUBLIC_SANITIZED" if public else "PRIVATE_OPERATIONAL"
        return await self._service.publish(Notification(
            NotificationType.PAPER_PERFORMANCE, "JQE PAPER SUMMARY", payload
        ))
