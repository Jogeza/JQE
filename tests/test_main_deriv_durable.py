"""Offline Phase 6C integration tests for durable Deriv DEMO execution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import main
from broker.types import (
    AccountInfo,
    OrderResult,
    OrderSide,
    OrderStatus,
    TradeHistorySnapshot,
)
from config import settings
from core.exceptions import ExecutionError
from execution.models import ClaimState, IntentRecord, IntentRecordStatus
from execution.persistence import SQLiteIntentRecordStore
from tests.test_main_durable_executor import _expected_key, _gateway, _pipeline_patches


@pytest.fixture(autouse=True)
def _deriv_demo_settings(tmp_path):
    original = {
        "broker": settings.broker,
        "use_durable_executor": settings.use_durable_executor,
        "intent_store_path": settings.intent_store_path,
        "deriv_expected_environment": settings.deriv_expected_environment,
        "deriv_options_account_id": settings.deriv_options_account_id,
        "deriv_demo_execution_enabled": settings.deriv_demo_execution_enabled,
        "deriv_approved_symbols": settings.deriv_approved_symbols,
        "default_symbol": settings.default_symbol,
        "environment": settings.environment,
    }
    settings.broker = "deriv"
    settings.use_durable_executor = True
    settings.intent_store_path = tmp_path / "deriv-intents.sqlite3"
    settings.deriv_expected_environment = "demo"
    settings.deriv_options_account_id = "CR-DEMO"
    settings.deriv_demo_execution_enabled = True
    settings.deriv_approved_symbols = frozenset({"XAUUSD"})
    settings.default_symbol = "XAUUSD"
    settings.environment = "development"
    with patch(
        "broker.deriv_gateway.websockets.connect",
        side_effect=AssertionError("external Deriv WebSocket access is forbidden"),
    ) as websocket_connect, patch(
        "broker.deriv_auth.urlopen",
        side_effect=AssertionError("external Deriv HTTP access is forbidden"),
    ) as urlopen:
        yield websocket_connect, urlopen
    for name, value in original.items():
        setattr(settings, name, value)


def _deriv_gateway(*, account_id: str = "CR-DEMO") -> MagicMock:
    gateway = _gateway()
    gateway.get_trade_history_snapshot.side_effect = None
    gateway.get_trade_history_snapshot.return_value = TradeHistorySnapshot()
    gateway.get_account_info.return_value = AccountInfo(
        account_id=account_id, balance=10_000.0, currency="USD"
    )
    gateway.submit_order.return_value = OrderResult(
        order_id="contract-1",
        transaction_id="txn-1",
        status=OrderStatus.FILLED,
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=1.0,
    )
    return gateway


def _persist(
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
        assert store.transition(
            IntentRecord(key, status, order_id, transaction_id)
        ) is True


@pytest.mark.asyncio
async def test_durable_deriv_demo_is_authorized_with_explicit_context() -> None:
    gateway = _deriv_gateway()
    store = MagicMock()
    store.list_unresolved.return_value = ()
    store.get.return_value = None
    executor = MagicMock()
    executor.submit = AsyncMock(return_value=SimpleNamespace(state="accepted"))
    patches = _pipeline_patches(gateway)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ), patch("main.AsyncTradeExecutor", return_value=executor):
        await main.run()

    intent, context = executor.submit.await_args.args
    assert context.execution_enabled is True
    assert context.dry_run is False
    assert context.broker == "deriv"
    assert context.environment == "development"
    assert context.account_id == "CR-DEMO"
    assert context.approved_brokers == frozenset({"deriv"})
    assert context.approved_environments == frozenset({"development"})
    assert context.approved_accounts == frozenset({"CR-DEMO"})
    assert context.approved_symbols == frozenset({"XAUUSD"})
    assert context.daily_state_authoritative is False
    assert intent.idempotency_key == store.get.call_args.args[0]
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value,message",
    [
        ("deriv_expected_environment", "real", "explicit demo environment"),
        ("deriv_expected_environment", None, "explicit demo environment"),
        ("environment", "production", "development environment"),
        ("environment", "staging", "development environment"),
        ("deriv_demo_execution_enabled", False, "not enabled"),
        ("deriv_options_account_id", None, "approved account"),
        ("deriv_approved_symbols", frozenset({"R_100"}), "approved symbol"),
    ],
)
async def test_invalid_deriv_deployment_is_blocked_before_gateway_construction(
    field: str, value: object, message: str
) -> None:
    setattr(settings, field, value)
    with patch("main.get_gateway") as get_gateway:
        with pytest.raises(Exception, match=message):
            await main.run()
    get_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_durable_mt5_remains_blocked_before_gateway_construction() -> None:
    settings.broker = "mt5"
    with patch("main.get_gateway") as get_gateway:
        with pytest.raises(Exception, match="simulation and Deriv DEMO only"):
            await main.run()
    get_gateway.assert_not_called()


@pytest.mark.asyncio
async def test_deriv_demo_wrong_observed_account_fails_policy_closed() -> None:
    gateway = _deriv_gateway(account_id="CR-WRONG")
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
    gateway.submit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_deriv_demo_daily_state_is_not_authoritative_without_coverage() -> None:
    gateway = _deriv_gateway()
    store = MagicMock()
    store.list_unresolved.return_value = ()
    store.get.return_value = None
    executor = MagicMock()
    executor.submit = AsyncMock(return_value=SimpleNamespace(state="denied"))
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patch(
        "main.SQLiteIntentRecordStore", return_value=store
    ), patch("main.AsyncTradeExecutor", return_value=executor), patch(
        "main.get_reconciled_daily_state", return_value=(1.25, 2, 3.0, 5)
    ):
        await main.run()
    _, context = executor.submit.await_args.args
    assert context.daily_loss_percent == 1.25
    assert context.daily_trade_count == 2
    assert context.max_daily_loss_percent == 3.0
    assert context.max_daily_trades == 5
    assert context.daily_state_authoritative is False


@pytest.mark.asyncio
async def test_deriv_demo_new_intent_fails_closed_without_complete_daily_history() -> None:
    gateway = _deriv_gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
        await main.run()

    gateway.submit_order.assert_not_awaited()
    assert SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [IntentRecordStatus.ACCEPTED, IntentRecordStatus.REJECTED])
async def test_deriv_demo_terminal_restart_does_not_submit(
    status: IntentRecordStatus,
) -> None:
    _persist(status, order_id="contract-1" if status is IntentRecordStatus.ACCEPTED else None)
    gateway = _deriv_gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        await main.run()
    gateway.submit_order.assert_not_awaited()
    assert SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key()).status is status


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN])
async def test_deriv_demo_unresolved_record_blocks_before_broker_evidence(
    status: IntentRecordStatus,
) -> None:
    _persist(status, order_id="contract-1", transaction_id="txn-1")
    gateway = _deriv_gateway()
    patches = _pipeline_patches(gateway)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with pytest.raises(ExecutionError, match="unresolved persisted intents"):
            await main.run()
    gateway.get_positions.assert_not_awaited()
    gateway.submit_order.assert_not_awaited()
    record = SQLiteIntentRecordStore(settings.intent_store_path).get(_expected_key())
    assert record.status is status


def test_phase6c_network_boundary_was_never_called(_deriv_demo_settings) -> None:
    websocket_connect, urlopen = _deriv_demo_settings
    websocket_connect.assert_not_called()
    urlopen.assert_not_called()
