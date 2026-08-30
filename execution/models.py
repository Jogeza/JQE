"""Broker-neutral durable execution state shared by orchestration and storage."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class IntentRecord:
    idempotency_key: str
    status: IntentRecordStatus
    order_id: str | None = None
    transaction_id: str | None = None


class IntentRecordStore(Protocol):
    recovery_mode: bool

    def get(self, idempotency_key: str) -> IntentRecord | None: ...
    def list_unresolved(self) -> tuple[IntentRecord, ...]: ...
    def try_claim(self, record: IntentRecord) -> ClaimState: ...
    def transition(self, record: IntentRecord) -> bool: ...
