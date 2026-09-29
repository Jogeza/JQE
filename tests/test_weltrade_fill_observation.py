"""Offline confirmation and notification tests; never opens an MT5 session."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import main
from broker.types import Candle, OrderResult, OrderSide, OrderStatus, Position
from config import EmergencyStopState, settings
from data.watchlist import WatchlistStore
from execution.daily_instrument_guard import DailyInstrumentTradeGuard
from execution.persistence import SQLiteIntentRecordStore, SQLitePositionLedger
from execution.safety import DailyStateAuthority
import monitoring.weltrade_execution_supervisor as supervisor
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from notifications.telegram import render_telegram
from notifications.types import NotificationType
from risk.risk_controller import get_reconciled_daily_state
from tests.weltrade_stubs import WeltradeStubGateway


@pytest.fixture
def observed_fill(tmp_path):
    ledger = SQLitePositionLedger(tmp_path / "positions.sqlite3")
    records = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    position = Position(
        position_id="order-7", symbol="FX VOL 20", side=OrderSide.BUY,
        volume=0.01, open_price=101.0, stop_loss=99.0,
        opened_at=datetime(2026, 9, 28, 1, 0, tzinfo=timezone.utc),
    )
    gateway = SimpleNamespace(get_positions=AsyncMock(return_value=[position]),
                              get_price_point=AsyncMock(return_value=0.01))
    sink = SimpleNamespace(send=AsyncMock())
    events = JQENotificationEvents(NotificationService(sink))
    composition = SimpleNamespace(position_ledger=ledger, records=records)
    result = OrderResult(
        order_id="order-7", status=OrderStatus.FILLED,
        symbol=position.symbol, side=position.side, volume=position.volume,
        filled_price=position.open_price,
    )
    return composition, gateway, events, sink, result


async def _observe(harness, *, result=None):
    composition, gateway, events, _, original = harness
    await main._observe_confirmed_weltrade_fill(
        gateway=gateway, composition=composition,
        broker_result=result or original,
        symbol="FX VOL 20", side=OrderSide.BUY,
        order_id="order-7", expected_stop_loss=99.0,
        notification_events=events,
        require_position=True,
    )


@pytest.mark.asyncio
async def test_confirmed_fill_records_complete_ledger_and_notifies_once_on_retry(observed_fill):
    await _observe(observed_fill)
    await _observe(observed_fill)
    composition, _, _, sink, _ = observed_fill
    rows = composition.position_ledger.open_entries(broker="weltrade")
    assert len(rows) == 1
    assert (rows[0].symbol, rows[0].side, rows[0].volume) == ("FX VOL 20", "BUY", 0.01)
    assert (rows[0].entry_price, rows[0].stop_loss) == (101.0, 99.0)
    assert (rows[0].position_id, rows[0].order_id) == ("order-7", "order-7")
    assert rows[0].opened_at == "2026-09-28T01:00:00+00:00"
    assert rows[0].notification_claimed_at is not None
    sink.send.assert_awaited_once()
    assert sink.send.await_args.args[0].kind is NotificationType.POSITION_OPENED


@pytest.mark.asyncio
async def test_broker_rounded_stop_is_accepted(observed_fill):
    composition, gateway, events, sink, result = observed_fill
    gateway.get_positions.return_value = [gateway.get_positions.return_value[0].model_copy(
        update={"open_price": 36643.01, "stop_loss": 36592.82})]
    await main._observe_confirmed_weltrade_fill(
        gateway=gateway, composition=composition, broker_result=result,
        symbol="FX VOL 20", side=OrderSide.BUY, order_id="order-7",
        expected_stop_loss=36592.81714, notification_events=events,
        require_position=True,
    )
    assert composition.position_ledger.open_entries(broker="weltrade")[0].stop_loss == 36592.82
    sink.send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_stop", [36582.82, 36650.0])
async def test_genuinely_wrong_stop_still_halts(observed_fill, wrong_stop):
    composition, gateway, events, sink, result = observed_fill
    gateway.get_positions.return_value = [gateway.get_positions.return_value[0].model_copy(
        update={"open_price": 36643.01, "stop_loss": wrong_stop})]
    with pytest.raises(RuntimeError, match="supervisor must stop"):
        await main._observe_confirmed_weltrade_fill(
            gateway=gateway, composition=composition, broker_result=result,
            symbol="FX VOL 20", side=OrderSide.BUY, order_id="order-7",
            expected_stop_loss=36592.81714, notification_events=events,
            require_position=True,
        )
    assert composition.records.post_fill_integrity_halt() == "CONFIRMED_FILL_LEDGER_UNVERIFIED"
    assert not composition.position_ledger.open_entries(broker="weltrade")
    sink.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_opened_alert_uses_observed_fill_and_planned_risk_facts(observed_fill):
    composition, gateway, _, sink, _ = observed_fill
    composition.account = SimpleNamespace(trade_mode="demo")
    await main._observe_confirmed_weltrade_fill(
        gateway=gateway, composition=composition, broker_result=observed_fill[-1],
        symbol="FX VOL 20", side=OrderSide.BUY, order_id="order-7",
        expected_stop_loss=99.0, notification_events=observed_fill[2],
        require_position=True, timeframe="M5", take_profit=105.0,
        planned_risk_amount=0.5, planned_volume=0.01, balance=100.0,
    )
    event = sink.send.await_args.args[0]
    assert event.event_id == "OPEN:order-7"
    assert event.facts["Entry"] == "101.0"
    assert event.facts["Stop loss"] == "99.0"
    assert event.facts["Quantity"] == "0.01"
    assert event.facts["TP1"] == "105.0"
    assert event.facts["Risk at stop %"] == "0.500"
    assert event.facts["Account mode"] == "SIMULATION"
    assert event.simulated is True
    assert event.title == "JQE SIMULATION TRADE OPENED"
    assert "JQE DEMO TRADE OPENED" not in render_telegram(event)


@pytest.mark.asyncio
async def test_fixture_result_price_cannot_be_reported_as_broker_fill(observed_fill):
    composition, gateway, events, sink, result = observed_fill
    fixture_result = result.model_copy(update={"filled_price": 777.0})
    await main._observe_confirmed_weltrade_fill(
        gateway=gateway, composition=composition, broker_result=fixture_result,
        symbol="FX VOL 20", side=OrderSide.BUY, order_id="order-7",
        expected_stop_loss=99.0, notification_events=events, require_position=True,
    )
    alert = sink.send.await_args.args[0]
    assert alert.facts["Entry"] == "101.0"
    assert "777.0" not in render_telegram(alert)
    assert alert.simulated is True


@pytest.mark.asyncio
async def test_partial_fill_records_only_observed_filled_volume(observed_fill):
    composition, gateway, _, sink, result = observed_fill
    gateway.get_positions.return_value = [
        gateway.get_positions.return_value[0].model_copy(update={"volume": 0.004})
    ]
    partial = result.model_copy(update={"volume": 0.004, "raw": {"partial_fill": True}})
    await _observe(observed_fill, result=partial)
    assert composition.position_ledger.open_entries(broker="weltrade")[0].volume == 0.004
    sink.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_failure_keeps_ledger_and_is_not_retried(observed_fill):
    composition, _, _, sink, _ = observed_fill
    sink.send.side_effect = RuntimeError("transport offline")
    await _observe(observed_fill)
    await _observe(observed_fill)
    assert len(composition.position_ledger.open_entries(broker="weltrade")) == 1
    sink.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_ledger_failure_persists_halt_and_prevents_notification(observed_fill, monkeypatch):
    composition, _, _, sink, _ = observed_fill
    def fail(**_kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(composition.position_ledger, "record_confirmed_fill_once", fail)
    with pytest.raises(RuntimeError, match="supervisor must stop"):
        await _observe(observed_fill)
    assert composition.records.post_fill_integrity_halt() == "CONFIRMED_FILL_LEDGER_UNVERIFIED"
    sink.send.assert_not_awaited()


@pytest.fixture
def supervised_offline_cycle(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JQE_BROKER_EXECUTION_ENABLED", "true")
    for name, value in {
        "broker": "weltrade", "market_data_source": "broker",
        "broker_execution_enabled": True, "emergency_stop": EmergencyStopState.CLEAR,
        "default_candle_count": 250, "risk_percent": 0.5,
        "max_trades_daily": 5, "max_daily_trades_per_instrument": 20,
        "watchlist_store_path": tmp_path / "watchlist.sqlite3",
        "intent_store_path": tmp_path / "intents.sqlite3",
        "execution_position_ledger_path": tmp_path / "positions.sqlite3",
        "execution_safety_store_path": tmp_path / "safety.sqlite3",
        "daily_instrument_trade_store_path": tmp_path / "daily.sqlite3",
    }.items():
        monkeypatch.setattr(settings, name, value)
    watchlist = WatchlistStore(settings.watchlist_store_path, default_seeds=[])
    watchlist.add_item("FX VOL 20", "M1")
    gateway = WeltradeStubGateway(starting_balance=10_000.0)
    last = datetime.now(timezone.utc) - timedelta(minutes=2)
    candles = [Candle(
        time=last - timedelta(minutes=249 - i),
        open=100.0 + i * 0.05, high=101.0 + i * 0.05,
        low=99.0 + i * 0.05, close=100.5 + i * 0.05,
        volume=10.0, source="weltrade-test-double",
    ) for i in range(250)]
    monkeypatch.setattr(gateway, "get_candles", AsyncMock(return_value=candles))
    monkeypatch.setattr(main, "get_gateway", lambda _settings: gateway)
    monkeypatch.setattr(main, "generate_trading_signal", lambda *_args, **_kwargs: {
        "signal": "BUY", "confidence": 90, "intelligence": {"atr": 2.0},
    })
    monkeypatch.setattr(supervisor, "evaluate", lambda _settings: SimpleNamespace(
        daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
        reason_codes=("READ_ONLY_PREFLIGHT_NO_ORDER_INTENT",),
    ))
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", AsyncMock())
    sink = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(
        main, "notification_service_from_settings", lambda _settings: NotificationService(sink)
    )
    return gateway, sink


def _opened_alerts(sink):
    return [call.args[0] for call in sink.send.await_args_list
            if call.args[0].kind is NotificationType.POSITION_OPENED]


@pytest.mark.asyncio
async def test_supervisor_preflight_to_mock_fill_ledger_alert_and_counter(
    supervised_offline_cycle, monkeypatch,
):
    gateway, sink = supervised_offline_cycle
    actual_submit = gateway.submit_order
    submit = AsyncMock(side_effect=actual_submit)
    monkeypatch.setattr(gateway, "submit_order", submit)
    results = await supervisor.run_cycle_once()
    assert len(results) == 1 and results[0].status == "ORDER_ACCEPTED"
    submit.assert_awaited_once()
    request = submit.await_args.args[0]
    assert request.stop_loss > 0
    assert request.stop_loss < 101.0 + 249 * 0.05
    assert request.quantity.value > 0
    rows = SQLitePositionLedger(settings.execution_position_ledger_path).open_entries(broker="weltrade")
    assert len(rows) == 1 and rows[0].stop_loss == request.stop_loss
    assert rows[0].volume == request.quantity.value
    assert len(_opened_alerts(sink)) == 1
    guard = DailyInstrumentTradeGuard(settings.daily_instrument_trade_store_path, limit=20)
    assert guard.usage("weltrade:4242", "FX VOL 20").count == 1
    assert get_reconciled_daily_state()[1] == 0  # Global cap counts closed broker trades.
    assert SQLiteIntentRecordStore(settings.intent_store_path).list_unresolved() == ()
    repeated = await supervisor.run_cycle_once()
    assert repeated[0].status == "ALREADY_EXECUTED"
    submit.assert_awaited_once()
    assert len(SQLitePositionLedger(settings.execution_position_ledger_path).open_entries(broker="weltrade")) == 1
    assert len(_opened_alerts(sink)) == 1
    assert guard.usage("weltrade:4242", "FX VOL 20").count == 1
    assert get_reconciled_daily_state()[1] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["REJECTED", "TIMEOUT"])
async def test_rejection_and_timeout_consume_attempt_without_open_ledger_or_alert(
    supervised_offline_cycle, monkeypatch, outcome,
):
    gateway, sink = supervised_offline_cycle
    if outcome == "REJECTED":
        gateway.submit_order = AsyncMock(return_value=OrderResult(
            order_id="", status=OrderStatus.REJECTED, symbol="FX VOL 20",
            side=OrderSide.BUY, volume=0.01,
        ))
    else:
        gateway.submit_order = AsyncMock(side_effect=TimeoutError("broker response timed out"))
    results = await supervisor.run_cycle_once()
    assert len(results) == 1
    assert results[0].status in ("BROKER_REJECTED", "UNKNOWN")
    assert SQLitePositionLedger(settings.execution_position_ledger_path).open_entries(broker="weltrade") == ()
    assert _opened_alerts(sink) == []
    kinds = [call.args[0].kind for call in sink.send.await_args_list]
    assert (NotificationType.ORDER_REJECTED in kinds) is (outcome == "REJECTED")
    guard = DailyInstrumentTradeGuard(settings.daily_instrument_trade_store_path, limit=20)
    assert guard.usage("weltrade:4242", "FX VOL 20").count == 1
    assert get_reconciled_daily_state()[1] == 0


@pytest.mark.asyncio
async def test_failed_ledger_write_halts_supervisor_before_next_pair(
    supervised_offline_cycle, monkeypatch,
):
    gateway, sink = supervised_offline_cycle
    WatchlistStore(settings.watchlist_store_path).add_item("PAINX 400", "M5")
    actual_submit = gateway.submit_order
    submit = AsyncMock(side_effect=actual_submit)
    monkeypatch.setattr(gateway, "submit_order", submit)
    def fail_ledger(_self, **_kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(SQLitePositionLedger, "record_confirmed_fill_once", fail_ledger)
    with pytest.raises(RuntimeError, match="supervisor must stop"):
        await supervisor.run_cycle_once()
    submit.assert_awaited_once()
    assert _opened_alerts(sink) == []
    assert SQLiteIntentRecordStore(settings.intent_store_path).post_fill_integrity_halt() == (
        "CONFIRMED_FILL_LEDGER_UNVERIFIED"
    )
    with pytest.raises(RuntimeError, match="integrity halt"):
        await supervisor.run_cycle_once()
    submit.assert_awaited_once()
