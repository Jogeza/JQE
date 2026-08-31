"""Tests for api package (Application API Boundary)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from api.app import create_app
from api.dto import (
    CandlesResponse,
    ExecutionStateResponse,
    ExecutionSafetyResponse,
    MarketSummaryResponse,
    PerformanceSummaryResponse,
    RiskStatusResponse,
    SignalResponse,
    SystemStatusResponse,
)
from api.routes import (
    get_execution_state,
    get_execution_safety,
    get_market_candles,
    get_market_summary,
    get_performance_summary,
    get_risk_status,
    get_strategy_signal,
    get_system_status,
)
from api.service import ApplicationService, _maximum_realized_drawdown
from broker.simulation_gateway import SimulationGateway
from config.settings import Settings, settings
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    SQLiteExecutionSafetyStore,
)


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="development",
        broker="simulation",
        default_symbol="XAUUSD",
        default_timeframe="H1",
        default_candle_count=50,
    )


@pytest.fixture
def sim_service(test_settings: Settings) -> ApplicationService:
    gateway = SimulationGateway(starting_balance=100.0)
    return ApplicationService(gateway=gateway)


@pytest.mark.asyncio
class TestApplicationService:
    async def test_execution_safety_missing_store_is_not_observed_and_read_only(
        self, tmp_path, monkeypatch
    ) -> None:
        path = tmp_path / "missing.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        with patch("api.service.get_gateway") as gateway, patch(
            "api.service.SQLiteExecutionSafetyStore.publish"
        ) as publish:
            response = ApplicationService().get_execution_safety()
        assert response.observation_state == "NOT_OBSERVED"
        assert response.execution_authorization == "NOT_EVALUATED"
        assert path.exists() is False
        gateway.assert_not_called()
        publish.assert_not_called()

    async def test_execution_safety_fresh_and_stale_states(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "execution_safety_freshness_seconds", 15)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        def snapshot(observed_at):
            return ExecutionSafetySnapshot(
                observed_at=observed_at, emergency_stop_state=EmergencyStopState.CLEAR,
                execution_mode=ExecutionMode.DURABLE, broker="simulation",
                environment="development", durable_executor_enabled=True,
                daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
                unresolved_intent_count=0, unresolved_intent_blocked=False,
                execution_authorization=ExecutionAuthorization.AUTHORIZED,
                reason_codes=("ALLOWED",),
            )
        store.publish(snapshot(datetime.now(timezone.utc)))
        fresh = ApplicationService().get_execution_safety()
        assert fresh.observation_state == "OBSERVED"
        assert fresh.execution_authorization == "AUTHORIZED"
        store.publish(snapshot(datetime.now(timezone.utc) - timedelta(seconds=16)))
        stale = ApplicationService().get_execution_safety()
        assert stale.observation_state == "STALE"
        assert stale.execution_authorization == "UNKNOWN"
        assert stale.emergency_stop_state == "UNKNOWN"

    async def test_execution_safety_malformed_store_is_unavailable(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        store.publish(ExecutionSafetySnapshot(
            observed_at=datetime.now(timezone.utc), emergency_stop_state=EmergencyStopState.ACTIVE,
            execution_mode=ExecutionMode.DURABLE, broker="simulation", environment="development",
            durable_executor_enabled=True, daily_state_authority=DailyStateAuthority.NOT_EVALUATED,
            unresolved_intent_count=0, unresolved_intent_blocked=False,
            execution_authorization=ExecutionAuthorization.BLOCKED, reason_codes=("EMERGENCY_STOP",),
        ))
        import sqlite3
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE execution_safety_snapshot SET emergency_stop_state='BROKEN'")
        response = ApplicationService().get_execution_safety()
        assert response.observation_state == "UNAVAILABLE"
        assert response.execution_authorization == "UNKNOWN"
    async def test_get_market_summary_returns_valid_dto(
        self, sim_service: ApplicationService
    ) -> None:
        summary = await sim_service.get_market_summary(symbol="XAUUSD", count=30)
        assert isinstance(summary, MarketSummaryResponse)
        assert summary.symbol == "XAUUSD"
        assert summary.latest_close > 0
        assert summary.atr >= 0
        assert 0 <= summary.rsi <= 100
        assert summary.price_decimals == 2

    async def test_get_market_candles_returns_valid_series(
        self, sim_service: ApplicationService
    ) -> None:
        candles_resp = await sim_service.get_market_candles(symbol="XAUUSD", count=25)
        assert isinstance(candles_resp, CandlesResponse)
        assert candles_resp.count == 25
        assert len(candles_resp.candles) == 25
        assert candles_resp.price_decimals == 2
        first = candles_resp.candles[0]
        assert first.open > 0
        assert first.close > 0

    async def test_get_strategy_signal_includes_confidence_and_plan(
        self, sim_service: ApplicationService
    ) -> None:
        signal_resp = await sim_service.get_strategy_signal(symbol="XAUUSD", count=40)
        assert isinstance(signal_resp, SignalResponse)
        assert signal_resp.symbol == "XAUUSD"
        assert signal_resp.signal in ("BUY", "SELL", "NO_TRADE")
        assert 0 <= signal_resp.confidence <= 100
        assert signal_resp.confidence_breakdown is not None
        assert 0 <= signal_resp.confidence_breakdown.total <= 100
        assert signal_resp.trade_plan is not None
        assert signal_resp.price_decimals == 2

    async def test_get_risk_status_returns_limits_and_balance(
        self, sim_service: ApplicationService
    ) -> None:
        risk_resp = await sim_service.get_risk_status(symbol="XAUUSD")
        assert isinstance(risk_resp, RiskStatusResponse)
        assert risk_resp.balance == 100.0
        assert risk_resp.max_daily_loss > 0
        assert risk_resp.max_trades_daily > 0
        assert risk_resp.risk_allowed is True
        assert risk_resp.model_dump()["recommended_lot_size"] == 0.0
        assert RiskStatusResponse.model_fields["recommended_lot_size"].deprecated is True

    async def test_get_execution_state_returns_simulation_state(
        self, sim_service: ApplicationService
    ) -> None:
        exec_resp = await sim_service.get_execution_state()
        assert isinstance(exec_resp, ExecutionStateResponse)
        assert exec_resp.open_positions_count == 0
        assert exec_resp.recent_trades_count == 0
        assert exec_resp.currency == "USD"

    async def test_get_performance_summary_empty_history(
        self, sim_service: ApplicationService
    ) -> None:
        perf_resp = await sim_service.get_performance_summary()
        assert isinstance(perf_resp, PerformanceSummaryResponse)
        assert perf_resp.total_trades == 0
        assert perf_resp.win_rate_percent == 0.0
        assert perf_resp.max_drawdown_amount == 0.0
        assert perf_resp.max_drawdown_percent is None
        assert perf_resp.drawdown_amount_unit == "account_currency"
        assert perf_resp.drawdown_percent_unit == "percent"
        assert perf_resp.currency == "USD"

    async def test_realized_drawdown_does_not_require_synthetic_equity(self) -> None:
        assert _maximum_realized_drawdown([10.0, -4.0, -9.0, 3.0]) == 13.0

    async def test_get_system_status_returns_online(
        self, sim_service: ApplicationService
    ) -> None:
        sys_resp = await sim_service.get_system_status()
        assert isinstance(sys_resp, SystemStatusResponse)
        assert sys_resp.status == "ONLINE"
        assert sys_resp.broker == "simulation"


@pytest.mark.asyncio
class TestApiEndpointsDirect:
    async def test_execution_safety_endpoint(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "missing.sqlite3")
        response = get_execution_safety(service=ApplicationService())
        assert isinstance(response, ExecutionSafetyResponse)
        assert response.observation_state == "NOT_OBSERVED"
    async def test_market_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_market_summary(symbol="XAUUSD", timeframe="H1", count=30, service=sim_service)
        assert resp.symbol == "XAUUSD"

    async def test_candles_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_market_candles(symbol="XAUUSD", timeframe="H1", count=20, service=sim_service)
        assert resp.count == 20

    async def test_signal_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_strategy_signal(symbol="XAUUSD", service=sim_service)
        assert resp.symbol == "XAUUSD"

    async def test_risk_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_risk_status(symbol="XAUUSD", service=sim_service)
        assert resp.balance > 0

    async def test_execution_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_execution_state(service=sim_service)
        assert resp.positions == []

    async def test_performance_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_performance_summary(service=sim_service)
        assert resp.total_trades == 0

    async def test_system_endpoint(self, sim_service: ApplicationService) -> None:
        resp = await get_system_status(service=sim_service)
        assert resp.status == "ONLINE"


class TestAppFactory:
    def test_create_app_initialization(self) -> None:
        app = create_app()
        assert app.title == "JQE Quant Trading API"
        routes = list(app.openapi()["paths"].keys())
        assert "/health" in routes
        assert any("/api/v1" in r for r in routes)
