"""Broker-neutral durable execution state shared by orchestration and storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from broker.types import ExecutionQuantity, OrderSide
from execution.policy import ExecutionIntent


class IntentRecordStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class ClaimState(str, Enum):
    CLAIMED = "CLAIMED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    CONFLICT = "CONFLICT"


class ReservationState(str, Enum):
    ACQUIRED = "ACQUIRED"
    HELD = "HELD"
    UNRESOLVED_INTENT = "UNRESOLVED_INTENT"


@dataclass(frozen=True, slots=True)
class IntentRecord:
    idempotency_key: str
    status: IntentRecordStatus
    order_id: str | None = None
    transaction_id: str | None = None
    symbol: str | None = None
    side: OrderSide | str | None = None
    quantity: ExecutionQuantity | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    authorized_risk_amount: float | None = None
    expected_loss_at_stop: float | None = None
    broker: str | None = None
    account_id: str | None = None

    @classmethod
    def from_execution_intent(
        cls,
        intent: ExecutionIntent,
        status: IntentRecordStatus = IntentRecordStatus.PENDING,
        *,
        order_id: str | None = None,
        transaction_id: str | None = None,
        broker: str | None = None,
        account_id: str | None = None,
    ) -> IntentRecord:
        """Construct an IntentRecord capturing full canonical intent parameters."""
        return cls(
            idempotency_key=intent.idempotency_key,
            status=status,
            order_id=order_id,
            transaction_id=transaction_id,
            symbol=intent.symbol,
            side=intent.side if isinstance(intent.side, OrderSide) else OrderSide(intent.side),
            quantity=intent.quantity,
            entry=intent.entry,
            stop_loss=intent.stop_loss,
            take_profit=intent.take_profit,
            authorized_risk_amount=intent.authorized_risk_amount,
            expected_loss_at_stop=intent.expected_loss_at_stop,
            broker=broker,
            account_id=account_id,
        )

    def to_execution_intent(self) -> ExecutionIntent | None:
        """Reconstruct a verified ExecutionIntent if all parameters are present."""
        if (
            self.symbol is None
            or self.side is None
            or self.quantity is None
            or self.entry is None
            or self.stop_loss is None
            or self.take_profit is None
            or self.authorized_risk_amount is None
            or self.expected_loss_at_stop is None
        ):
            return None
        side_val = self.side if isinstance(self.side, OrderSide) else OrderSide(self.side)
        return ExecutionIntent(
            symbol=self.symbol,
            side=side_val,
            quantity=self.quantity,
            authorized_risk_amount=self.authorized_risk_amount,
            expected_loss_at_stop=self.expected_loss_at_stop,
            quantity_risk_verified=True,
            entry=self.entry,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            idempotency_key=self.idempotency_key,
            risk_approved=True,
        )


@dataclass(frozen=True, slots=True)
class ExecutionReservation:
    scope: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime


class IntentRecordStore(Protocol):
    recovery_mode: bool

    def get(self, idempotency_key: str) -> IntentRecord | None: ...
    def list_unresolved(self) -> tuple[IntentRecord, ...]: ...
    def acquire_reservation(
        self, scope: str, owner_id: str, lease_seconds: int, intent_key: str
    ) -> ReservationState: ...
    def release_reservation(self, scope: str, owner_id: str) -> bool: ...
    def try_claim_under_reservation(
        self, record: IntentRecord, scope: str, owner_id: str
    ) -> ClaimState: ...
    def try_claim(self, record: IntentRecord) -> ClaimState: ...
    def transition(self, record: IntentRecord) -> bool: ...
