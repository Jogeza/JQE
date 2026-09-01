"""Fail-closed startup reconciliation for unresolved durable intents."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from execution.models import IntentRecord, IntentRecordStatus, IntentRecordStore
from execution.reconciliation import BrokerReconciliationResult, BrokerReconciliationState


class StartupRecoveryOutcome(str, Enum):
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    REMAINS_UNKNOWN = "REMAINS_UNKNOWN"
    MALFORMED_RECORD = "MALFORMED_RECORD"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    RECONCILIATION_UNAVAILABLE = "RECONCILIATION_UNAVAILABLE"
    RECONCILIATION_ERROR = "RECONCILIATION_ERROR"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"


@dataclass(frozen=True, slots=True)
class StartupRecoveryResult:
    idempotency_key: str
    outcome: StartupRecoveryOutcome
    reason: str

    @property
    def resolved(self) -> bool:
        return self.outcome in {
            StartupRecoveryOutcome.RESOLVED_ACCEPTED,
            StartupRecoveryOutcome.RESOLVED_REJECTED,
        }


@dataclass(frozen=True, slots=True)
class StartupRecoverySummary:
    results: tuple[StartupRecoveryResult, ...]

    @property
    def unresolved_count(self) -> int:
        return sum(not result.resolved for result in self.results)


class StartupReconciler(Protocol):
    async def reconcile(
        self,
        *,
        order_id: str | None = None,
        transaction_id: str | None = None,
        symbol: str | None = None,
        idempotency_key: str | None = None,
    ) -> BrokerReconciliationResult: ...


class StartupRecoveryService:
    """Reconcile persisted intents without constructing or submitting orders."""

    def __init__(
        self,
        records: IntentRecordStore,
        reconciler: StartupReconciler,
        *,
        broker: str,
        account_id: str,
    ) -> None:
        self._records = records
        self._reconciler = reconciler
        self._broker = broker.strip().lower()
        self._account_id = account_id.strip()

    async def recover(self) -> StartupRecoverySummary:
        results: list[StartupRecoveryResult] = []
        for record in self._records.list_unresolved():
            results.append(await self._recover_record(record))
        return StartupRecoverySummary(tuple(results))

    async def _recover_record(self, record: IntentRecord) -> StartupRecoveryResult:
        try:
            intent = record.to_execution_intent()
        except Exception as exc:
            return self._result(record, StartupRecoveryOutcome.MALFORMED_RECORD, exc)
        if intent is None:
            return self._result(
                record,
                StartupRecoveryOutcome.MALFORMED_RECORD,
                "Canonical execution intent payload is incomplete",
            )
        if (
            not record.broker
            or record.broker.strip().lower() != self._broker
            or not record.account_id
            or record.account_id.strip() != self._account_id
        ):
            return self._result(
                record,
                StartupRecoveryOutcome.SCOPE_MISMATCH,
                "Persisted broker/account scope does not match startup scope",
            )
        try:
            evidence = await self._reconciler.reconcile(
                order_id=record.order_id,
                transaction_id=record.transaction_id,
                symbol=intent.symbol,
                idempotency_key=intent.idempotency_key,
            )
        except Exception as exc:
            return self._remain_unresolved(
                record, StartupRecoveryOutcome.RECONCILIATION_ERROR, exc
            )
        if evidence.state is BrokerReconciliationState.UNAVAILABLE:
            return self._remain_unresolved(
                record, StartupRecoveryOutcome.RECONCILIATION_UNAVAILABLE, evidence.reason
            )
        if evidence.state is BrokerReconciliationState.CONFIRMED_MATCH:
            return self._persist(
                record,
                IntentRecordStatus.ACCEPTED,
                StartupRecoveryOutcome.RESOLVED_ACCEPTED,
                evidence,
            )
        if evidence.state is BrokerReconciliationState.CONFIRMED_ABSENCE:
            return self._persist(
                record,
                IntentRecordStatus.REJECTED,
                StartupRecoveryOutcome.RESOLVED_REJECTED,
                evidence,
            )
        return self._remain_unresolved(
            record, StartupRecoveryOutcome.REMAINS_UNKNOWN, evidence.reason
        )

    def _remain_unresolved(
        self,
        record: IntentRecord,
        outcome: StartupRecoveryOutcome,
        reason: object,
    ) -> StartupRecoveryResult:
        if record.status is IntentRecordStatus.PENDING:
            try:
                if not self._records.transition(replace(record, status=IntentRecordStatus.UNKNOWN)):
                    return self._result(
                        record,
                        StartupRecoveryOutcome.PERSISTENCE_ERROR,
                        "Ambiguous PENDING state could not be persisted as UNKNOWN",
                    )
            except Exception as exc:
                return self._result(record, StartupRecoveryOutcome.PERSISTENCE_ERROR, exc)
        return self._result(record, outcome, reason)

    def _persist(
        self,
        record: IntentRecord,
        status: IntentRecordStatus,
        outcome: StartupRecoveryOutcome,
        evidence: BrokerReconciliationResult,
    ) -> StartupRecoveryResult:
        order_id = record.order_id
        transaction_id = record.transaction_id
        if evidence.evidence is not None:
            order_id = order_id or evidence.evidence.order_id or evidence.evidence.contract_id
            transaction_id = transaction_id or evidence.evidence.transaction_id
        order_id = order_id or evidence.contract_id
        transaction_id = transaction_id or evidence.transaction_id
        try:
            persisted = self._records.transition(
                replace(
                    record,
                    status=status,
                    order_id=order_id if status is IntentRecordStatus.ACCEPTED else None,
                    transaction_id=transaction_id,
                )
            )
        except Exception as exc:
            return self._result(record, StartupRecoveryOutcome.PERSISTENCE_ERROR, exc)
        if not persisted:
            return self._result(
                record,
                StartupRecoveryOutcome.PERSISTENCE_ERROR,
                "Recovered terminal outcome could not be persisted",
            )
        return self._result(record, outcome, evidence.reason)

    @staticmethod
    def _result(
        record: IntentRecord, outcome: StartupRecoveryOutcome, reason: object
    ) -> StartupRecoveryResult:
        return StartupRecoveryResult(record.idempotency_key, outcome, str(reason))
