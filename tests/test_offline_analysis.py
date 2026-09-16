"""Deterministic analysis-only publication safety tests."""

from datetime import datetime, timedelta, timezone
import inspect

import pytest

from api.service import ApplicationService
from broker.types import Candle, Timeframe
from config.settings import settings
from core.exceptions import MarketDataError
from execution.simulation_daily_guard import SQLiteSimulationDailySubmissionGuard
from monitoring.offline_analysis import run_offline_analysis, validate_closed_dataset


FIXED_NOW = datetime(2026, 9, 14, 15, 23, tzinfo=timezone.utc)
SCOPE = "simulation:JQE-DASHBOARD-PAPER"


@pytest.mark.asyncio
async def test_cycle_is_deterministic_and_canonical_result_remains_authoritative() -> None:
    first = await run_offline_analysis(
        symbol="R_75", timeframe=Timeframe.H1, seed=62061, count=500,
        observed_at=FIXED_NOW,
    )
    second = await run_offline_analysis(
        symbol="R_75", timeframe=Timeframe.H1, seed=62061, count=500,
        observed_at=FIXED_NOW,
    )
    assert first.dataset_hash == second.dataset_hash
    assert first.direction == second.direction
    assert first.confidence_score == second.confidence_score
    assert first.direction in {"BUY", "SELL", "NO_TRADE"}
    if first.direction == "NO_TRADE":
        assert first.risk_authorization.status == "BLOCKED"
        assert "NO_TRADE" in first.reason_codes
    else:
        assert first.risk_authorization.status == "NOT_EVALUATED"
    assert first.execution_authorization.status == "BLOCKED"
    assert "ANALYSIS_ONLY" in first.reason_codes


@pytest.mark.asyncio
async def test_natural_no_trade_fixture_remains_authoritative() -> None:
    result = await run_offline_analysis(
        symbol="R_75", timeframe=Timeframe.H1, seed=1, count=500,
        observed_at=FIXED_NOW,
    )
    assert result.direction == "NO_TRADE"
    assert result.risk_authorization.status == "BLOCKED"
    assert result.execution_authorization.status == "BLOCKED"
    assert result.reason_codes == ["NO_TRADE", "ANALYSIS_ONLY"]


def test_open_candle_is_rejected() -> None:
    candle = Candle(
        time=FIXED_NOW.replace(minute=0), open=100, high=101, low=99,
        close=100, volume=10, source="simulation",
    )
    with pytest.raises(MarketDataError, match="Incomplete/open"):
        validate_closed_dataset([candle], timeframe=Timeframe.H1, observed_at=FIXED_NOW)


def test_stale_candles_cannot_be_published_fresh() -> None:
    candle = Candle(
        time=FIXED_NOW.replace(hour=12, minute=0), open=100, high=101, low=99,
        close=100, volume=10, source="simulation",
    )
    with pytest.raises(MarketDataError, match="Stale offline data"):
        validate_closed_dataset([candle], timeframe=Timeframe.H1, observed_at=FIXED_NOW)


@pytest.mark.asyncio
async def test_analysis_publication_never_consumes_guard_or_selects_broker(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "dashboard_paper_store_path", tmp_path / "paper.sqlite3")
    monkeypatch.setattr(settings, "simulation_daily_submission_store_path", tmp_path / "daily.sqlite3")
    monkeypatch.setattr(settings, "offline_analysis_seed", 62061)
    service = ApplicationService()
    monkeypatch.setattr(service, "_get_gateway", lambda: (_ for _ in ()).throw(AssertionError("broker selected")))
    guard = SQLiteSimulationDailySubmissionGuard(
        settings.simulation_daily_submission_store_path,
        limit=settings.simulation_daily_submission_limit,
    )
    before = guard.status(SCOPE).count
    setup = await service.run_offline_analysis("R_75", "H1")
    after = guard.status(SCOPE).count
    assert setup.execution_authorization.status == "BLOCKED"
    assert before == after == 0


def test_analysis_module_has_no_execution_or_real_broker_reachability() -> None:
    import monitoring.offline_analysis as module

    source = inspect.getsource(module).lower()
    forbidden = (
        "orderrequest", "executionintent", "asynctradeexecutor", "submit_order",
        "order_send", "get_gateway", "mt5gateway", "derivgateway",
        "sqliteoneshotexecutionguard", "sqlitesimulationdailysubmissionguard",
    )
    assert not any(name in source for name in forbidden)
