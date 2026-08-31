"""Async, gateway-injected execution boundary with explicit reconciliation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol
from uuid import uuid4

from broker.types import OrderRequest, OrderResult, Position
from execution.policy import ExecutionContext, ExecutionDecision, ExecutionIntent, ExecutionPolicy
from execution.trade_manager import PositionSnapshotAdapter
from execution.reconciliation import BrokerReconciliationResult, BrokerReconciliationState
from execution.observability import log_unresolved_execution
from execution.models import (
    ClaimState,
    IntentRecord,
    IntentRecordStatus,
    IntentRecordStore,
    ReservationState,
)
from execution.policy import ExecutionDecisionCode


_DEFAULT_RESERVATION_LEASE_SECONDS = 120


class ReconciliationState(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXECUTED = "ALREADY_EXECUTED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"


class ExecutionGateway(Protocol):
    async def get_positions(self) -> list[Position]: ...

    async def submit_order(self, order: OrderRequest) -> OrderResult: ...


class ExecutionReconciler(Protocol):
    async def reconcile(
        self, *, order_id: str | None = None, transaction_id: str | None = None,
        symbol: str | None = None, idempotency_key: str | None = None,
    ) -> BrokerReconciliationResult: ...


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    state: ReconciliationState
    reason: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    state: ReconciliationState
    decision: ExecutionDecision
    order_id: str | None = None
    reason: str = ""


class AsyncTradeExecutor:
    """Coordinate policy, atomic idempotency, reconciliation, and submission."""

    def __init__(
        self,
        gateway: ExecutionGateway,
        records: IntentRecordStore,
        reconciler: ExecutionReconciler | None = None,
        *,
        reservation_lease_seconds: int = _DEFAULT_RESERVATION_LEASE_SECONDS,
    ) -> None:
        self._gateway = gateway
        self._records = records
        self._reconciler = reconciler
        self._reservation_lease_seconds = reservation_lease_seconds

    async def reconcile(
        self, intent: ExecutionIntent, positions: tuple[Position, ...] | None = None,
    ) -> ReconciliationResult:
        try:
            record = self._records.get(intent.idempotency_key)
        except Exception:
            return ReconciliationResult(ReconciliationState.UNKNOWN, "Intent records unavailable")
        if record is not None and record.status is IntentRecordStatus.REJECTED:
            return ReconciliationResult(ReconciliationState.REJECTED, "Intent was rejected")
        if record is not None and record.status is IntentRecordStatus.ACCEPTED:
            return ReconciliationResult(
                ReconciliationState.ALREADY_EXECUTED,
                "Intent was already accepted",
            )
        try:
            observed_positions = tuple(await self._gateway.get_positions()) if positions is None else positions
            snapshots = PositionSnapshotAdapter.from_positions(observed_positions)
        except Exception:
            return ReconciliationResult(ReconciliationState.UNKNOWN, "Broker state unavailable")
        if snapshots is None:
            return ReconciliationResult(ReconciliationState.UNKNOWN, "Broker state malformed")
        symbol = intent.symbol.strip().upper() if isinstance(intent.symbol, str) else ""
        symbol_match = any(position.symbol.strip().upper() == symbol for position in snapshots)
        if symbol_match and record is None:
            return ReconciliationResult(ReconciliationState.ALREADY_EXECUTED, "Symbol has an open position")
        if record is None:
            if getattr(self._records, "recovery_mode", False):
                return ReconciliationResult(ReconciliationState.UNKNOWN, "Recovery mode cannot prove intent absence")
            return ReconciliationResult(ReconciliationState.READY_TO_SUBMIT, "No prior intent or position found")
        if record.status in {IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN}:
            if self._reconciler is None:
                state = ReconciliationState.PENDING if record.status is IntentRecordStatus.PENDING else ReconciliationState.UNKNOWN
                return ReconciliationResult(state, "Broker reconciler is not configured")
            evidence = await self._reconciler.reconcile(
                order_id=record.order_id,
                transaction_id=record.transaction_id,
                symbol=intent.symbol,
                idempotency_key=intent.idempotency_key,
            )
            if evidence.state is BrokerReconciliationState.CONFIRMED_MATCH:
                if not self._transition(
                    intent,
                    IntentRecordStatus.ACCEPTED,
                    record.order_id or evidence.contract_id,
                    record.transaction_id or evidence.transaction_id,
                ):
                    return ReconciliationResult(
                        ReconciliationState.UNKNOWN,
                        "Reconciled outcome could not be persisted",
                    )
                return ReconciliationResult(ReconciliationState.ALREADY_EXECUTED, evidence.reason)
            if record.status is IntentRecordStatus.PENDING:
                if not self._transition(intent, IntentRecordStatus.UNKNOWN):
                    return ReconciliationResult(
                        ReconciliationState.UNKNOWN,
                        "Uncertain recovery state could not be persisted",
                    )
            return ReconciliationResult(ReconciliationState.UNKNOWN, evidence.reason)
        return ReconciliationResult(ReconciliationState.UNKNOWN, "Intent state is not recoverable")

    async def submit(
        self,
        intent: ExecutionIntent,
        context: ExecutionContext | None,
        *,
        before_submit: Callable[[ExecutionDecision], None] | None = None,
        context_provider: Callable[[], Awaitable[ExecutionContext | None]] | None = None,
        after_submit: Callable[[ExecutionResult], None] | None = None,
    ) -> ExecutionResult:
        scope = context.account_id.strip() if context is not None and isinstance(context.account_id, str) else ""
        if not scope:
            decision = ExecutionDecision(
                False,
                ExecutionDecisionCode.SAFETY_CONTEXT_INVALID,
                "Execution reservation requires an account identity",
            )
            return ExecutionResult(ReconciliationState.UNKNOWN, decision, reason=decision.reason)
        owner_id = str(uuid4())
        try:
            reservation = self._records.acquire_reservation(
                scope,
                owner_id,
                self._reservation_lease_seconds,
                intent.idempotency_key,
            )
        except Exception:
            decision = ExecutionDecision(
                False,
                ExecutionDecisionCode.EXECUTION_RESERVATION_UNAVAILABLE,
                "Execution reservation is unavailable",
            )
            return ExecutionResult(ReconciliationState.UNKNOWN, decision, reason=decision.reason)
        if reservation is not ReservationState.ACQUIRED:
            code = (
                ExecutionDecisionCode.UNRESOLVED_DURABLE_INTENT
                if reservation is ReservationState.UNRESOLVED_INTENT
                else ExecutionDecisionCode.EXECUTION_RESERVATION_HELD
            )
            decision = ExecutionDecision(False, code, "Execution reservation was not acquired")
            return ExecutionResult(ReconciliationState.UNKNOWN, decision, reason=decision.reason)
        try:
            if context_provider is not None:
                try:
                    context = await context_provider()
                except Exception:
                    context = None
            result = await self._submit_reserved(
                intent,
                context,
                scope=scope,
                owner_id=owner_id,
                before_submit=before_submit,
            )
            if after_submit is not None:
                after_submit(result)
            return result
        finally:
            self._records.release_reservation(scope, owner_id)

    async def _submit_reserved(
        self,
        intent: ExecutionIntent,
        context: ExecutionContext | None,
        *,
        scope: str,
        owner_id: str,
        before_submit: Callable[[ExecutionDecision], None] | None,
    ) -> ExecutionResult:
        try:
            broker_positions = tuple(await self._gateway.get_positions())
            fresh_positions = PositionSnapshotAdapter.from_positions(broker_positions)
        except Exception:
            broker_positions = None
            fresh_positions = None
        effective_context = replace(context, open_positions=fresh_positions) if context is not None and fresh_positions is not None else None
        decision = ExecutionPolicy.evaluate(intent, effective_context)
        if not decision.allowed:
            state = ReconciliationState.UNKNOWN if broker_positions is None else ReconciliationState.REJECTED
            return ExecutionResult(state, decision, reason=decision.reason)
        reconciliation = await self.reconcile(intent, broker_positions)
        if reconciliation.state is not ReconciliationState.READY_TO_SUBMIT:
            return ExecutionResult(reconciliation.state, decision, reason=reconciliation.reason)
        if before_submit is not None:
            before_submit(decision)
        try:
            claim = self._records.try_claim_under_reservation(
                IntentRecord(intent.idempotency_key, IntentRecordStatus.PENDING),
                scope,
                owner_id,
            )
        except Exception:
            return ExecutionResult(ReconciliationState.UNKNOWN, decision, reason="Intent records unavailable")
        if claim is not ClaimState.CLAIMED:
            follow_up = await self.reconcile(intent)
            return ExecutionResult(follow_up.state, decision, reason=follow_up.reason)
        order = OrderRequest(
            symbol=intent.symbol.strip(),
            side=intent.side,
            quantity=intent.quantity,
            stop_loss=float(intent.stop_loss),
            take_profit=float(intent.take_profit),
            idempotency_key=intent.idempotency_key,
        )
        try:
            result = await self._gateway.submit_order(order)
            if not isinstance(result, OrderResult):
                raise TypeError("Gateway returned a malformed order result")
            status_value = result.status.value
            if status_value not in {"FILLED", "SUBMITTED", "REJECTED"}:
                raise ValueError("Gateway returned an indeterminate order status")
            if status_value in {"FILLED", "SUBMITTED"} and not result.order_id.strip():
                raise ValueError("Gateway accepted an order without broker identity")
        except Exception:
            self._transition(intent, IntentRecordStatus.UNKNOWN)
            log_unresolved_execution(idempotency_key=intent.idempotency_key, state="UNKNOWN", error_category="SUBMISSION_OUTCOME_UNKNOWN")
            return ExecutionResult(ReconciliationState.UNKNOWN, decision, reason="Submission outcome unknown")
        status = IntentRecordStatus.ACCEPTED if status_value in {"FILLED", "SUBMITTED"} else IntentRecordStatus.REJECTED
        if not self._transition(intent, status, result.order_id if status is IntentRecordStatus.ACCEPTED else None, result.transaction_id):
            return ExecutionResult(ReconciliationState.UNKNOWN, decision, result.order_id, "Outcome could not be persisted")
        state = ReconciliationState.ALREADY_EXECUTED if status is IntentRecordStatus.ACCEPTED else ReconciliationState.REJECTED
        return ExecutionResult(state, decision, result.order_id if status is IntentRecordStatus.ACCEPTED else None, "Order accepted" if status is IntentRecordStatus.ACCEPTED else "Broker rejected order")

    def _transition(self, intent: ExecutionIntent, status: IntentRecordStatus, order_id: str | None = None, transaction_id: str | None = None) -> bool:
        try:
            return self._records.transition(IntentRecord(intent.idempotency_key, status, order_id, transaction_id))
        except Exception:
            return False
