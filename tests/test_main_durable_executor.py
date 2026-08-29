"""Phase 6A integration coverage for the opt-in simulation execution path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

import main
from broker.types import AccountInfo, OrderResult, OrderSide, OrderStatus, Position
from config import Settings, settings
from execution.idempotency import build_execution_idempotency_key
from execution.models import ClaimState, IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore


@pytest.fixture(autouse=True)
def _restore_execution_settings(tmp_path):
    original = (
        settings.broker,
        settings.use_durable_executor,
        settings.intent_store_path,
        settings.environment,
    )
    settings.broker = "simulation"
    settings.use_durable_executor = False
    settings.intent_store_path = tmp_path / "intents.sqlite3"
    settings.environment = "development"
    yield
    (
        settings.broker,
        settings.use_durable_executor,
        settings.intent_store_path,
        settings.environment,
    ) = original


def _gateway() -> MagicMock:
    gateway = MagicMock()
    gateway.__aenter__ = AsyncMock(return_value=gateway)
    gateway.__aexit__ = AsyncMock(return_value=None)
    candle = MagicMock()
    candle.model_dump.return_value = {
        "time": pd.Timestamp("2026-08-29T12:00:00Z"),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 10.0,
        "ATR": 1.0,
    }
    gateway.get_candles = AsyncMock(return_value=[candle])
    gateway.get_account_info = AsyncMock(
        return_value=AccountInfo(account_id="SIMULATED", balance=10_000.0, currency="USD")
    )
    gateway.get_trade_history = AsyncMock(return_value=[])
    gateway.get_positions = AsyncMock(return_value=[])
    gateway.submit_order = AsyncMock(
        return_value=OrderResult(
            order_id="SIM-1", status=OrderStatus.FILLED, symbol="XAUUSD",
            side=OrderSide.BUY, volume=1.0,
        )
    )
    return gateway


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        symbol="XAUUSD", signal="BUY", position_size=1.0, stop_loss=99.0,
        take_profit=105.0, warnings=[], invalidation=None, is_valid=lambda: True,
    )


def _pipeline_patches(gateway: MagicMock):
    return (
        patch("main.get_gateway", return_value=gateway),
        patch("main.validate_market_data", return_value=True),
        patch("main.calculate_indicators", side_effect=lambda frame: frame),
        patch("main.detect_regime", return_value="TREND_UP"),
        patch("main.generate_trading_signal", return_value={
            "signal": "BUY", "confidence": 90, "intelligence": {"atr": 1.0},
        }),
        patch("main.approve_trade", return_value={
            "approved": True, "reason": "ok", "risk_percent": 0.5, "lot_size": 1.0,
        }),
        patch("main.TradePlanBuilder.build", return_value=_plan()),
    )


def _expected_key() -> str:
    return build_execution_idempotency_key(
        symbol="XAUUSD",
        side="BUY",
        volume=1.0,
        entry=101.0,
        stop_loss=99.0,
        take_profit=105.0,
        signal_time=pd.Timestamp("2026-08-29T12:00:00Z"),
    )


def _persist_record(
    status: IntentRecordStatus,
    *,
    order_id: str | None = None,
    transaction_id: str | None = None,
) -> None:
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    key = _expected_key()
    pending_order_id = order_id if status is IntentRecordStatus.PENDING else None
    pending_transaction_id = transaction_id if status is IntentRecordStatus.PENDING else None
    assert store.try_claim(
        IntentRecord(
            key,
            IntentRecordStatus.PENDING,
            pending_order_id,
            pending_transaction_id,
        )
    ) is ClaimState.CLAIMED
    if status is not IntentRecordStatus.PENDING:
        assert store.transition(IntentRecord(key, status, order_id, transaction_id)) is True


@pytest.mark.asyncio
async def test_default_setting_preserves_direct_submission_path() -> None:
    assert Settings(_env_file=None).use_durable_executor is False
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.AsyncTradeExecutor"
    ) as executor:
        await main.run()
    gateway.submit_order.assert_awaited_once()
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_simulation_uses_durable_executor_with_explicit_authorization() -> None:
    settings.use_durable_executor = True
    gateway = _gateway()
    store = MagicMock()
    store.get.return_value = None
    executor = MagicMock()
    executor.submit = AsyncMock(return_value=SimpleNamespace(state="accepted"))
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ) as store_type, patch("main.AsyncTradeExecutor", return_value=executor):
        await main.run()

    store_type.assert_called_once_with(settings.intent_store_path)
    intent, context = executor.submit.await_args.args
    assert intent.idempotency_key == store.get.call_args.args[0]
    assert context.execution_enabled is True
    assert context.dry_run is False
    assert context.broker == "simulation"
    assert context.environment == "development"
    assert context.account_id == "SIMULATED"
    assert context.approved_brokers == frozenset({"simulation"})
    assert context.approved_environments == frozenset({"development"})
    assert context.approved_accounts == frozenset({"SIMULATED"})
    assert context.approved_symbols == frozenset({"XAUUSD"})
    assert context.daily_state_authoritative is True
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("broker", ["deriv", "mt5"])
async def test_non_simulation_durable_execution_fails_before_gateway_creation(broker: str) -> None:
    settings.use_durable_executor = True
    settings.broker = broker
    with patch("main.get_gateway") as get_gateway:
        with pytest.raises(Exception, match="simulation broker only"):
            await main.run()
    get_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_store_initialization_failure_prevents_broker_submission() -> None:
    settings.use_durable_executor = True
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", side_effect=OSError("store unavailable")
    ):
        with pytest.raises(OSError, match="store unavailable"):
            await main.run()
    gateway.submit_order.assert_not_awaited()


def test_idempotency_key_is_deterministic_and_sensitive_to_intent() -> None:
    values = dict(
        symbol=" xauusd ", side="buy", volume=1.0, entry=101.0, stop_loss=99.0,
        take_profit=105.0, signal_time=pd.Timestamp("2026-08-29T12:00:00Z"),
    )
    first = build_execution_idempotency_key(**values)
    assert first == build_execution_idempotency_key(**values)
    assert first != build_execution_idempotency_key(**{**values, "volume": 2.0})


@pytest.mark.asyncio
async def test_complete_durable_path_preserves_key_and_blocks_duplicate() -> None:
    settings.use_durable_executor = True
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
        await main.run()

    gateway.submit_order.assert_awaited_once()
    order = gateway.submit_order.await_args.args[0]
    assert order.idempotency_key is not None
    record = SQLiteIntentRecordStore(settings.intent_store_path).get(order.idempotency_key)
    assert record is not None
    assert record.idempotency_key == order.idempotency_key
    assert record.status is IntentRecordStatus.ACCEPTED


@pytest.mark.asyncio
async def test_unknown_submission_is_persisted_and_not_blindly_retried() -> None:
    settings.use_durable_executor = True
    gateway = _gateway()
    gateway.submit_order.side_effect = TimeoutError("outcome unknown")
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
        await main.run()

    gateway.submit_order.assert_awaited_once()
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    with store._connect() as connection:
        key = connection.execute("SELECT idempotency_key FROM intent_records").fetchone()[0]
    assert store.get(key).status is IntentRecordStatus.UNKNOWN


@pytest.mark.asyncio
async def test_broker_open_same_symbol_position_blocks_durable_submission() -> None:
    settings.use_durable_executor = True
    gateway = _gateway()
    gateway.get_positions.return_value = [
        Position(
            position_id="SIM-existing", symbol="XAUUSD", side=OrderSide.SELL,
            volume=1.0, open_price=100.0,
        )
    ]
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,order_id",
    [
        (IntentRecordStatus.ACCEPTED, "SIM-prior"),
        (IntentRecordStatus.REJECTED, None),
    ],
)
async def test_terminal_record_survives_restart_without_resubmission(
    status: IntentRecordStatus, order_id: str | None
) -> None:
    settings.use_durable_executor = True
    _persist_record(status, order_id=order_id)
    gateway = _gateway()
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    gateway.submit_order.assert_not_awaited()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is status
    assert recovered.order_id == order_id


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_status", [IntentRecordStatus.UNKNOWN, IntentRecordStatus.PENDING])
async def test_uncertain_record_reconciles_exact_open_position_after_restart(
    prior_status: IntentRecordStatus,
) -> None:
    settings.use_durable_executor = True
    _persist_record(prior_status, order_id="SIM-prior")
    gateway = _gateway()
    gateway.get_positions.return_value = [
        Position(
            position_id="SIM-prior", symbol="XAUUSD", side=OrderSide.BUY,
            volume=1.0, open_price=101.0,
        )
    ]
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    gateway.submit_order.assert_not_awaited()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is IntentRecordStatus.ACCEPTED
    assert recovered.order_id == "SIM-prior"


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_status", [IntentRecordStatus.UNKNOWN, IntentRecordStatus.PENDING])
async def test_uncertain_record_without_exact_evidence_remains_unknown_after_restart(
    prior_status: IntentRecordStatus,
) -> None:
    settings.use_durable_executor = True
    _persist_record(prior_status)
    gateway = _gateway()
    gateway.get_positions.return_value = [
        Position(
            position_id="SIM-unrelated", symbol="XAUUSD", side=OrderSide.BUY,
            volume=1.0, open_price=101.0,
        )
    ]
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    gateway.submit_order.assert_not_awaited()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is IntentRecordStatus.UNKNOWN


@pytest.mark.asyncio
async def test_recovery_store_read_failure_fails_closed() -> None:
    settings.use_durable_executor = True
    gateway = _gateway()
    store = MagicMock()
    store.get.side_effect = OSError("read failed")
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ):
        with pytest.raises(OSError, match="read failed"):
            await main.run()
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_reconciliation_failure_keeps_unknown_and_fails_closed() -> None:
    settings.use_durable_executor = True
    _persist_record(IntentRecordStatus.UNKNOWN)
    gateway = _gateway()
    gateway.get_positions.side_effect = [[], RuntimeError("reconciliation unavailable")]
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    gateway.submit_order.assert_not_awaited()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is IntentRecordStatus.UNKNOWN
