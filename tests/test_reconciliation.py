"""Tests for broker-neutral correlation observations."""

import pytest

from broker.types import OrderSide, Position
from execution.reconciliation import (
    BrokerReconciliationState,
    CorrelationStrength,
    DerivReconciliationAdapter,
    MT5ReconciliationAdapter,
    classify_observation,
)


def test_unavailable_broker_is_distinct() -> None:
    assert classify_observation(broker_available=False, symbol_match=False).state is BrokerReconciliationState.UNAVAILABLE


def test_symbol_match_is_ambiguous_without_intent_identity() -> None:
    assert classify_observation(broker_available=True, symbol_match=True).state is BrokerReconciliationState.AMBIGUOUS


def test_absence_is_not_confirmed_non_execution() -> None:
    assert classify_observation(broker_available=True, symbol_match=False).state is BrokerReconciliationState.AMBIGUOUS


class Gateway:
    def __init__(self, positions=(), history=()) -> None:
        self.positions = positions
        self.history = history

    async def get_positions(self):
        return list(self.positions)

    async def get_trade_history(self, count=100):
        return list(self.history)


def _position() -> Position:
    return Position(position_id="contract-1", symbol="R_100", side=OrderSide.BUY, volume=1, open_price=10, transaction_id="txn-1")


@pytest.mark.asyncio
async def test_deriv_adapter_confirms_exact_identifiers() -> None:
    adapter = DerivReconciliationAdapter(Gateway([_position()]))
    contract_result = await adapter.reconcile(contract_id="contract-1", idempotency_key="jqe-1")
    transaction_result = await adapter.reconcile(transaction_id="txn-1", idempotency_key="jqe-1")
    assert contract_result.state is BrokerReconciliationState.CONFIRMED_MATCH
    assert contract_result.evidence.correlation_strength is CorrelationStrength.EXACT
    assert contract_result.evidence.idempotency_key == "jqe-1"
    assert transaction_result.state is BrokerReconciliationState.CONFIRMED_MATCH


@pytest.mark.asyncio
async def test_deriv_adapter_keeps_symbol_match_ambiguous() -> None:
    result = await DerivReconciliationAdapter(Gateway([_position()])).reconcile(symbol="R_100")
    assert result.state is BrokerReconciliationState.AMBIGUOUS
    assert result.evidence.correlation_strength is CorrelationStrength.AMBIGUOUS


@pytest.mark.asyncio
async def test_deriv_absence_does_not_become_exact() -> None:
    result = await DerivReconciliationAdapter(Gateway()).reconcile(contract_id="missing")
    assert result.state is BrokerReconciliationState.AMBIGUOUS
    assert result.evidence.correlation_strength is CorrelationStrength.AMBIGUOUS


class MT5Gateway(Gateway):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["order_id", "deal_id", "position_id"])
async def test_mt5_known_broker_identifier_is_explicit_exact_evidence(field: str) -> None:
    item = type("MT5Record", (), {field: "mt5-1", "symbol": "EURUSD"})()
    result = await MT5ReconciliationAdapter(MT5Gateway([item])).reconcile(**{field: "mt5-1"}, idempotency_key="jqe-1")
    assert result.state is BrokerReconciliationState.CONFIRMED_MATCH
    assert result.evidence.correlation_strength is CorrelationStrength.EXACT


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"symbol": "EURUSD"},
    {"request_id": "request-1"},
])
async def test_mt5_non_identity_evidence_is_ambiguous(kwargs: dict[str, str]) -> None:
    item = type("MT5Record", (), {"symbol": "EURUSD", "magic": 20260802, "comment": "JQE"})()
    result = await MT5ReconciliationAdapter(MT5Gateway([item])).reconcile(**kwargs)
    assert result.state is BrokerReconciliationState.AMBIGUOUS
    assert result.evidence.correlation_strength is CorrelationStrength.AMBIGUOUS


@pytest.mark.asyncio
async def test_mt5_empty_successful_query_is_absent() -> None:
    result = await MT5ReconciliationAdapter(MT5Gateway()).reconcile()
    assert result.state is BrokerReconciliationState.CONFIRMED_ABSENCE
    assert result.evidence.correlation_strength is CorrelationStrength.ABSENT


@pytest.mark.asyncio
async def test_mt5_failure_is_unavailable() -> None:
    class Failing(MT5Gateway):
        async def get_positions(self):
            raise RuntimeError("unavailable")

    result = await MT5ReconciliationAdapter(Failing()).reconcile()
    assert result.state is BrokerReconciliationState.UNAVAILABLE
    assert result.evidence.correlation_strength is CorrelationStrength.UNAVAILABLE
