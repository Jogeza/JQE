"""Phase 6A integration coverage for the opt-in simulation execution path."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

import main
from broker.types import (
    ExecutionQuantity,
    ExecutionQuantityUnit,
    AccountInfo,
    OrderResult,
    OrderSide,
    OrderStatus,
    Position,
    TradeHistoryCompleteness,
    TradeHistorySnapshot,
)
from config import EmergencyStopState, Settings, settings
from core.exceptions import ConfigurationError, ExecutionError
from execution.idempotency import build_execution_idempotency_key
from execution.models import ClaimState, IntentRecord, IntentRecordStatus, ReservationState
from execution.persistence import SQLiteIntentRecordStore
from execution.executor import ExecutionResult, ReconciliationState
from execution.policy import ExecutionDecision, ExecutionDecisionCode
from execution.safety import (
    ExecutionAuthorization,
    RiskEvaluationState,
    SQLiteExecutionSafetyStore,
)


@pytest.fixture(autouse=True)
def _restore_execution_settings(tmp_path):
    original = (
        settings.broker,
        settings.intent_store_path,
        settings.environment,
        settings.emergency_stop,
        settings.execution_safety_store_path,
    )
    settings.broker = "simulation"
    settings.intent_store_path = tmp_path / "intents.sqlite3"
    settings.environment = "development"
    settings.emergency_stop = EmergencyStopState.CLEAR
    settings.execution_safety_store_path = tmp_path / "execution-safety.sqlite3"
    yield
    (
        settings.broker,
        settings.intent_store_path,
        settings.environment,
        settings.emergency_stop,
        settings.execution_safety_store_path,
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

    async def complete_history(*, start, end, count):
        return TradeHistorySnapshot(
            trades=[],
            completeness=TradeHistoryCompleteness.COMPLETE,
            coverage_start=start,
            coverage_end=end,
        )

    gateway.get_trade_history_snapshot = AsyncMock(side_effect=complete_history)
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
            "approved": True, "reason": "ok", "risk_percent": 0.02, "authorized_risk_amount": 2.0,
        }),
        patch("main.TradePlanBuilder.build", return_value=_plan()),
    )


def _expected_key() -> str:
    return build_execution_idempotency_key(
        symbol="XAUUSD",
        side="BUY",
        quantity=ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
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
async def test_obsolete_durable_switch_cannot_restore_direct_submission_path() -> None:
    assert not hasattr(Settings(_env_file=None), "use_durable_executor")
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    executor = MagicMock()
    executor.submit = AsyncMock(return_value=SimpleNamespace(
        state="accepted", decision=SimpleNamespace(allowed=True, code=ExecutionDecisionCode.ALLOWED)
    ))
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.AsyncTradeExecutor", return_value=executor
    ):
        await main.run()
    gateway.submit_order.assert_not_awaited()
    executor.submit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("broker", ["deriv", "mt5"])
async def test_direct_real_broker_is_rejected_before_gateway_creation(broker: str) -> None:
    settings.broker = broker
    with patch("main.get_gateway") as get_gateway:
        with pytest.raises(ConfigurationError, match="simulation only"):
            await main.run()
    get_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_simulation_uses_durable_executor_with_explicit_authorization() -> None:
    gateway = _gateway()
    store = MagicMock()
    store.list_unresolved.return_value = ()
    store.get.return_value = None
    executor = MagicMock()
    executor.submit = AsyncMock(return_value=SimpleNamespace(
        state="accepted", decision=SimpleNamespace(allowed=True, code=ExecutionDecisionCode.ALLOWED)
    ))
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
    assert context.emergency_stop is False
    gateway.submit_order.assert_not_awaited()
    risk = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read_risk()
    assert risk is not None
    assert risk.evaluation_state is RiskEvaluationState.AUTHORIZED
    assert risk.account_id == "SIMULATED"
    assert risk.authorized_risk_amount == 2.0
    assert risk.execution_quantity_available is True
    assert risk.execution_quantity_value == 1.0
    assert risk.execution_quantity_unit == "SIMULATION_UNITS"


@pytest.mark.asyncio
async def test_durable_blocked_risk_publishes_fresh_no_quantity_observation() -> None:
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patch(
        "main.approve_trade",
        return_value={
            "approved": False,
            "reason": "Confidence too low",
            "risk_percent": 0.0,
            "authorized_risk_amount": 0.0,
        },
    ), patches[6]:
        await main.run()
    risk = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read_risk()
    assert risk is not None
    assert risk.evaluation_state is RiskEvaluationState.BLOCKED
    assert risk.account_id == "SIMULATED"
    assert risk.execution_quantity_available is False
    assert risk.execution_quantity_value is None
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_new_cycle_invalidates_previous_authorized_risk_observation() -> None:
    first_gateway = _gateway()
    first_patches = _pipeline_patches(first_gateway)
    with (
        first_patches[0], first_patches[1], first_patches[2], first_patches[3],
        first_patches[4], first_patches[5], first_patches[6]
    ):
        await main.run()
    store = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    )
    assert store.read_risk().execution_quantity_available is True

    failed_gateway = _gateway()
    failed_gateway.get_candles.return_value = []
    with patch("main.get_gateway", return_value=failed_gateway):
        with pytest.raises(Exception, match="Market data unavailable"):
            await main.run()

    risk = store.read_risk()
    assert risk is not None
    assert risk.evaluation_state is RiskEvaluationState.NOT_EVALUATED
    assert risk.execution_quantity_available is False
    assert risk.execution_quantity_value is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stop_state",
    [EmergencyStopState.ACTIVE, EmergencyStopState.UNKNOWN],
)
async def test_non_clear_emergency_stop_blocks_durable_simulation_submission(
    stop_state: EmergencyStopState,
) -> None:
    settings.emergency_stop = stop_state
    gateway = _gateway()
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    gateway.submit_order.assert_not_awaited()
    snapshot = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert snapshot is not None
    assert snapshot.execution_authorization is ExecutionAuthorization.BLOCKED
    assert snapshot.reason_codes == (
        "EMERGENCY_STOP" if stop_state is EmergencyStopState.ACTIVE else "SAFETY_CONTEXT_INVALID",
    )


@pytest.mark.asyncio
async def test_pre_submit_safety_publication_failure_prevents_submission() -> None:
    gateway = _gateway()
    safety_store = MagicMock()
    safety_store.publish.side_effect = [None, OSError("safety publication failed")]
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteExecutionSafetyStore", return_value=safety_store
    ):
        with pytest.raises(OSError, match="safety publication failed"):
            await main.run()
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminal_safety_publication_failure_leaves_submission_in_progress() -> None:
    gateway = _gateway()
    real_store = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=True
    )
    safety_store = MagicMock()
    publication_count = 0

    def publish(snapshot) -> None:
        nonlocal publication_count
        publication_count += 1
        if publication_count == 3:
            raise OSError("terminal safety publication failed")
        real_store.publish(snapshot)

    safety_store.publish.side_effect = publish
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteExecutionSafetyStore", return_value=safety_store
    ):
        with pytest.raises(OSError, match="terminal safety publication failed"):
            await main.run()

    gateway.submit_order.assert_awaited_once()
    snapshot = real_store.read()
    assert snapshot is not None
    assert snapshot.execution_authorization is ExecutionAuthorization.NOT_EVALUATED
    assert snapshot.reason_codes == ("SUBMISSION_IN_PROGRESS",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    [
        TradeHistorySnapshot(completeness=TradeHistoryCompleteness.TRUNCATED),
        TradeHistorySnapshot(completeness=TradeHistoryCompleteness.UNKNOWN),
        TradeHistorySnapshot(completeness=TradeHistoryCompleteness.COMPLETE),
    ],
    ids=["truncated", "unknown", "complete-without-coverage"],
)
async def test_unproven_daily_history_blocks_durable_submission(
    snapshot: TradeHistorySnapshot,
) -> None:
    gateway = _gateway()
    gateway.get_trade_history_snapshot.return_value = snapshot
    gateway.get_trade_history_snapshot.side_effect = None
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
    gateway.submit_order.assert_not_awaited()
    safety = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert safety is not None
    assert safety.execution_authorization is ExecutionAuthorization.BLOCKED
    assert safety.reason_codes == ("DAILY_STATE_NOT_AUTHORITATIVE",)


@pytest.mark.asyncio
async def test_unavailable_daily_history_fails_closed_before_submission() -> None:
    gateway = _gateway()
    gateway.get_trade_history_snapshot.side_effect = RuntimeError("history unavailable")
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with pytest.raises(RuntimeError, match="history unavailable"):
            await main.run()
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("broker", ["deriv", "mt5"])
async def test_unauthorized_durable_execution_fails_before_gateway_creation(
    broker: str,
) -> None:
    settings.broker = broker
    with patch("main.get_gateway") as get_gateway:
        with pytest.raises(Exception, match="simulation only"):
            await main.run()
    get_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_store_initialization_failure_prevents_broker_submission() -> None:
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
        symbol=" xauusd ", side="buy", quantity=ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS), entry=101.0, stop_loss=99.0,
        take_profit=105.0, signal_time=pd.Timestamp("2026-08-29T12:00:00Z"),
    )
    first = build_execution_idempotency_key(**values)
    assert first == build_execution_idempotency_key(**values)
    assert first != build_execution_idempotency_key(**{**values, "quantity": ExecutionQuantity(value=2.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS)})
    assert first != build_execution_idempotency_key(**{**values, "quantity": ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.DERIV_STAKE)})


@pytest.mark.asyncio
async def test_complete_durable_path_preserves_key_and_blocks_duplicate() -> None:
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
async def test_allowed_policy_is_published_before_durable_submission() -> None:
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
    safety = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert safety is not None
    assert safety.execution_authorization is ExecutionAuthorization.AUTHORIZED
    assert safety.reason_codes == ("ORDER_ACCEPTED",)
    gateway.submit_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_held_execution_reservation_is_published_as_blocked() -> None:
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    assert store.acquire_reservation(
        "SIMULATED", "other-process", 120, "other-key"
    ) is ReservationState.ACQUIRED
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    gateway.submit_order.assert_not_awaited()
    safety = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert safety is not None
    assert safety.execution_authorization is ExecutionAuthorization.BLOCKED
    assert safety.reason_codes == ("EXECUTION_RESERVATION_HELD",)


@pytest.mark.asyncio
async def test_reconciliation_exit_before_pre_submit_remains_not_evaluated() -> None:
    gateway = _gateway()
    store = MagicMock()
    store.list_unresolved.return_value = ()
    store.get.return_value = None
    decision = ExecutionDecision(True, ExecutionDecisionCode.ALLOWED, "Execution authorized")
    executor = MagicMock()
    executor.submit = AsyncMock(return_value=ExecutionResult(
        ReconciliationState.ALREADY_EXECUTED,
        decision,
        order_id="SIM-prior",
        reason="Intent was already accepted",
    ))
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ), patch("main.AsyncTradeExecutor", return_value=executor):
        await main.run()

    snapshot = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert snapshot is not None
    assert snapshot.execution_authorization is ExecutionAuthorization.NOT_EVALUATED
    assert snapshot.reason_codes == ("NOT_EVALUATED",)


@pytest.mark.asyncio
async def test_durable_claim_failure_after_pre_submit_publishes_unknown() -> None:
    gateway = _gateway()
    store = MagicMock()
    store.recovery_mode = False
    store.list_unresolved.return_value = ()
    store.get.return_value = None
    store.acquire_reservation.return_value = ReservationState.ACQUIRED
    store.release_reservation.return_value = True
    store.try_claim_under_reservation.side_effect = OSError("claim unavailable")
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ):
        await main.run()

    gateway.submit_order.assert_not_awaited()
    snapshot = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert snapshot is not None
    assert snapshot.execution_authorization is ExecutionAuthorization.UNKNOWN
    assert snapshot.reason_codes == ("SUBMISSION_OUTCOME_UNKNOWN",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("broker_result", "expected_authorization", "expected_reason"),
    [
        (
            OrderResult(
                order_id="", status=OrderStatus.REJECTED, symbol="XAUUSD",
                side=OrderSide.BUY, volume=1.0,
            ),
            ExecutionAuthorization.BLOCKED,
            "BROKER_REJECTED",
        ),
        (object(), ExecutionAuthorization.UNKNOWN, "SUBMISSION_OUTCOME_UNKNOWN"),
    ],
    ids=["broker-rejection", "malformed-result"],
)
async def test_terminal_broker_results_publish_fail_closed_state(
    broker_result, expected_authorization, expected_reason
) -> None:
    gateway = _gateway()
    gateway.submit_order.return_value = broker_result
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    snapshot = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert snapshot is not None
    assert snapshot.execution_authorization is expected_authorization
    assert snapshot.reason_codes == (expected_reason,)


@pytest.mark.asyncio
async def test_durable_terminal_persistence_failure_publishes_unknown() -> None:
    gateway = _gateway()
    store = MagicMock()
    store.recovery_mode = False
    store.list_unresolved.return_value = ()
    store.get.return_value = None
    store.acquire_reservation.return_value = ReservationState.ACQUIRED
    store.release_reservation.return_value = True
    store.try_claim_under_reservation.return_value = ClaimState.CLAIMED
    store.transition.return_value = False
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ):
        await main.run()

    gateway.submit_order.assert_awaited_once()
    snapshot = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert snapshot is not None
    assert snapshot.execution_authorization is ExecutionAuthorization.UNKNOWN
    assert snapshot.reason_codes == ("SUBMISSION_OUTCOME_UNKNOWN",)


@pytest.mark.asyncio
async def test_unknown_submission_is_persisted_and_not_blindly_retried() -> None:
    gateway = _gateway()
    gateway.submit_order.side_effect = TimeoutError("outcome unknown")
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
        safety = SQLiteExecutionSafetyStore(
            settings.execution_safety_store_path, initialize=False
        ).read()
        assert safety is not None
        assert safety.execution_authorization is ExecutionAuthorization.UNKNOWN
        assert safety.reason_codes == ("SUBMISSION_OUTCOME_UNKNOWN",)
        with pytest.raises(ExecutionError, match="unresolved persisted intents"):
            await main.run()

    gateway.submit_order.assert_awaited_once()
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    with store._connect() as connection:
        key = connection.execute("SELECT idempotency_key FROM intent_records").fetchone()[0]
    assert store.get(key).status is IntentRecordStatus.UNKNOWN
    safety = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert safety is not None
    assert safety.execution_authorization is ExecutionAuthorization.BLOCKED
    assert safety.reason_codes == ("UNRESOLVED_DURABLE_INTENT",)


@pytest.mark.asyncio
async def test_broker_open_same_symbol_position_blocks_durable_submission() -> None:
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
async def test_unresolved_record_blocks_startup_without_reconciliation(
    prior_status: IntentRecordStatus,
) -> None:
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
        with pytest.raises(ExecutionError, match="unresolved persisted intents"):
            await main.run()

    gateway.submit_order.assert_not_awaited()
    gateway.__aenter__.assert_awaited_once()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is prior_status
    assert recovered.order_id == "SIM-prior"
    safety = SQLiteExecutionSafetyStore(
        settings.execution_safety_store_path, initialize=False
    ).read()
    assert safety is not None
    assert safety.execution_authorization is ExecutionAuthorization.BLOCKED
    assert safety.unresolved_intent_count == 1
    assert safety.reason_codes == ("UNRESOLVED_DURABLE_INTENT",)


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_status", [IntentRecordStatus.UNKNOWN, IntentRecordStatus.PENDING])
async def test_unresolved_record_without_evidence_remains_unchanged(
    prior_status: IntentRecordStatus,
) -> None:
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
        with pytest.raises(ExecutionError, match="unresolved persisted intents"):
            await main.run()

    gateway.submit_order.assert_not_awaited()
    gateway.__aenter__.assert_awaited_once()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is prior_status


@pytest.mark.asyncio
async def test_recovery_store_read_failure_fails_closed() -> None:
    gateway = _gateway()
    store = MagicMock()
    store.list_unresolved.return_value = ()
    store.get.side_effect = OSError("read failed")
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ):
        with pytest.raises(OSError, match="read failed"):
            await main.run()
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_unresolved_record_blocks_before_reconciliation_gateway_calls() -> None:
    _persist_record(IntentRecordStatus.UNKNOWN)
    gateway = _gateway()
    gateway.get_positions.side_effect = [[], RuntimeError("reconciliation unavailable")]
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with pytest.raises(ExecutionError, match="unresolved persisted intents"):
            await main.run()

    gateway.submit_order.assert_not_awaited()
    gateway.get_positions.assert_not_awaited()
    recovered = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert recovered is not None
    assert recovered.status is IntentRecordStatus.UNKNOWN


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [IntentRecordStatus.ACCEPTED, IntentRecordStatus.REJECTED])
async def test_unrelated_terminal_records_do_not_block_new_durable_intent(
    status: IntentRecordStatus,
) -> None:
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    assert store.try_claim(IntentRecord("terminal-old", status)) is ClaimState.CLAIMED
    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
    gateway.submit_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_multiple_unresolved_records_block_new_intent_in_enumeration_order() -> None:
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    records = (
        IntentRecord("pending-first", IntentRecordStatus.PENDING),
        IntentRecord("accepted-middle", IntentRecordStatus.ACCEPTED),
        IntentRecord("unknown-last", IntentRecordStatus.UNKNOWN),
    )
    for record in records:
        assert store.try_claim(record) is ClaimState.CLAIMED
    assert store.list_unresolved() == (records[0], records[2])

    gateway = _gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with pytest.raises(ExecutionError, match="unresolved persisted intents"):
            await main.run()
    gateway.submit_order.assert_not_awaited()
    gateway.__aenter__.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_continues_after_all_unresolved_intents_are_proven_accepted() -> None:
    store = SQLiteIntentRecordStore(settings.intent_store_path)
    record = IntentRecord(
        idempotency_key=_expected_key(),
        status=IntentRecordStatus.UNKNOWN,
        order_id="SIM-prior",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        quantity=ExecutionQuantity(
            value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS
        ),
        entry=101.0,
        stop_loss=99.0,
        take_profit=105.0,
        authorized_risk_amount=2.0,
        expected_loss_at_stop=2.0,
        broker="simulation",
        account_id="SIMULATED",
    )
    assert store.try_claim(record) is ClaimState.CLAIMED
    gateway = _gateway()
    gateway.get_positions.return_value = [
        Position(
            position_id="SIM-prior",
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=1.0,
            open_price=101.0,
        )
    ]
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()

    assert store.get(_expected_key()).status is IntentRecordStatus.ACCEPTED
    gateway.get_candles.assert_awaited_once()
    gateway.submit_order.assert_not_awaited()
