"""Offline regression coverage for durable account execution reservations."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from broker.types import OrderRequest, OrderResult, OrderSide, OrderStatus, Position
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.models import (
    ClaimState,
    IntentRecord,
    IntentRecordStatus,
    ReservationState,
)
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionDecisionCode, ExecutionIntent


def _intent(key: str, symbol: str = "EURUSD") -> ExecutionIntent:
    return ExecutionIntent(symbol, OrderSide.BUY, 1.0, 100.0, 99.0, 101.0, key, True)


def _context() -> ExecutionContext:
    return ExecutionContext(
        emergency_stop=False,
        daily_loss_percent=0.0,
        max_daily_loss_percent=3.0,
        daily_trade_count=0,
        max_daily_trades=5,
        open_positions=(),
        max_open_positions=1,
        used_idempotency_keys=frozenset(),
        execution_enabled=True,
        dry_run=False,
        broker="simulation",
        environment="development",
        account_id="account-1",
        approved_brokers=frozenset({"simulation"}),
        approved_environments=frozenset({"development"}),
        approved_accounts=frozenset({"account-1"}),
        approved_symbols=frozenset({"EURUSD", "GBPUSD"}),
        daily_state_authoritative=True,
    )


class CoordinatedGateway:
    def __init__(self) -> None:
        self.positions: list[Position] = []
        self.entered_submission = asyncio.Event()
        self.allow_submission = asyncio.Event()
        self.orders: list[OrderRequest] = []

    async def get_positions(self) -> list[Position]:
        return list(self.positions)

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        self.orders.append(order)
        self.entered_submission.set()
        await self.allow_submission.wait()
        order_id = f"SIM-{len(self.orders)}"
        self.positions.append(
            Position(
                position_id=order_id,
                symbol=order.symbol,
                side=order.side,
                volume=order.volume,
                open_price=100.0,
            )
        )
        return OrderResult(
            order_id=order_id,
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=order.volume,
        )


def test_competing_process_safe_acquisition_has_one_owner(tmp_path) -> None:
    path = tmp_path / "intents.sqlite3"
    first = SQLiteIntentRecordStore(path)
    second = SQLiteIntentRecordStore(path)

    def acquire(values: tuple[SQLiteIntentRecordStore, str, str]) -> ReservationState:
        store, owner, key = values
        return store.acquire_reservation("account-1", owner, 120, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(acquire, ((first, "owner-1", "key-1"), (second, "owner-2", "key-2")))
        )

    assert sorted(result.value for result in results) == ["ACQUIRED", "HELD"]


def test_valid_lease_cannot_be_stolen_and_release_is_owner_checked(tmp_path) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.acquire_reservation("account-1", "owner-1", 120, "key-1") is ReservationState.ACQUIRED
    assert store.acquire_reservation("account-1", "owner-2", 120, "key-2") is ReservationState.HELD
    assert store.release_reservation("account-1", "owner-2") is False
    assert store.acquire_reservation("account-1", "owner-2", 120, "key-2") is ReservationState.HELD
    assert store.release_reservation("account-1", "owner-1") is True


def test_expired_crash_style_lease_is_reclaimed_without_unresolved_intent(tmp_path) -> None:
    now = [datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)]
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3", clock=lambda: now[0])
    assert store.acquire_reservation("account-1", "dead-owner", 10, "key-1") is ReservationState.ACQUIRED
    now[0] += timedelta(seconds=11)
    assert store.acquire_reservation("account-1", "new-owner", 10, "key-2") is ReservationState.ACQUIRED


def test_expired_lease_does_not_bypass_other_unresolved_intent(tmp_path) -> None:
    now = [datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)]
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3", clock=lambda: now[0])
    assert store.acquire_reservation("account-1", "dead-owner", 10, "key-1") is ReservationState.ACQUIRED
    assert store.try_claim_under_reservation(
        IntentRecord("key-1", IntentRecordStatus.PENDING), "account-1", "dead-owner"
    ) is ClaimState.CLAIMED
    now[0] += timedelta(seconds=11)
    assert store.acquire_reservation(
        "account-1", "new-owner", 10, "different-key"
    ) is ReservationState.UNRESOLVED_INTENT


def test_expired_owner_cannot_claim_an_intent(tmp_path) -> None:
    now = [datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)]
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3", clock=lambda: now[0])
    assert store.acquire_reservation("account-1", "owner-1", 10, "key-1") is ReservationState.ACQUIRED
    now[0] += timedelta(seconds=11)
    assert store.try_claim_under_reservation(
        IntentRecord("key-1", IntentRecordStatus.PENDING), "account-1", "owner-1"
    ) is ClaimState.CONFLICT
    assert store.get("key-1") is None


@pytest.mark.parametrize("column,value", [("owner_id", ""), ("expires_at", "not-a-time")])
def test_malformed_lease_fails_closed(tmp_path, column: str, value: str) -> None:
    store = SQLiteIntentRecordStore(tmp_path / "intents.sqlite3")
    assert store.acquire_reservation("account-1", "owner-1", 120, "key-1") is ReservationState.ACQUIRED
    with store._connect() as connection:
        connection.execute(
            f"UPDATE execution_reservations SET {column} = ? WHERE scope = ?",
            (value, "account-1"),
        )
    with pytest.raises(ValueError, match="Malformed execution reservation"):
        store.acquire_reservation("account-1", "owner-2", 120, "key-2")


@pytest.mark.asyncio
async def test_reservation_database_failure_is_fail_closed() -> None:
    class UnavailableStore:
        recovery_mode = False

        def acquire_reservation(self, *args) -> ReservationState:
            raise sqlite3.OperationalError("database is locked")

    gateway = CoordinatedGateway()
    result = await AsyncTradeExecutor(gateway, UnavailableStore()).submit(  # type: ignore[arg-type]
        _intent("key-1"), _context()
    )
    assert result.state is ReconciliationState.UNKNOWN
    assert result.decision.code is ExecutionDecisionCode.EXECUTION_RESERVATION_UNAVAILABLE
    assert gateway.orders == []


@pytest.mark.asyncio
async def test_different_keys_and_symbols_cannot_overlap_submission(tmp_path) -> None:
    path = tmp_path / "intents.sqlite3"
    gateway = CoordinatedGateway()
    first = asyncio.create_task(
        AsyncTradeExecutor(gateway, SQLiteIntentRecordStore(path)).submit(
            _intent("key-1", "EURUSD"), _context()
        )
    )
    await gateway.entered_submission.wait()
    second = await AsyncTradeExecutor(gateway, SQLiteIntentRecordStore(path)).submit(
        _intent("key-2", "GBPUSD"), _context()
    )
    gateway.allow_submission.set()
    first_result = await first

    assert first_result.state is ReconciliationState.ALREADY_EXECUTED
    assert second.decision.code is ExecutionDecisionCode.EXECUTION_RESERVATION_HELD
    assert len(gateway.orders) == 1


@pytest.mark.asyncio
async def test_next_execution_refreshes_positions_after_prior_completion(tmp_path) -> None:
    path = tmp_path / "intents.sqlite3"
    gateway = CoordinatedGateway()
    gateway.allow_submission.set()
    first = await AsyncTradeExecutor(gateway, SQLiteIntentRecordStore(path)).submit(
        _intent("key-1", "EURUSD"), _context()
    )
    second = await AsyncTradeExecutor(gateway, SQLiteIntentRecordStore(path)).submit(
        _intent("key-2", "GBPUSD"), _context()
    )

    assert first.state is ReconciliationState.ALREADY_EXECUTED
    assert second.decision.code is ExecutionDecisionCode.MAX_OPEN_POSITIONS
    assert len(gateway.orders) == 1


@pytest.mark.asyncio
async def test_context_provider_runs_after_reservation_and_before_policy(tmp_path) -> None:
    events: list[str] = []

    class TrackingStore(SQLiteIntentRecordStore):
        def acquire_reservation(self, *args, **kwargs) -> ReservationState:
            events.append("reservation")
            return super().acquire_reservation(*args, **kwargs)

    async def refresh() -> ExecutionContext:
        events.append("context")
        return replace(_context(), daily_trade_count=5)

    gateway = CoordinatedGateway()
    result = await AsyncTradeExecutor(
        gateway, TrackingStore(tmp_path / "intents.sqlite3")
    ).submit(_intent("key-1"), _context(), context_provider=refresh)

    assert events == ["reservation", "context"]
    assert result.decision.code is ExecutionDecisionCode.DAILY_TRADE_LIMIT
    assert gateway.orders == []


@pytest.mark.asyncio
async def test_terminal_safety_callback_runs_before_reservation_release(tmp_path) -> None:
    events: list[str] = []

    class TrackingStore(SQLiteIntentRecordStore):
        def release_reservation(self, scope: str, owner_id: str) -> bool:
            events.append("release")
            return super().release_reservation(scope, owner_id)

    gateway = CoordinatedGateway()
    gateway.allow_submission.set()
    result = await AsyncTradeExecutor(
        gateway, TrackingStore(tmp_path / "intents.sqlite3")
    ).submit(
        _intent("key-1"),
        _context(),
        after_submit=lambda _result: events.append("terminal-safety"),
    )

    assert result.state is ReconciliationState.ALREADY_EXECUTED
    assert events == ["terminal-safety", "release"]
