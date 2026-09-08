"""Deterministic offline paper-contract lifecycle tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from broker.types import ClosedMarketObservation, ExecutionQuantity, ExecutionQuantityUnit, OrderSide, Timeframe
from execution.contract_lifecycle import ContractLifecycleState
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.paper_contract import PaperContractEngine, PaperContractExecutionGateway, PaperContractSpecification, PaperExitReason
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def obs(index, *, open_=100, high=101, low=99.5, close=100):
    opened = BASE + timedelta(minutes=5 * index)
    return ClosedMarketObservation(
        canonical_symbol="XAUUSD", source="fixture", provider_symbol="XAUUSD",
        timeframe=Timeframe.M5, candle_opened_at=opened,
        closed_at=opened + timedelta(minutes=5), open=open_, high=high, low=low, close=close,
    )


def intent(**changes):
    values = dict(
        symbol="XAUUSD", side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
        authorized_risk_amount=2, expected_loss_at_stop=1,
        quantity_risk_verified=True, entry=100, stop_loss=99, take_profit=102,
        idempotency_key="one", risk_approved=True,
    )
    values.update(changes)
    return ExecutionIntent(**values)


def context(**changes):
    values = dict(
        emergency_stop=False, daily_loss_percent=0, max_daily_loss_percent=3,
        daily_trade_count=0, max_daily_trades=5, open_positions=(), max_open_positions=1,
        used_idempotency_keys=frozenset(), execution_enabled=True, dry_run=False,
        broker="simulation", environment="paper", account_id="PAPER",
        approved_brokers=frozenset({"simulation"}), approved_environments=frozenset({"paper"}),
        approved_accounts=frozenset({"PAPER"}), approved_symbols=frozenset({"XAUUSD"}),
        daily_state_authoritative=True,
    )
    values.update(changes)
    return ExecutionContext(**values)


def opened(engine=None):
    engine = engine or PaperContractEngine()
    proposal = engine.authorize_and_propose(intent(), context(), obs(0), observed_at=obs(0).closed_at)
    return engine, proposal, engine.open(proposal)


def test_verified_decimal_semantics_and_maximum_loss():
    spec = PaperContractSpecification(fee_rate=Decimal("0.001"))
    engine = PaperContractEngine(spec)
    proposal = engine.authorize_and_propose(intent(authorized_risk_amount=2.0), context(), obs(0), observed_at=obs(0).closed_at)
    assert proposal.entry == Decimal("100")
    assert proposal.maximum_loss == Decimal("1.199")


def test_minimum_maximum_increment_and_precision():
    engine = PaperContractEngine(PaperContractSpecification(Decimal("0.10"), Decimal("1.00"), Decimal("0.01")))
    with pytest.raises(ValueError):
        engine.propose(idempotency_key="x", side=OrderSide.BUY, stake=Decimal("0.09"), stop_loss=Decimal("99"), take_profit=Decimal("102"), observation=obs(0))
    with pytest.raises(ValueError):
        engine.propose(idempotency_key="z", side=OrderSide.BUY, stake=Decimal("1.01"), stop_loss=Decimal("99"), take_profit=Decimal("102"), observation=obs(0))
    proposal = engine.propose(idempotency_key="y", side=OrderSide.BUY, stake=Decimal("0.11"), stop_loss=Decimal("99"), take_profit=Decimal("102"), observation=obs(0))
    assert proposal.stake == Decimal("0.11")


def test_proposal_binding_and_duplicate_open_prevention():
    engine, proposal, position = opened()
    assert position.proposal_id == proposal.proposal_id
    with pytest.raises(ValueError, match="already open"):
        engine.open(proposal)


def test_proposal_idempotency_preserves_original_economic_context():
    engine = PaperContractEngine()
    original = engine.propose(
        idempotency_key="stable", side=OrderSide.BUY, stake=Decimal("1"),
        stop_loss=Decimal("99"), take_profit=Decimal("102"), observation=obs(0),
    )
    assert engine.propose(
        idempotency_key="stable", side=OrderSide.BUY, stake=Decimal("1"),
        stop_loss=Decimal("99"), take_profit=Decimal("102"), observation=obs(0),
    ) is original
    with pytest.raises(ValueError, match="context mismatch"):
        engine.propose(
            idempotency_key="stable", side=OrderSide.BUY, stake=Decimal("1.01"),
            stop_loss=Decimal("99"), take_profit=Decimal("102"), observation=obs(0),
        )


def test_duplicate_close_prevention():
    engine, _, position = opened()
    assert engine.observe(position.contract_id, obs(1, high=102.5)) is not None
    with pytest.raises(ValueError, match="already closed"):
        engine.observe(position.contract_id, obs(2))


def test_stop_loss_and_take_profit_chronology():
    engine, _, position = opened()
    assert engine.observe(position.contract_id, obs(1, low=99.5, high=101)) is None
    closed = engine.observe(position.contract_id, obs(2, low=98.5, high=101))
    assert closed.reason is PaperExitReason.STOP_LOSS and closed.closed_at == obs(2).closed_at
    engine2, _, position2 = opened(PaperContractEngine())
    closed2 = engine2.observe(position2.contract_id, obs(1, high=102.5))
    assert closed2.reason is PaperExitReason.TAKE_PROFIT


def test_same_candle_ambiguity_is_conservative_and_no_lookahead():
    engine, _, position = opened()
    closed = engine.observe(position.contract_id, obs(1, high=103, low=98))
    assert closed.reason is PaperExitReason.STOP_LOSS


def test_gap_stop_uses_open_price_and_realized_pl():
    engine, _, position = opened()
    closed = engine.observe(position.contract_id, obs(1, open_=98, high=100, low=97, close=99))
    assert closed.exit_price == Decimal("98")
    assert closed.realized_profit == Decimal("-2")


def test_gap_up_target_uses_open_price():
    engine, _, position = opened()
    closed = engine.observe(position.contract_id, obs(1, open_=103, high=104, low=98, close=101))
    assert closed.reason is PaperExitReason.TAKE_PROFIT
    assert closed.exit_price == Decimal("103")


def test_fee_and_slippage_are_decimal_and_reduce_realized_profit():
    engine = PaperContractEngine(PaperContractSpecification(
        fee_rate=Decimal("0.001"), slippage=Decimal("0.10")
    ))
    _, _, position = opened(engine)
    assert engine._proposals["one"].maximum_loss == Decimal("1.29890")
    closed = engine.observe(position.contract_id, obs(1, high=103))
    assert closed.exit_price == Decimal("101.90")
    assert closed.fees == Decimal("0.20190")
    assert closed.realized_profit == Decimal("1.69810")


def test_nonchronological_observation_rejected():
    engine, _, position = opened()
    with pytest.raises(ValueError, match="chronological"):
        engine.observe(position.contract_id, obs(0))


def test_strategy_and_forced_exit():
    engine, _, position = opened()
    assert engine.observe(position.contract_id, obs(1, close=101), strategy_exit=True).reason is PaperExitReason.STRATEGY_EXIT
    engine2, _, position2 = opened(PaperContractEngine())
    assert engine2.replay(position2.contract_id, [obs(1), obs(2, close=101)], force_close=True).reason is PaperExitReason.END_OF_TEST


def test_reconciliation_tracks_closed_profit():
    engine, _, position = opened()
    assert engine.reconcile(position.contract_id).state is ContractLifecycleState.PURCHASED_OPEN
    closed = engine.observe(position.contract_id, obs(1, high=103))
    result = engine.reconcile(position.contract_id)
    assert result.close_id == closed.close_id and result.realized_profit == closed.realized_profit


@pytest.mark.parametrize("intent_change,context_change,reason", [
    ({"risk_approved": False}, {}, "RISK_NOT_APPROVED"),
    ({}, {"emergency_stop": True}, "EMERGENCY_STOP"),
    ({}, {"used_idempotency_keys": frozenset({"one"})}, "IDEMPOTENCY_KEY_REUSED"),
])
def test_existing_policy_rejections_are_preserved(intent_change, context_change, reason):
    engine = PaperContractEngine()
    with pytest.raises(ValueError, match=reason):
        engine.authorize_and_propose(intent(**intent_change), context(**context_change), obs(0), observed_at=obs(0).closed_at)


def test_forming_and_cross_symbol_observations_rejected():
    engine = PaperContractEngine()
    with pytest.raises(ValueError, match="not closed"):
        engine.authorize_and_propose(intent(), context(), obs(0), observed_at=BASE)
    with pytest.raises(ValueError, match="symbol"):
        engine.authorize_and_propose(
            intent(symbol="EURUSD"),
            context(approved_symbols=frozenset({"EURUSD"})),
            obs(0),
            observed_at=obs(0).closed_at,
        )


@pytest.mark.asyncio
async def test_executor_preserves_reservation_unresolved_and_position_safety(tmp_path):
    engine = PaperContractEngine()
    venue = PaperContractExecutionGateway(
        engine, obs(0), observed_at=obs(0).closed_at,
        authorized_risk_amount=Decimal("2"),
    )
    records = SQLiteIntentRecordStore(tmp_path / "paper.sqlite3")
    result = await AsyncTradeExecutor(venue, records).submit(intent(), context())
    assert result.state is ReconciliationState.ALREADY_EXECUTED
    assert result.order_id == "PAPER-C-one"
    duplicate = await AsyncTradeExecutor(venue, records).submit(intent(), context())
    assert duplicate.state is ReconciliationState.REJECTED
    assert len(engine._positions) == 1


@pytest.mark.asyncio
async def test_paper_notification_facts_are_downstream_only():
    class NotificationOnlyGateway:
        send = AsyncMock()

    gateway = NotificationOnlyGateway()
    events = JQENotificationEvents(NotificationService(gateway))
    await events.paper_event(kind="OPENED", facts={"Contract": "PAPER-C-one", "Execution": "OFFLINE"})
    notification = gateway.send.await_args.args[0]
    assert notification.title == "JQE PAPER POSITION OPENED"
    assert notification.facts["Execution"] == "OFFLINE"
    assert not hasattr(gateway, "submit_order")


@pytest.mark.asyncio
async def test_closed_and_blocked_paper_notifications():
    class NotificationOnlyGateway:
        send = AsyncMock()

    gateway = NotificationOnlyGateway()
    events = JQENotificationEvents(NotificationService(gateway))
    await events.paper_event(kind="CLOSED", facts={"Reason": "STOP_LOSS"})
    await events.paper_event(kind="BLOCKED", facts={"Decision": "EMERGENCY_STOP"})
    assert [call.args[0].title for call in gateway.send.await_args_list] == [
        "JQE PAPER POSITION CLOSED", "JQE PAPER TRADE BLOCKED"
    ]
