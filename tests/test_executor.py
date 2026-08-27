"""Focused tests for the non-live async execution boundary."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
import asyncio

from broker.types import OrderRequest, OrderResult, OrderSide, OrderStatus, Position
from execution.executor import (
    AsyncTradeExecutor,
    IntentRecord,
    IntentRecordStatus,
    ClaimState,
    ReconciliationState,
)
from execution.policy import ExecutionContext, ExecutionDecisionCode, ExecutionIntent


def _intent(**overrides: object) -> ExecutionIntent:
    return replace(
        ExecutionIntent("EURUSD", OrderSide.BUY, 1.0, 100.0, 99.0, 101.0, "key-1", True),
        **overrides,
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        False, 0.0, 3.0, 0, 5, (), 3, frozenset(),
        execution_enabled=True,
        dry_run=False,
        broker="test",
        environment="demo",
        account_id="demo-account",
        approved_brokers=frozenset({"test"}),
        approved_environments=frozenset({"demo"}),
        approved_accounts=frozenset({"demo-account"}),
        approved_symbols=frozenset({"EURUSD"}),
        daily_state_authoritative=True,
    )


class Records:
    def __init__(self) -> None:
        self.values: dict[str, IntentRecord] = {}

    def get(self, key: str) -> IntentRecord | None:
        return self.values.get(key)

    def try_claim(self, record: IntentRecord) -> ClaimState:
        if record.idempotency_key in self.values:
            return ClaimState.ALREADY_EXISTS
        self.values[record.idempotency_key] = record
        return ClaimState.CLAIMED

    def transition(self, record: IntentRecord) -> bool:
        current = self.values.get(record.idempotency_key)
        if current is None:
            return False
        allowed = {
            IntentRecordStatus.PENDING: {IntentRecordStatus.ACCEPTED, IntentRecordStatus.REJECTED, IntentRecordStatus.UNKNOWN},
            IntentRecordStatus.UNKNOWN: {IntentRecordStatus.ACCEPTED, IntentRecordStatus.REJECTED, IntentRecordStatus.UNKNOWN},
            IntentRecordStatus.ACCEPTED: {IntentRecordStatus.ACCEPTED},
            IntentRecordStatus.REJECTED: {IntentRecordStatus.REJECTED},
        }
        if record.status not in allowed[current.status]:
            return False
        self.values[record.idempotency_key] = record
        return True


class Gateway:
    def __init__(self, positions: object = ()) -> None:
        self.positions = positions
        self.submissions: list[OrderRequest] = []
        self.fail_positions = False
        self.fail_submit = False

    async def get_positions(self) -> list[Position]:
        if self.fail_positions:
            raise RuntimeError("broker unavailable")
        return self.positions  # type: ignore[return-value]

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self.submissions.append(order)
        if self.fail_submit:
            raise TimeoutError("unknown outcome")
        return OrderResult(
            order_id="order-1",
            status=OrderStatus.FILLED,
            symbol="EURUSD",
            side=OrderSide.BUY,
            volume=1.0,
        )


@pytest.mark.asyncio
async def test_no_position_reconciles_ready_and_submits_once() -> None:
    gateway, records = Gateway(), Records()
    executor = AsyncTradeExecutor(gateway, records)

    result = await executor.submit(_intent(), _context())

    assert result.state is ReconciliationState.ALREADY_EXECUTED
    assert len(gateway.submissions) == 1
    assert gateway.submissions[0].idempotency_key == "key-1"
    assert records.values["key-1"].status is IntentRecordStatus.ACCEPTED


@pytest.mark.asyncio
@pytest.mark.parametrize("status,state", [(IntentRecordStatus.ACCEPTED, ReconciliationState.UNKNOWN), (IntentRecordStatus.PENDING, ReconciliationState.PENDING), (IntentRecordStatus.REJECTED, ReconciliationState.REJECTED), (IntentRecordStatus.UNKNOWN, ReconciliationState.UNKNOWN)])
async def test_recorded_intent_prevents_resubmission(status: IntentRecordStatus, state: ReconciliationState) -> None:
    gateway, records = Gateway(), Records()
    records.values["key-1"] = IntentRecord("key-1", status)
    executor = AsyncTradeExecutor(gateway, records)

    result = await executor.submit(_intent(), _context())

    assert result.state is state
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_existing_position_blocks_submission() -> None:
    gateway, records = Gateway([Position(position_id="p", symbol=" eurusd ", side=OrderSide.SELL, volume=1, open_price=100)]) , Records()
    executor = AsyncTradeExecutor(gateway, records)
    result = await executor.submit(_intent(), _context())
    assert result.state is ReconciliationState.REJECTED
    assert result.decision.code is ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_unknown_symbol_match_is_ambiguous_not_proof_of_execution() -> None:
    gateway, records = Gateway([Position(position_id="p", symbol="EURUSD", side=OrderSide.BUY, volume=1, open_price=100)]), Records()
    records.values["key-1"] = IntentRecord("key-1", IntentRecordStatus.UNKNOWN)
    result = await AsyncTradeExecutor(gateway, records).submit(_intent(), _context())
    assert result.state is ReconciliationState.REJECTED
    assert result.decision.code is ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_broker_failure_and_malformed_state_are_unknown() -> None:
    for positions, fail in [(object(), False), ((), True)]:
        gateway, records = Gateway(positions), Records()
        gateway.fail_positions = fail
        executor = AsyncTradeExecutor(gateway, records)
        result = await executor.submit(_intent(), _context())
        assert result.state is ReconciliationState.UNKNOWN
        assert gateway.submissions == []


@pytest.mark.asyncio
async def test_unknown_submission_is_not_retried_blindly() -> None:
    gateway, records = Gateway(), Records()
    gateway.fail_submit = True
    executor = AsyncTradeExecutor(gateway, records)
    first = await executor.submit(_intent(), _context())
    second = await executor.submit(_intent(), _context())
    assert first.state is ReconciliationState.UNKNOWN
    assert second.state is ReconciliationState.UNKNOWN
    assert records.values["key-1"].status is IntentRecordStatus.UNKNOWN
    assert len(gateway.submissions) == 1


@pytest.mark.asyncio
async def test_malformed_result_after_submission_is_unknown_and_blocks_retry() -> None:
    gateway, records = Gateway(), Records()
    gateway.submit_order = AsyncMock(return_value=object())  # type: ignore[method-assign]
    executor = AsyncTradeExecutor(gateway, records)

    first = await executor.submit(_intent(), _context())
    second = await executor.submit(_intent(), _context())

    assert first.state is ReconciliationState.UNKNOWN
    assert second.state is ReconciliationState.UNKNOWN
    assert records.values["key-1"].status is IntentRecordStatus.UNKNOWN
    gateway.submit_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_injected_reconciler_is_used_for_uncertain_intent() -> None:
    from execution.reconciliation import BrokerReconciliationResult, BrokerReconciliationState

    gateway, records = Gateway(), Records()
    records.values["key-1"] = IntentRecord("key-1", IntentRecordStatus.UNKNOWN, "broker-1")
    reconciler = AsyncMock()
    reconciler.reconcile.return_value = BrokerReconciliationResult(
        BrokerReconciliationState.CONFIRMED_MATCH, "Exact broker identifier matched"
    )

    result = await AsyncTradeExecutor(gateway, records, reconciler).submit(_intent(), _context())

    assert result.state is ReconciliationState.ALREADY_EXECUTED
    reconciler.reconcile.assert_awaited_once_with(
        order_id="broker-1",
        transaction_id=None,
        symbol="EURUSD",
        idempotency_key="key-1",
    )
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_fresh_broker_positions_override_stale_caller_snapshot() -> None:
    gateway = Gateway([Position(position_id="p", symbol="EURUSD", side=OrderSide.BUY, volume=1, open_price=100)])
    result = await AsyncTradeExecutor(gateway, Records()).submit(_intent(), _context())
    assert result.decision.code is ExecutionDecisionCode.DUPLICATE_SYMBOL_POSITION
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_policy_rejection_prevents_gateway_calls() -> None:
    gateway, records = Gateway(), Records()
    executor = AsyncTradeExecutor(gateway, records)
    result = await executor.submit(_intent(risk_approved=False), _context())
    assert result.decision.code is ExecutionDecisionCode.RISK_NOT_APPROVED
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_recovery_mode_missing_intent_fails_closed() -> None:
    class RecoveryRecords(Records):
        recovery_mode = True

    gateway, records = Gateway(), RecoveryRecords()
    result = await AsyncTradeExecutor(gateway, records).submit(_intent(), _context())
    assert result.state is ReconciliationState.UNKNOWN
    assert gateway.submissions == []


@pytest.mark.asyncio
async def test_restart_and_concurrent_attempts_do_not_duplicate() -> None:
    gateway, records = Gateway(), Records()
    first, second = await asyncio.gather(
        AsyncTradeExecutor(gateway, records).submit(_intent(), _context()),
        AsyncTradeExecutor(gateway, records).submit(_intent(), _context()),
    )
    assert len(gateway.submissions) == 1
    assert first.state is ReconciliationState.ALREADY_EXECUTED or second.state is ReconciliationState.ALREADY_EXECUTED
    assert {first.state, second.state} <= {ReconciliationState.ALREADY_EXECUTED, ReconciliationState.UNKNOWN}

    restarted = AsyncTradeExecutor(gateway, records)
    result = await restarted.submit(_intent(), _context())
    assert result.state is ReconciliationState.UNKNOWN
    assert len(gateway.submissions) == 1
