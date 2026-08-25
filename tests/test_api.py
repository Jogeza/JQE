"""Tests for api package (Application API Boundary)."""

from __future__ import annotations

import pytest

from api.app import create_app
from api.dto import (
    CandlesResponse,
    ExecutionStateResponse,
    MarketSummaryResponse,
    PerformanceSummaryResponse,
    RiskStatusResponse,
    SignalResponse,
    SystemStatusResponse,
)
from api.routes import (
    get_execution_state,
    get_market_candles,
    get_market_summary,
    get_performance_summary,
    get_risk_status,
    get_strategy_signal,
    get_system_status,
)
from api.service import ApplicationService
from broker.simulation_gateway import SimulationGateway
from config.settings import Settings


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
    async def test_get_market_summary_returns_valid_dto(
        self, sim_service: ApplicationService
    ) -> None:
        summary = await sim_service.get_market_summary(symbol="XAUUSD", count=30)
        assert isinstance(summary, MarketSummaryResponse)
        assert summary.symbol == "XAUUSD"
        assert summary.latest_close > 0
        assert summary.atr >= 0
        assert 0 <= summary.rsi <= 100

    async def test_get_market_candles_returns_valid_series(
        self, sim_service: ApplicationService
    ) -> None:
        candles_resp = await sim_service.get_market_candles(symbol="XAUUSD", count=25)
        assert isinstance(candles_resp, CandlesResponse)
        assert candles_resp.count == 25
        assert len(candles_resp.candles) == 25
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

    async def test_get_risk_status_returns_limits_and_balance(
        self, sim_service: ApplicationService
    ) -> None:
        risk_resp = await sim_service.get_risk_status(symbol="XAUUSD")
        assert isinstance(risk_resp, RiskStatusResponse)
        assert risk_resp.balance == 100.0
        assert risk_resp.max_daily_loss > 0
        assert risk_resp.max_trades_daily > 0
        assert risk_resp.risk_allowed is True

    async def test_get_execution_state_returns_simulation_state(
        self, sim_service: ApplicationService
    ) -> None:
        exec_resp = await sim_service.get_execution_state()
        assert isinstance(exec_resp, ExecutionStateResponse)
        assert exec_resp.open_positions_count == 0
        assert exec_resp.recent_trades_count == 0

    async def test_get_performance_summary_empty_history(
        self, sim_service: ApplicationService
    ) -> None:
        perf_resp = await sim_service.get_performance_summary()
        assert isinstance(perf_resp, PerformanceSummaryResponse)
        assert perf_resp.total_trades == 0
        assert perf_resp.win_rate_percent == 0.0

    async def test_get_system_status_returns_online(
        self, sim_service: ApplicationService
    ) -> None:
        sys_resp = await sim_service.get_system_status()
        assert isinstance(sys_resp, SystemStatusResponse)
        assert sys_resp.status == "ONLINE"
        assert sys_resp.broker == "simulation"


@pytest.mark.asyncio
class TestApiEndpointsDirect:
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
