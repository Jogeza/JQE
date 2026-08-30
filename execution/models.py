"""Broker-neutral durable execution state shared by orchestration and storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


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
