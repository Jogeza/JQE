"""Startup crash-recovery invariants for durable execution intents."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderSide
from execution.models import ClaimState, IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore
from execution.reconciliation import (
    BrokerReconciliationResult,
    BrokerReconciliationState,
    CorrelationEvidence,
    CorrelationStrength,
)
from execution.recovery import StartupRecoveryOutcome, StartupRecoveryService


def _record(
    key: str,
    status: IntentRecordStatus,
    *,
    broker: str = "simulation",
    account_id: str = "SIMULATED",
    order_id: str | None = None,
) -> IntentRecord:
    return IntentRecord(
        idempotency_key=key,
        status=status,
        order_id=order_id,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        quantity=ExecutionQuantity(
            value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS
        ),
        entry=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        authorized_risk_amount=1.0,
        expected_loss_at_stop=1.0,
        broker=broker,
        account_id=account_id,
    )


def _evidence(state: BrokerReconciliationState) -> BrokerReconciliationResult:
    evidence = CorrelationEvidence(
        broker="simulation",
        correlation_strength=(
            CorrelationStrength.EXACT
            if state is BrokerReconciliationState.CONFIRMED_MATCH
            else CorrelationStrength.ABSENT
            if state is BrokerReconciliationState.CONFIRMED_ABSENCE
            else CorrelationStrength.UNAVAILABLE
            if state is BrokerReconciliationState.UNAVAILABLE
            else CorrelationStrength.AMBIGUOUS
        ),
        order_id="SIM-1" if state is BrokerReconciliationState.CONFIRMED_MATCH else None,
    )
    return BrokerReconciliationResult(state, state.value, evidence=evidence)


def _service(store, reconciler) -> StartupRecoveryService:
    return StartupRecoveryService(
        store, reconciler, broker="simulation", account_id="SIMULATED"
    )


def _reconciler(*, result=None, error=None):
    method = AsyncMock(return_value=result, side_effect=error)
    return SimpleNamespace(reconcile=method), method


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN])
async def test_unresolved_record_is_reconstructed_and_exact_evidence_accepts(
    tmp_path, status
) -> None:
    path = tmp_path / "intents.sqlite3"
    store = SQLiteIntentRecordStore(path)
    assert store.try_claim(_record("key", status)) is ClaimState.CLAIMED
    reconciler, _ = _reconciler(
        result=_evidence(BrokerReconciliationState.CONFIRMED_MATCH)
    )

    summary = await _service(store, reconciler).recover()

    assert summary.results[0].outcome is StartupRecoveryOutcome.RESOLVED_ACCEPTED
    assert store.get("key").status is IntentRecordStatus.ACCEPTED
    assert store.get("key").order_id == "SIM-1"
    assert SQLiteIntentRecordStore(path).get("key").status is IntentRecordStatus.ACCEPTED


@pytest.mark.asyncio
async def test_explicit_confirmed_absence_resolves_rejected(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.try_claim(_record("key", IntentRecordStatus.UNKNOWN)) is ClaimState.CLAIMED
    reconciler, _ = _reconciler(
        result=_evidence(BrokerReconciliationState.CONFIRMED_ABSENCE)
    )
    summary = await _service(store, reconciler).recover()
    assert summary.results[0].outcome is StartupRecoveryOutcome.RESOLVED_REJECTED
    assert store.get("key").status is IntentRecordStatus.REJECTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,outcome",
    [
        (BrokerReconciliationState.AMBIGUOUS, StartupRecoveryOutcome.REMAINS_UNKNOWN),
        (
            BrokerReconciliationState.UNAVAILABLE,
            StartupRecoveryOutcome.RECONCILIATION_UNAVAILABLE,
        ),
    ],
)
async def test_unproven_outcome_remains_unknown(tmp_path, state, outcome) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.try_claim(_record("key", IntentRecordStatus.PENDING)) is ClaimState.CLAIMED
    reconciler, _ = _reconciler(result=_evidence(state))
    summary = await _service(store, reconciler).recover()
    assert summary.results[0].outcome is outcome
    assert store.get("key").status is IntentRecordStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconciliation_exception_leaves_record_unresolved(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.try_claim(_record("key", IntentRecordStatus.UNKNOWN)) is ClaimState.CLAIMED
    reconciler, _ = _reconciler(error=RuntimeError("offline"))
    summary = await _service(store, reconciler).recover()
    assert summary.results[0].outcome is StartupRecoveryOutcome.RECONCILIATION_ERROR
    assert store.get("key").status is IntentRecordStatus.UNKNOWN


@pytest.mark.asyncio
async def test_malformed_and_scope_mismatch_fail_closed_without_reconciliation(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.try_claim(IntentRecord("malformed", IntentRecordStatus.PENDING)) is ClaimState.CLAIMED
    assert store.try_claim(
        _record("other-account", IntentRecordStatus.UNKNOWN, account_id="OTHER")
    ) is ClaimState.CLAIMED
    reconciler, reconcile = _reconciler()
    summary = await _service(store, reconciler).recover()
    assert [item.outcome for item in summary.results] == [
        StartupRecoveryOutcome.MALFORMED_RECORD,
        StartupRecoveryOutcome.SCOPE_MISMATCH,
    ]
    assert summary.unresolved_count == 2
    reconcile.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_records_terminal_rows_and_idempotency(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    for record in (
        _record("pending", IntentRecordStatus.PENDING),
        _record("unknown", IntentRecordStatus.UNKNOWN),
        _record("accepted", IntentRecordStatus.ACCEPTED),
        _record("rejected", IntentRecordStatus.REJECTED),
    ):
        assert store.try_claim(record) is ClaimState.CLAIMED
    reconciler, reconcile = _reconciler(
        result=_evidence(BrokerReconciliationState.CONFIRMED_MATCH)
    )
    first = await _service(store, reconciler).recover()
    second = await _service(store, reconciler).recover()
    assert len(first.results) == 2
    assert second.results == ()
    assert reconcile.await_count == 2
    assert store.list_unresolved() == ()


@pytest.mark.asyncio
async def test_recovery_interface_has_no_submission_capability(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.try_claim(_record("key", IntentRecordStatus.UNKNOWN)) is ClaimState.CLAIMED
    reconciler, _ = _reconciler(result=_evidence(BrokerReconciliationState.AMBIGUOUS))
    gateway = AsyncMock()
    await _service(store, reconciler).recover()
    gateway.submit_order.assert_not_awaited()
