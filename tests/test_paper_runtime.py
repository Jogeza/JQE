"""Offline continuous paper-runtime safety and orchestration tests."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from api.service import ApplicationService
from broker.types import ClosedMarketObservation, ExecutionQuantity, ExecutionQuantityUnit, OrderSide, Timeframe
from config import settings
from execution.paper_contract import PaperContractEngine
from execution.paper_runtime import ContinuousPaperRuntime, PaperEntry, PaperRuntimeStateStore
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def obs(index: int, *, open_=100, high=101, low=99.5, close=100):
    opened = BASE + timedelta(minutes=5 * index)
    return ClosedMarketObservation(
        canonical_symbol="XAUUSD", source="fixture", provider_symbol="XAUUSD",
        timeframe=Timeframe.M5, candle_opened_at=opened,
        closed_at=opened + timedelta(minutes=5), open=open_, high=high, low=low, close=close,
    )


def entry(*, emergency=False, symbol="XAUUSD"):
    intent = ExecutionIntent(
        symbol=symbol, side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
        authorized_risk_amount=2.0, expected_loss_at_stop=1.0,
        quantity_risk_verified=True, entry=100, stop_loss=99, take_profit=102,
        idempotency_key="runtime-one", risk_approved=True,
    )
    context = ExecutionContext(
        emergency_stop=emergency, daily_loss_percent=0, max_daily_loss_percent=3,
        daily_trade_count=0, max_daily_trades=5, open_positions=(), max_open_positions=1,
        used_idempotency_keys=frozenset(), execution_enabled=True, dry_run=False,
        broker="simulation", environment="paper", account_id="PAPER",
        approved_brokers=frozenset({"simulation"}), approved_environments=frozenset({"paper"}),
        approved_accounts=frozenset({"PAPER"}), approved_symbols=frozenset({"XAUUSD"}),
        daily_state_authoritative=True,
    )
    return PaperEntry(intent, context)


def runtime(tmp_path, source, decide, **changes):
    values = dict(
        observation_source=source, decision_builder=decide,
        intent_records=SQLiteIntentRecordStore(tmp_path / "intents.sqlite3"),
        state_store=PaperRuntimeStateStore(tmp_path / "runtime.sqlite3"),
        symbols=("XAUUSD",), enabled=True, runtime_mode="paper_continuous",
        poll_seconds=1, max_backoff_seconds=2,
        clock=lambda: BASE + timedelta(days=1),
    )
    values.update(changes)
    return ContinuousPaperRuntime(**values)


def test_runtime_disabled_by_default_and_explicit_opt_in(tmp_path):
    assert settings.paper_runtime_enabled is False
    assert settings.runtime_mode == "disabled"
    with pytest.raises(ValueError, match="explicit opt-in"):
        runtime(tmp_path, AsyncMock(return_value=[obs(0)]), AsyncMock(return_value=None), enabled=False)


@pytest.mark.asyncio
async def test_first_duplicate_and_old_candles_are_deduplicated(tmp_path):
    source = AsyncMock(return_value=[obs(1)])
    decide = AsyncMock(return_value=None)
    subject = runtime(tmp_path, source, decide)
    first = await subject.run_once()
    assert first.cycles_completed == 1 and first.last_action == "NO_SIGNAL"
    assert (await subject.run_once()).last_action == "DUPLICATE_IGNORED"
    source.return_value = [obs(0)]
    assert (await subject.run_once()).last_action == "OLD_IGNORED"
    decide.assert_awaited_once()


@pytest.mark.asyncio
async def test_forming_candle_and_market_failure_fail_closed(tmp_path):
    subject = runtime(
        tmp_path, AsyncMock(return_value=[obs(0)]), AsyncMock(return_value=None), clock=lambda: BASE
    )
    assert (await subject.run_once()).last_error == "ValueError"
    failing = runtime(tmp_path / "other", AsyncMock(side_effect=OSError("offline")), AsyncMock())
    assert (await failing.run_once()).last_error == "OSError"


@pytest.mark.asyncio
async def test_out_of_order_batch_is_rejected(tmp_path):
    subject = runtime(
        tmp_path, AsyncMock(return_value=[obs(1), obs(0)]), AsyncMock(return_value=None)
    )
    assert (await subject.run_once()).last_error == "ValueError"


@pytest.mark.asyncio
async def test_valid_entry_uses_executor_and_opens_once(tmp_path):
    subject = runtime(tmp_path, AsyncMock(return_value=[obs(0)]), AsyncMock(return_value=entry()))
    heartbeat = await subject.run_once()
    assert heartbeat.last_action == "POSITION_OPENED"
    assert heartbeat.open_paper_positions == 1
    assert len(subject.engine._positions) == 1


@pytest.mark.asyncio
async def test_policy_emergency_and_symbol_rejections_do_not_open(tmp_path):
    for name, proposed in (("emergency", entry(emergency=True)), ("symbol", entry(symbol="EURUSD"))):
        subject = runtime(tmp_path / name, AsyncMock(return_value=[obs(0)]), AsyncMock(return_value=proposed))
        heartbeat = await subject.run_once()
        assert heartbeat.last_action.startswith("BLOCKED:")
        assert heartbeat.open_paper_positions == 0


@pytest.mark.asyncio
async def test_open_position_updates_then_take_profit_closes_and_reconciles(tmp_path):
    source = AsyncMock(return_value=[obs(0)])
    decide = AsyncMock(side_effect=[entry(), None, None])
    subject = runtime(tmp_path, source, decide)
    await subject.run_once()
    source.return_value = [obs(1, high=101)]
    assert (await subject.run_once()).open_paper_positions == 1
    source.return_value = [obs(2, high=103)]
    heartbeat = await subject.run_once()
    assert heartbeat.last_action == "POSITION_CLOSED"
    assert heartbeat.open_paper_positions == 0
    contract_id = next(iter(subject.engine._positions))
    assert subject.engine.reconcile(contract_id).state.value == "CLOSED"


@pytest.mark.asyncio
async def test_notification_failure_is_downstream_only(tmp_path):
    gateway = AsyncMock()
    gateway.send.side_effect = RuntimeError("telegram unavailable")
    events = JQENotificationEvents(NotificationService(gateway))
    subject = runtime(
        tmp_path, AsyncMock(return_value=[obs(0)]), AsyncMock(return_value=entry()),
        notifications=events,
    )
    heartbeat = await subject.run_once()
    assert heartbeat.last_action == "POSITION_OPENED"
    assert heartbeat.notification_state == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_run_once_lifecycle_and_explicit_shutdown(tmp_path):
    subject = runtime(tmp_path, AsyncMock(return_value=[obs(0)]), AsyncMock(return_value=None))
    heartbeat = await subject.run(once=True)
    assert heartbeat.running is False and heartbeat.shutdown_state == "STOPPED"
    assert heartbeat.cycles_completed == 1
    subject2 = runtime(tmp_path / "stop", AsyncMock(), AsyncMock())
    subject2.request_stop()
    assert (await subject2.run()).cycles_completed == 0


def test_restart_with_open_position_fails_closed(tmp_path):
    store = PaperRuntimeStateStore(tmp_path / "runtime.sqlite3")
    heartbeat = store.read()
    store.publish(heartbeat.__class__(open_paper_positions=1))
    with pytest.raises(RuntimeError, match="restart blocked"):
        ContinuousPaperRuntime(
            observation_source=AsyncMock(), decision_builder=AsyncMock(),
            intent_records=SQLiteIntentRecordStore(tmp_path / "intents.sqlite3"),
            state_store=store, symbols=("XAUUSD",), enabled=True,
            runtime_mode="paper_continuous",
        )


def test_api_runtime_telemetry_is_read_only(tmp_path, monkeypatch):
    path = tmp_path / "runtime.sqlite3"
    store = PaperRuntimeStateStore(path)
    heartbeat = store.read().__class__(cycles_completed=7, last_action="NO_SIGNAL")
    store.publish(heartbeat)
    monkeypatch.setattr(settings, "paper_runtime_state_path", path)
    response = ApplicationService().get_paper_runtime_status()
    assert response.cycles_completed == 7 and response.broker_execution_enabled is False
    assert store.read().cycles_completed == 7
