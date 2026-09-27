"""Unit and integration tests for Continuous Terminal Reconciliation (Phase 5).

Validates:
1. TerminalReconciliationAuditor reports clean state when broker and internal match.
2. Auditor detects untracked broker positions (external manual trades).
3. Auditor detects magic number divergence as external manual trade.
4. Auditor detects volume discrepancies (e.g. partial external close).
5. Auditor detects symbol and side mismatches.
6. Auditor detects phantom internal positions (ledger claims open, broker empty).
7. Auditor handles broker gateway errors fail-closed.
8. ContinuousTerminalReconciliationService trips EmergencyStop circuit breaker,
   disables execution, updates SQLite safety store, and invokes callbacks.
9. ContinuousTerminalReconciliationService background run_loop executes cleanly
   and terminates when circuit breaker trips.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from broker.types import OrderSide, Position
from config.settings import Settings, EmergencyStopState
from execution.continuous_reconciliation import (
    AuditReconciliationReport,
    ContinuousTerminalReconciliationService,
    ReconciliationDiscrepancyType,
    TerminalReconciliationAuditor,
    TrackedTradeState,
)
from execution.persistence import PositionLedgerEntry
from execution.safety import (
    EmergencyStopState,
    ExecutionAuthorization,
    SQLiteExecutionSafetyStore,
    utc_now,
)
from intelligence.trade_plan import TradePlan


def _pos(
    pid: str = "1001",
    symbol: str = "VOL_10",
    side: OrderSide = OrderSide.BUY,
    volume: float = 0.1,
    magic: int | None = 12345,
) -> Position:
    return Position(
        position_id=pid,
        symbol=symbol,
        side=side,
        volume=volume,
        open_price=100.0,
        magic=magic,
    )


class MockGateway:
    def __init__(self, positions: list[Position] | None = None) -> None:
        self._positions = list(positions) if positions is not None else []

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    def set_positions(self, positions: list[Position]) -> None:
        self._positions = list(positions)


class FailingGateway:
    async def get_positions(self) -> list[Position]:
        raise ConnectionResetError("MT5 IPC pipe disconnected")


class MockLedger:
    def __init__(self, entries: list[PositionLedgerEntry] | None = None) -> None:
        self._entries = list(entries) if entries is not None else []

    def open_entries(self, *, broker: str) -> tuple[PositionLedgerEntry, ...]:
        return tuple(self._entries)


# ---------------------------------------------------------------------------
# 1. Auditor - Clean states
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auditor_empty_is_clean() -> None:
    gateway = MockGateway([])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    report = await auditor.audit()
    assert report.is_clean is True
    assert report.broker_positions_count == 0
    assert report.tracked_positions_count == 0
    assert len(report.discrepancies) == 0
    assert report.action_taken == "CLEAN"


@pytest.mark.asyncio
async def test_auditor_matching_tracked_is_clean() -> None:
    p = _pos("1001", "VOL_10", OrderSide.BUY, 0.1)
    gateway = MockGateway([p])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    tracked = [
        TrackedTradeState(
            symbol="VOL_10",
            side=OrderSide.BUY,
            volume=0.1,
            position_id="1001",
        )
    ]
    report = await auditor.audit(explicit_tracked=tracked)
    assert report.is_clean is True
    assert report.broker_positions_count == 1
    assert report.tracked_positions_count == 1
    assert len(report.discrepancies) == 0


@pytest.mark.asyncio
async def test_auditor_matching_trade_plan_is_clean() -> None:
    p = _pos("1001", "VOL_10", OrderSide.BUY, 0.1)
    gateway = MockGateway([p])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    plan = TradePlan(symbol="VOL_10", signal="BUY", confidence=85)
    report = await auditor.audit(active_plans=[plan])
    assert report.is_clean is True
    assert report.broker_positions_count == 1


# ---------------------------------------------------------------------------
# 2. Auditor - Discrepancy detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auditor_detects_untracked_broker_position() -> None:
    p = _pos("9999", "FX_VOL_50", OrderSide.SELL, 0.5)
    gateway = MockGateway([p])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    report = await auditor.audit(explicit_tracked=[])
    assert report.is_clean is False
    assert len(report.discrepancies) == 1
    d = report.discrepancies[0]
    assert d.discrepancy_type is ReconciliationDiscrepancyType.UNTRACKED_BROKER_POSITION
    assert d.position_id == "9999"
    assert d.symbol == "FX_VOL_50"


@pytest.mark.asyncio
async def test_auditor_detects_magic_number_external_manual_trade() -> None:
    # Position with different magic number when expected_magic_number is enforced
    p = _pos("5001", "VOL_20", OrderSide.BUY, 0.05, magic=99999)
    gateway = MockGateway([p])
    auditor = TerminalReconciliationAuditor(
        gateway, broker="weltrade", expected_magic_number=12345
    )
    report = await auditor.audit()
    assert report.is_clean is False
    assert any(
        d.discrepancy_type is ReconciliationDiscrepancyType.EXTERNAL_MANUAL_TRADE
        for d in report.discrepancies
    )


@pytest.mark.asyncio
async def test_auditor_detects_volume_mismatch() -> None:
    p = _pos("1001", "VOL_10", OrderSide.BUY, volume=0.05)  # half closed on broker
    gateway = MockGateway([p])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    tracked = [
        TrackedTradeState(
            symbol="VOL_10",
            side=OrderSide.BUY,
            volume=0.10,  # internal expects 0.10
            position_id="1001",
        )
    ]
    report = await auditor.audit(explicit_tracked=tracked)
    assert report.is_clean is False
    d = report.discrepancies[0]
    assert d.discrepancy_type is ReconciliationDiscrepancyType.VOLUME_MISMATCH
    assert d.broker_volume == 0.05
    assert d.internal_volume == 0.10


@pytest.mark.asyncio
async def test_auditor_detects_side_mismatch() -> None:
    p = _pos("1001", "VOL_10", side=OrderSide.SELL)
    gateway = MockGateway([p])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    tracked = [
        TrackedTradeState(
            symbol="VOL_10",
            side=OrderSide.BUY,
            position_id="1001",
        )
    ]
    report = await auditor.audit(explicit_tracked=tracked)
    assert report.is_clean is False
    assert report.discrepancies[0].discrepancy_type is ReconciliationDiscrepancyType.SIDE_MISMATCH


@pytest.mark.asyncio
async def test_auditor_detects_phantom_internal_position() -> None:
    # Broker has NO positions, but internal ledger claims position 1001 is open
    gateway = MockGateway([])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    tracked = [
        TrackedTradeState(
            symbol="VOL_10",
            side=OrderSide.BUY,
            volume=0.1,
            position_id="1001",
        )
    ]
    report = await auditor.audit(explicit_tracked=tracked)
    assert report.is_clean is False
    d = report.discrepancies[0]
    assert d.discrepancy_type is ReconciliationDiscrepancyType.PHANTOM_INTERNAL_POSITION
    assert d.position_id == "1001"


@pytest.mark.asyncio
async def test_auditor_handles_broker_error_fail_closed() -> None:
    gateway = FailingGateway()
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    report = await auditor.audit()
    assert report.is_clean is False
    assert report.action_taken == "AUDIT_FAILED"
    assert report.discrepancies[0].discrepancy_type is ReconciliationDiscrepancyType.BROKER_UNAVAILABLE


# ---------------------------------------------------------------------------
# 3. Continuous Service & Circuit Breaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_reconcile_and_protect_clean_does_not_trip(tmp_path) -> None:
    gateway = MockGateway([])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    store = SQLiteExecutionSafetyStore(tmp_path / "safety.sqlite3", initialize=True)
    settings = Settings(_env_file=None, emergency_stop=EmergencyStopState.CLEAR)

    service = ContinuousTerminalReconciliationService(
        auditor, safety_store=store, settings=settings
    )
    report = await service.reconcile_and_protect()
    assert report.is_clean is True
    assert report.emergency_stop_tripped is False
    assert service.is_emergency_stop_latched is False
    assert settings.emergency_stop is EmergencyStopState.CLEAR


@pytest.mark.asyncio
async def test_service_trips_emergency_stop_on_discrepancy(tmp_path) -> None:
    p = _pos("7777", "UNKNOWN_SYM", OrderSide.BUY, 0.2)
    gateway = MockGateway([p])  # Untracked broker position
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    store = SQLiteExecutionSafetyStore(tmp_path / "safety.sqlite3", initialize=True)
    settings = Settings(
        _env_file=None,
        emergency_stop=EmergencyStopState.CLEAR,
        broker_execution_enabled=True,
    )

    callback_called = False
    async def mock_callback(report: AuditReconciliationReport) -> None:
        nonlocal callback_called
        callback_called = True

    service = ContinuousTerminalReconciliationService(
        auditor,
        safety_store=store,
        settings=settings,
        on_circuit_break=mock_callback,
    )

    report = await service.reconcile_and_protect()
    assert report.is_clean is False
    assert report.emergency_stop_tripped is True
    assert service.is_emergency_stop_latched is True

    # Check that settings were latched
    assert settings.emergency_stop is EmergencyStopState.ACTIVE
    assert settings.broker_execution_enabled is False

    # Check callback was fired
    assert callback_called is True

    # Check safety snapshot was persisted to SQLite
    snapshot = store.read()
    assert snapshot is not None
    assert snapshot.emergency_stop_state is EmergencyStopState.ACTIVE
    assert snapshot.execution_authorization is ExecutionAuthorization.BLOCKED
    assert "UNTRACKED_BROKER_POSITION" in snapshot.reason_codes


# ---------------------------------------------------------------------------
# 4. Background Monitor Loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_run_loop_halts_on_breach() -> None:
    gateway = MockGateway([])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    settings = Settings(_env_file=None, emergency_stop=EmergencyStopState.CLEAR)
    service = ContinuousTerminalReconciliationService(auditor, settings=settings)

    # Schedule discrepancy injection after short sleep
    async def inject_fault():
        await asyncio.sleep(0.05)
        gateway.set_positions([_pos("9999", "ROGUE_TRADE", OrderSide.SELL, 1.0)])

    asyncio.create_task(inject_fault())

    # Run monitor with fast poll interval
    await service.run_loop(poll_interval_seconds=0.02)

    # Monitor must have stopped after tripping
    assert service.is_emergency_stop_latched is True
    assert settings.emergency_stop is EmergencyStopState.ACTIVE


@pytest.mark.asyncio
async def test_service_run_loop_stops_on_event() -> None:
    gateway = MockGateway([])
    auditor = TerminalReconciliationAuditor(gateway, broker="weltrade")
    settings = Settings(_env_file=None, emergency_stop=EmergencyStopState.CLEAR)
    service = ContinuousTerminalReconciliationService(auditor, settings=settings)

    stop_event = asyncio.Event()

    async def trigger_stop():
        await asyncio.sleep(0.05)
        stop_event.set()

    asyncio.create_task(trigger_stop())

    await service.run_loop(poll_interval_seconds=0.02, stop_event=stop_event)
    assert service.is_emergency_stop_latched is False
