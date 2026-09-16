"""Safety properties for the offline-only durable daily submission cap."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import inspect

import pytest
from unittest.mock import patch

from execution.simulation_daily_guard import (
    DEMO_DAILY_SUBMISSION_CAP_REACHED,
    SQLiteSimulationDailySubmissionGuard,
    SimulationDailyCapReached,
)
from execution.dashboard_paper import DashboardPaperGateway, DashboardPaperStore
from execution.market_setup import DataFreshnessDTO, HistoricalWinRateDTO, MarketSetup, SetupAuthorizationDTO
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderRequest, OrderSide


SCOPE = "simulation:JQE-DASHBOARD-PAPER"


def test_atomic_cap_enforcement_under_concurrency(tmp_path) -> None:
    guard = SQLiteSimulationDailySubmissionGuard(tmp_path / "daily.sqlite3", limit=1)

    def attempt() -> str:
        try:
            guard.consume(SCOPE)
            return "consumed"
        except SimulationDailyCapReached:
            return DEMO_DAILY_SUBMISSION_CAP_REACHED

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(lambda _: attempt(), range(12)))

    assert results.count("consumed") == 1
    assert results.count(DEMO_DAILY_SUBMISSION_CAP_REACHED) == 11
    assert guard.status(SCOPE).count == 1


def test_utc_day_separation_and_reset_boundary(tmp_path) -> None:
    guard = SQLiteSimulationDailySubmissionGuard(tmp_path / "daily.sqlite3", limit=1)
    first = datetime(2026, 9, 14, 23, 59, tzinfo=timezone.utc)
    second = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
    guard.consume(SCOPE, now=first)
    assert guard.status(SCOPE, now=first).reset_at == second
    assert guard.status(SCOPE, now=second).count == 0
    assert guard.consume(SCOPE, now=second).count == 1


def test_count_persists_across_guard_restart(tmp_path) -> None:
    path = tmp_path / "daily.sqlite3"
    SQLiteSimulationDailySubmissionGuard(path, limit=3).consume(SCOPE)
    assert SQLiteSimulationDailySubmissionGuard(path, limit=3).status(SCOPE).count == 1


def test_pre_submission_rejection_consumes_nothing(tmp_path) -> None:
    guard = SQLiteSimulationDailySubmissionGuard(tmp_path / "daily.sqlite3", limit=1)
    # The policy rejection path only checks availability; mutation owns consume().
    guard.assert_available(SCOPE)
    assert guard.status(SCOPE).count == 0


def test_submission_start_consumes_exactly_once(tmp_path) -> None:
    guard = SQLiteSimulationDailySubmissionGuard(tmp_path / "daily.sqlite3", limit=2)
    status = guard.consume(SCOPE)
    assert status.count == 1
    assert guard.status(SCOPE).count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("timeout"), RuntimeError("mock rejected")])
async def test_failure_after_mock_submission_start_remains_consumed(tmp_path, failure) -> None:
    now = datetime.now(timezone.utc)
    setup = MarketSetup(
        setup_id="guarded", symbol="R_75", timeframe="H1", observed_at=now,
        candle_close_time=now, direction="BUY", setup_state="READY",
        entry_price="100", stop_loss="99", targets=["102"], confidence_score=90,
        confidence_method="TEST", market_regime="TRENDING",
        data_freshness=DataFreshnessDTO(
            status="CURRENT", source="SIMULATION", maximum_age_seconds=7200,
            reason="fresh", freshness_state="FRESH",
        ),
        risk_authorization=SetupAuthorizationDTO(status="AUTHORIZED", reason="ok"),
        execution_authorization=SetupAuthorizationDTO(status="AUTHORIZED", reason="ok"),
        historical_win_rate=HistoricalWinRateDTO(),
    )
    guard = SQLiteSimulationDailySubmissionGuard(tmp_path / "daily.sqlite3", limit=2)
    gateway = DashboardPaperGateway(
        DashboardPaperStore(tmp_path / "paper.sqlite3"), setup, guard, SCOPE,
    )
    order = OrderRequest(
        symbol="R_75", side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
        stop_loss=99, take_profit=102, idempotency_key="guarded",
    )
    with patch("execution.dashboard_paper.PaperContractEngine.open", side_effect=failure):
        with pytest.raises(type(failure)):
            await gateway.submit_order(order)
    assert guard.status(SCOPE).count == 1


def test_guard_cannot_reach_real_gateways_or_order_send(tmp_path) -> None:
    import execution.simulation_daily_guard as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "mt5", "deriv", "order_send", "broker.factory", "demoonlyguard",
        "sqliteoneshotexecutionguard", "orderrequest", "submit_order",
    )
    assert not any(name in source for name in forbidden)
    with pytest.raises(ValueError, match="only accepts simulation"):
        SQLiteSimulationDailySubmissionGuard(tmp_path / "daily.sqlite3", limit=1).consume("mt5:41163130")
