"""Tests for api package (Application API Boundary)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

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
from tests.weltrade_stubs import WeltradeStubGateway
from broker.types import Candle, Timeframe, TIMEFRAME_SECONDS
from broker.types import Candle, Tick, Timeframe, TIMEFRAME_SECONDS
from config.settings import Settings, settings
from core.exceptions import BrokerConnectionError, MarketDataError
from data.storage import CandleStore
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    RiskAuthorizationSnapshot,
    RiskEvaluationState,
    SQLiteExecutionSafetyStore,
)


def _risk_snapshot(
    observed_at: datetime,
    *,
    broker: str = "weltrade",
    state: RiskEvaluationState = RiskEvaluationState.AUTHORIZED,
    quantity_available: bool = True,
    reason: str = "Offline fixture contract economics",
    account_id: str | None = None,
) -> RiskAuthorizationSnapshot:
    authorized = state is RiskEvaluationState.AUTHORIZED
    if account_id is None and state in (
        RiskEvaluationState.AUTHORIZED, RiskEvaluationState.BLOCKED
    ):
        account_id = "4242"
    return RiskAuthorizationSnapshot(
        observed_at=observed_at,
        broker=broker,
        environment="development",
        account_id=account_id,
        evaluation_state=state,
        balance=100.0,
        equity=100.0,
        currency="USD",
        max_daily_loss=2.0,
        max_trades_daily=5,
        daily_trades_count=1,
        daily_loss_percent=0.25,
        risk_allowed=True,
        risk_message="Limits OK",
        rejection_reason="" if authorized else reason,
        authorized_risk_amount=0.5 if authorized else None,
        authorized_risk_percent=0.5 if authorized else None,
        execution_quantity_available=quantity_available,
        execution_quantity_value=0.5 if quantity_available else None,
        execution_quantity_unit="MT5_LOTS" if quantity_available else None,
        execution_quantity_reason=reason,
    )


def test_api_rejects_non_loopback_clients() -> None:
    client = TestClient(create_app(), client=("198.51.100.42", 12345))
    response = client.get("/health")
    assert response.status_code == 403
    assert response.json()["detail"] == "Workstation-local API only"


@pytest.fixture(autouse=True)
def weltrade_context(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "broker", "weltrade")
    monkeypatch.setattr(settings, "market_data_source", "broker")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "weltrade_demo_login", 4242)
    monkeypatch.setattr(settings, "historical_data_path", tmp_path / "history.sqlite3")
    monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "safety.sqlite3")


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="development",
        broker="weltrade",
        default_symbol="XAUUSD",
        default_timeframe="H1",
        default_candle_count=50,
    )


@pytest.fixture
def offline_service(test_settings: Settings, tmp_path, monkeypatch) -> ApplicationService:
    monkeypatch.setattr(settings, "broker", "weltrade")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(
        settings, "execution_safety_store_path", tmp_path / "execution-safety.sqlite3"
    )
    gateway = WeltradeStubGateway(starting_balance=100.0)
    return ApplicationService(gateway=gateway, market_data_source=FakePublicMarketData())


class FakePublicMarketData:
    """Offline-only stand-in for the unauthenticated public candle adapter."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, Timeframe, int]] = []

    async def get_candles(self, symbol, timeframe, count, end=None):
        del end
        self.requests.append((symbol, timeframe, count))
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [
            Candle(
                time=start + timedelta(seconds=TIMEFRAME_SECONDS[timeframe] * index),
                open=1900.0 + index,
                high=1902.0 + index,
                low=1899.0 + index,
                close=1901.0 + index,
                volume=None,
                source="deriv",
            )
            for index in range(count)
        ]


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
    async def test_terminal_observation_uses_direct_gateway_reads(self, monkeypatch) -> None:
        gateway = WeltradeStubGateway(starting_balance=321.0)
        now = datetime.now(timezone.utc)
        closed = Candle(
            time=now - timedelta(minutes=10), open=100.0, high=102.0,
            low=99.0, close=101.0, volume=12.0, source="weltrade",
        )
        gateway.get_latest_tick = AsyncMock(return_value=Tick(
            time=now, symbol="FX Vol 20", bid=100.9, ask=101.1, last=101.0,
        ))
        gateway.get_candles = AsyncMock(return_value=[closed])
        gateway.get_terminal_permissions = AsyncMock(return_value={
            "connected": True, "terminal_trading_allowed": False,
            "trade_api_disabled": True,
        })
        gateway.get_symbol_specification = AsyncMock(return_value={
            "name": "FX Vol 20", "digits": 2, "point": 0.01,
            "trade_tick_size": 0.01, "trade_tick_value": 0.1,
            "contract_size": 1.0, "volume_min": 0.01,
            "volume_step": 0.01, "volume_max": 100.0, "trade_mode": 4,
        })
        service = ApplicationService(gateway=gateway)

        response = await service.get_terminal_observation("FX Vol 20", "M5")

        assert response.state == "CONNECTED"
        assert response.environment == "DEMO"
        assert response.execution_enabled is False
        assert response.tick is not None and response.tick.bid == 100.9
        assert response.candle is not None
        assert response.candle.source == "CURRENT_TERMINAL"
        assert response.candle.close == 101.0
        assert response.symbol_specification is not None
        assert response.symbol_specification.trade_tick_value == 0.1
        gateway.get_candles.assert_awaited_once()
        gateway.get_latest_tick.assert_awaited_once_with("FX Vol 20")

    async def test_execution_safety_fresh_and_stale_states(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "execution_safety_freshness_seconds", 15)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        def snapshot(observed_at):
            return ExecutionSafetySnapshot(
                observed_at=observed_at, emergency_stop_state=EmergencyStopState.CLEAR,
                execution_mode=ExecutionMode.DURABLE, broker="weltrade",
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
            execution_mode=ExecutionMode.DURABLE, broker="weltrade", environment="development",
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
        self, offline_service: ApplicationService
    ) -> None:
        summary = await offline_service.get_market_summary(symbol="XAUUSD", count=30)
        assert isinstance(summary, MarketSummaryResponse)
        assert summary.symbol == "XAUUSD"
        assert summary.latest_close > 0
        assert summary.atr >= 0
        assert 0 <= summary.rsi <= 100
        assert summary.price_decimals == 2

    async def test_get_market_candles_returns_valid_series(
        self, offline_service: ApplicationService
    ) -> None:
        candles_resp = await offline_service.get_market_candles(symbol="XAUUSD", count=25)
        assert isinstance(candles_resp, CandlesResponse)
        assert candles_resp.count == 25
        assert len(candles_resp.candles) == 25
        assert candles_resp.price_decimals == 2
        first = candles_resp.candles[0]
        assert first.open > 0
        assert first.close > 0

    async def test_get_strategy_signal_includes_confidence_and_plan(
        self, offline_service: ApplicationService
    ) -> None:
        signal_resp = await offline_service.get_strategy_signal(symbol="XAUUSD", count=40)
        assert isinstance(signal_resp, SignalResponse)
        assert signal_resp.symbol == "XAUUSD"
        assert signal_resp.signal in ("BUY", "SELL", "NO_TRADE")
        assert 0 <= signal_resp.confidence <= 100
        assert signal_resp.confidence_breakdown is not None
        assert 0 <= signal_resp.confidence_breakdown.total <= 100
        assert signal_resp.trade_plan is not None
        assert signal_resp.price_decimals == 2

    async def test_public_market_source_is_independent_and_read_only(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "broker", "weltrade")
        execution_gateway = WeltradeStubGateway(starting_balance=321.0)
        public_source = FakePublicMarketData()
        service = ApplicationService(
            gateway=execution_gateway, market_data_source=public_source
        )

        summary = await service.get_market_summary("XAUUSD", "M15", 40)
        candles = await service.get_market_candles("XAUUSD", "M15", 40)
        signal = await service.get_strategy_signal("XAUUSD", "M15", 40)

        assert summary.symbol == candles.symbol == signal.symbol == "XAUUSD"
        assert summary.market_data_source == "DERIV_PUBLIC"
        assert candles.market_data_source == "DERIV_PUBLIC"
        assert candles.candles[-1].volume is None
        assert summary.spread is None
        assert all(request[0] == "XAUUSD" for request in public_source.requests)

        public_source.get_candles = AsyncMock(side_effect=AssertionError("market source used"))
        execution = await service.get_execution_state()
        assert execution.broker == "weltrade"
        public_source.get_candles.assert_not_called()

    async def test_configured_weltrade_uses_native_symbol(self, monkeypatch) -> None:
        source = FakePublicMarketData()
        with patch("api.service.get_gateway", return_value=source) as factory:
            response = await ApplicationService().get_market_candles("FX VOL 20", "M15", 5)
        assert source.requests[0][0] == "FX VOL 20"
        assert response.symbol == "FX VOL 20"
        assert response.market_data_source == "BROKER"
        factory.assert_called_once()

    async def test_public_market_failure_does_not_fall_back_to_execution(self) -> None:
        public_source = FakePublicMarketData()
        public_source.get_candles = AsyncMock(side_effect=RuntimeError("public source unavailable"))
        service = ApplicationService(market_data_source=public_source)
        with patch("api.service.get_gateway", side_effect=AssertionError("execution fallback")) as gateway_factory:
            with pytest.raises(RuntimeError, match="public source unavailable"):
                await service.get_market_candles("XAUUSD", "M15", 5)
        gateway_factory.assert_not_called()

    async def test_weltrade_market_failure_returns_truthful_cached_candles(
        self, tmp_path, monkeypatch
    ) -> None:
        cache_path = tmp_path / "historical.sqlite3"
        monkeypatch.setattr(settings, "historical_data_path", cache_path)
        monkeypatch.setattr(settings, "market_data_source", "broker")
        cached = await FakePublicMarketData().get_candles(
            "frxXAUUSD", Timeframe.M5, 20
        )
        CandleStore(cache_path).save_candles(
            "XAUUSD", Timeframe.M5, cached, provider="weltrade"
        )
        failed_source = FakePublicMarketData()
        failed_source.get_candles = AsyncMock(
            side_effect=MarketDataError("public provider unavailable")
        )

        with patch("api.service.get_gateway", return_value=failed_source):
            response = await ApplicationService().get_market_candles(
                "XAUUSD", "M5", 20
            )

        assert response.count == 20
        assert response.market_data_source == "BROKER"
        assert response.market_data_status == "CACHED"
        assert response.stale is True
        assert response.degraded is True
        assert [candle.time for candle in response.candles] == sorted(
            candle.time for candle in response.candles
        )

    async def test_broker_chart_uses_newest_case_insensitive_cache_partition(
        self, tmp_path, monkeypatch
    ) -> None:
        cache_path = tmp_path / "historical.sqlite3"
        monkeypatch.setattr(settings, "historical_data_path", cache_path)
        monkeypatch.setattr(settings, "market_data_source", "broker")
        monkeypatch.setattr(settings, "broker", "weltrade")
        monkeypatch.setattr("api.service._uses_mt5_session", lambda: False)
        now = datetime.now(timezone.utc)

        def candles(symbol: str, latest_close: float, latest_open: datetime) -> list[Candle]:
            return [
                Candle(
                    time=latest_open - timedelta(minutes=5 * (4 - index)),
                    open=latest_close - 1 + index,
                    high=latest_close + 1 + index,
                    low=latest_close - 2 + index,
                    close=latest_close + index,
                    volume=1.0,
                    source="mt5",
                )
                for index in range(5)
            ]

        store = CandleStore(cache_path)
        store.save_candles(
            "FX VOL 20", Timeframe.M5,
            candles("FX VOL 20", 111.0, now - timedelta(hours=2)),
            provider="weltrade",
        )
        store.save_candles(
            "FX Vol 20", Timeframe.M5,
            candles("FX Vol 20", 222.0, now - timedelta(minutes=6)),
            provider="weltrade",
        )

        source = FakePublicMarketData()
        source.get_candles = AsyncMock(side_effect=AssertionError("stale partition selected"))
        service = ApplicationService(gateway=source)

        response = await service.get_market_candles("FX VOL 20", "M5", 5)

        assert response.market_data_status == "CURRENT"
        assert response.stale is False
        assert response.candles[-1].close == 226.0
        assert store.resolve_symbol_partition(
            "FX VOL 20", Timeframe.M5, provider="weltrade"
        ) == "FX Vol 20"
        source.get_candles.assert_not_called()

    async def test_broker_market_refresh_failure_is_logged_before_cache_fallback(
        self, tmp_path, monkeypatch
    ) -> None:
        cache_path = tmp_path / "historical.sqlite3"
        monkeypatch.setattr(settings, "historical_data_path", cache_path)
        monkeypatch.setattr(settings, "market_data_source", "broker")
        monkeypatch.setattr(settings, "broker", "weltrade")
        monkeypatch.setattr("api.service._uses_mt5_session", lambda: False)
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        cached = [
            Candle(
                time=old + timedelta(minutes=5 * index),
                open=100 + index,
                high=102 + index,
                low=99 + index,
                close=101 + index,
                volume=1.0,
                source="mt5",
            )
            for index in range(5)
        ]
        CandleStore(cache_path).save_candles(
            "FX Vol 20", Timeframe.M5, cached, provider="weltrade"
        )
        source = FakePublicMarketData()
        source.get_candles = AsyncMock(
            side_effect=MarketDataError("Weltrade history unavailable")
        )
        service = ApplicationService(gateway=source)

        with patch("api.service.logger.exception") as log_exception:
            response = await service.get_market_candles("FX Vol 20", "M5", 5)

        assert response.market_data_status == "CACHED"
        log_exception.assert_called_once()
        assert log_exception.call_args.args[2] == "FX Vol 20"

    async def test_weltrade_market_failure_without_cache_is_typed_unavailable(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "historical_data_path", tmp_path / "empty.sqlite3")
        monkeypatch.setattr(settings, "market_data_source", "broker")
        failed_source = FakePublicMarketData()
        failed_source.get_candles = AsyncMock(
            side_effect=BrokerConnectionError("public provider timed out")
        )

        with patch("api.service.get_gateway", return_value=failed_source):
            response = await ApplicationService().get_market_candles(
                "XAUUSD", "M5", 20
            )

        assert response.count == 0
        assert response.candles == []
        assert response.market_data_source == "UNAVAILABLE"
        assert response.market_data_status == "UNAVAILABLE"
        assert response.stale is False
        assert response.degraded is True

    async def test_obsolete_market_source_rejects_without_gateway(self, monkeypatch) -> None:
        from core.exceptions import ConfigurationError
        monkeypatch.setattr(settings, "market_data_source", "simulation")
        with patch("api.service.get_gateway") as factory:
            with pytest.raises(ConfigurationError, match="broker market data"):
                await ApplicationService().get_market_candles("FX VOL 20", "M15", 5)
        factory.assert_not_called()

    async def test_fresh_weltrade_risk_observation_exposes_typed_quantity(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "broker", "weltrade")
        monkeypatch.setattr(settings, "environment", "development")
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "risk_observation_freshness_seconds", 15)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        persisted = _risk_snapshot(now - timedelta(seconds=5))
        store.publish_risk(persisted)
        service = ApplicationService()
        with patch("api.service.utc_now", return_value=now), patch.object(
            service, "_get_gateway"
        ) as gateway, patch.object(
            service.risk_engine, "approve_trade"
        ) as approve, patch.object(
            service.risk_engine, "authorize_execution_quantity"
        ) as authorize:
            response = await service.get_risk_status()
        assert response.observation_available is True
        assert response.observation_fresh is True
        assert response.observation_status == "FRESH"
        assert response.observation_age_seconds == 5.0
        assert response.risk_authorized is True
        assert response.authorized_risk_amount == 0.5
        assert response.execution_quantity_available is True
        assert response.execution_quantity_value == 0.5
        assert response.execution_quantity_unit == "MT5_LOTS"
        gateway.assert_not_called()
        approve.assert_not_called()
        authorize.assert_not_called()
        assert store.read_risk() == persisted

    async def test_stale_observation_cannot_leak_previously_authorized_quantity(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "broker", "weltrade")
        monkeypatch.setattr(settings, "environment", "development")
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "risk_observation_freshness_seconds", 15)
        SQLiteExecutionSafetyStore(path, initialize=True).publish_risk(
            _risk_snapshot(now - timedelta(seconds=15, microseconds=1))
        )
        with patch("api.service.utc_now", return_value=now):
            response = await ApplicationService().get_risk_status()
        assert response.observation_status == "STALE"
        assert response.observation_fresh is False
        assert response.approved is False
        assert response.risk_allowed is False
        assert response.risk_authorized is True
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None
        assert response.execution_quantity_unit is None
        assert response.execution_quantity_reason == "Risk observation is stale"

    async def test_exact_freshness_boundary_is_fresh(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(settings, "broker", "weltrade")
        monkeypatch.setattr(settings, "environment", "development")
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "risk_observation_freshness_seconds", 15)
        SQLiteExecutionSafetyStore(path, initialize=True).publish_risk(
            _risk_snapshot(now - timedelta(seconds=15))
        )
        with patch("api.service.utc_now", return_value=now):
            response = await ApplicationService().get_risk_status()
        assert response.observation_status == "FRESH"
        assert response.execution_quantity_available is True

    async def test_missing_observation_is_unavailable_and_read_only(
        self, tmp_path, monkeypatch
    ) -> None:
        path = tmp_path / "missing.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        service = ApplicationService()
        with patch.object(service, "_get_gateway") as gateway, patch.object(
            service.risk_engine, "approve_trade"
        ) as approve, patch.object(
            service.risk_engine, "authorize_execution_quantity"
        ) as authorize:
            response = await service.get_risk_status()
        assert response.observation_status == "NOT_OBSERVED"
        assert response.observation_available is False
        assert response.execution_quantity_available is False
        assert path.exists() is False
        gateway.assert_not_called()
        approve.assert_not_called()
        authorize.assert_not_called()

    async def test_future_timestamp_anomaly_fails_closed(self, tmp_path, monkeypatch) -> None:
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        SQLiteExecutionSafetyStore(path, initialize=True).publish_risk(
            _risk_snapshot(now + timedelta(microseconds=1))
        )
        with patch("api.service.utc_now", return_value=now):
            response = await ApplicationService().get_risk_status()
        assert response.observation_status == "UNAVAILABLE"
        assert response.observation_fresh is False
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None

    @pytest.mark.parametrize(
        ("broker", "state", "reason", "expected_status", "risk_authorized"),
        [
            ("weltrade", RiskEvaluationState.BLOCKED, "No trade signal", "FRESH", False),
            ("weltrade", RiskEvaluationState.AUTHORIZED, "Broker stop-risk conversion is not proven", "FRESH", True),
            ("weltrade", RiskEvaluationState.NOT_EVALUATED, "MT5 execution is disabled", "UNAVAILABLE", False),
        ],
    )
    async def test_broker_specific_unavailable_quantity_observations(
        self, tmp_path, monkeypatch, broker, state, reason, expected_status, risk_authorized
    ) -> None:
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / f"{broker}.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "broker", broker)
        if broker == "deriv":
            monkeypatch.setattr(settings, "deriv_options_account_id", "CR-DEMO")
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        store.publish_risk(_risk_snapshot(
            now, broker=broker, state=state, quantity_available=False, reason=reason
        ))
        with patch("api.service.utc_now", return_value=now):
            response = await ApplicationService().get_risk_status()
        assert response.observation_status == expected_status
        assert response.risk_authorized is risk_authorized
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None
        assert response.execution_quantity_unit is None
        assert reason in (response.execution_quantity_reason or "")

    @pytest.mark.parametrize(
        ("snapshot_broker", "configured_environment", "configured_account"),
        [("deriv", "development", 4242), ("weltrade", "production", 4242),
         ("weltrade", "development", 4343)],
        ids=["broker", "environment", "account"],
    )
    async def test_context_mismatch_is_non_authoritative_and_redacts_quantity(
        self, tmp_path, monkeypatch, snapshot_broker, configured_environment, configured_account,
    ) -> None:
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        SQLiteExecutionSafetyStore(path, initialize=True).publish_risk(
            _risk_snapshot(now, broker=snapshot_broker, account_id="4242")
        )
        monkeypatch.setattr(settings, "environment", configured_environment)
        monkeypatch.setattr(settings, "weltrade_demo_login", configured_account)
        with patch("api.service.utc_now", return_value=now):
            response = await ApplicationService().get_risk_status()
        assert response.observation_status == "CONTEXT_MISMATCH"
        assert response.observation_fresh is False
        assert response.risk_authorized is False
        assert response.authorized_risk_amount is None
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None
        assert response.execution_quantity_unit is None

    async def test_weltrade_account_switch_cannot_reuse_fresh_observation(self, tmp_path, monkeypatch) -> None:
        now = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        monkeypatch.setattr(settings, "weltrade_demo_login", 4343)
        SQLiteExecutionSafetyStore(path, initialize=True).publish_risk(
            _risk_snapshot(now, account_id="4242")
        )
        with patch("api.service.utc_now", return_value=now):
            response = await ApplicationService().get_risk_status()
        assert response.observation_status == "CONTEXT_MISMATCH"
        assert response.execution_quantity_available is False

    async def test_malformed_account_identity_fails_closed(
        self, tmp_path, monkeypatch
    ) -> None:
        import sqlite3
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        store.publish_risk(_risk_snapshot(datetime.now(timezone.utc)))
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE risk_authorization_snapshot SET account_id='   '"
            )
        response = await ApplicationService().get_risk_status()
        assert response.observation_status == "UNAVAILABLE"
        assert response.execution_quantity_available is False

    async def test_legacy_snapshot_without_account_identity_is_unavailable(
        self, tmp_path, monkeypatch
    ) -> None:
        import sqlite3
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        store.publish_risk(_risk_snapshot(datetime.now(timezone.utc)))
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE risk_authorization_snapshot SET schema_version=1, account_id=NULL"
            )
        response = await ApplicationService().get_risk_status()
        assert response.observation_status == "UNAVAILABLE"
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None

    async def test_unknown_future_risk_schema_is_unavailable_and_not_rewritten(
        self, tmp_path, monkeypatch
    ) -> None:
        import sqlite3
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        store.publish_risk(_risk_snapshot(datetime.now(timezone.utc)))
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE risk_authorization_snapshot SET schema_version=99"
            )
        service = ApplicationService()
        with patch.object(service, "_get_gateway") as gateway, patch.object(
            service.risk_engine, "approve_trade"
        ) as approve, patch.object(
            service.risk_engine, "authorize_execution_quantity"
        ) as authorize:
            response = await service.get_risk_status()
        assert response.observation_status == "UNAVAILABLE"
        assert response.observation_fresh is False
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None
        assert response.execution_quantity_unit is None
        gateway.assert_not_called()
        approve.assert_not_called()
        authorize.assert_not_called()
        with sqlite3.connect(path) as connection:
            persisted_version = connection.execute(
                "SELECT schema_version FROM risk_authorization_snapshot WHERE singleton_id=1"
            ).fetchone()[0]
        assert persisted_version == 99

    async def test_malformed_persisted_risk_observation_fails_closed(
        self, tmp_path, monkeypatch
    ) -> None:
        import sqlite3
        path = tmp_path / "safety.sqlite3"
        monkeypatch.setattr(settings, "execution_safety_store_path", path)
        store = SQLiteExecutionSafetyStore(path, initialize=True)
        store.publish_risk(_risk_snapshot(datetime.now(timezone.utc)))
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE risk_authorization_snapshot SET evaluation_state='BROKEN'"
            )
        response = await ApplicationService().get_risk_status()
        assert response.observation_status == "UNAVAILABLE"
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None

    async def test_old_risk_payload_remains_deserializable_with_safe_defaults(self) -> None:
        response = RiskStatusResponse(
            balance=100.0,
            equity=100.0,
            max_daily_loss=2.0,
            max_trades_daily=5,
        )
        assert response.model_dump()["recommended_lot_size"] == 0.0
        assert response.risk_authorized is False
        assert response.execution_quantity_available is False
        assert response.execution_quantity_value is None
        assert response.observation_status == "NOT_OBSERVED"

    async def test_get_execution_state_returns_offline_weltrade_state(
        self, offline_service: ApplicationService
    ) -> None:
        exec_resp = await offline_service.get_execution_state()
        assert isinstance(exec_resp, ExecutionStateResponse)
        assert exec_resp.open_positions_count == 0
        assert exec_resp.recent_trades_count == 0
        assert exec_resp.currency == "USD"

    async def test_get_performance_summary_empty_history(
        self, offline_service: ApplicationService
    ) -> None:
        perf_resp = await offline_service.get_performance_summary()
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
        self, offline_service: ApplicationService
    ) -> None:
        sys_resp = await offline_service.get_system_status()
        assert isinstance(sys_resp, SystemStatusResponse)
        assert sys_resp.status == "ONLINE"
        assert sys_resp.broker == "weltrade"


@pytest.mark.asyncio
class TestApiEndpointsDirect:
    async def test_execution_safety_endpoint(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(settings, "execution_safety_store_path", tmp_path / "missing.sqlite3")
        response = get_execution_safety(service=ApplicationService())
        assert isinstance(response, ExecutionSafetyResponse)
        assert response.observation_state == "NOT_OBSERVED"
    async def test_market_endpoint(self, offline_service: ApplicationService) -> None:
        resp = await get_market_summary(symbol="XAUUSD", timeframe="H1", count=30, service=offline_service)
        assert resp.symbol == "XAUUSD"

    async def test_candles_endpoint(self, offline_service: ApplicationService) -> None:
        resp = await get_market_candles(symbol="XAUUSD", timeframe="H1", count=20, service=offline_service)
        assert resp.count == 20
        assert resp.symbol == "XAUUSD"
        assert resp.timeframe == "H1"
        assert len(resp.candles) == 20
        assert [candle.time for candle in resp.candles] == sorted(candle.time for candle in resp.candles)
        assert resp.candles[0].model_dump().keys() == {
            "time", "open", "high", "low", "close", "volume", "EMA50", "EMA200", "RSI", "ATR"
        }

    async def test_signal_endpoint(self, offline_service: ApplicationService) -> None:
        resp = await get_strategy_signal(symbol="XAUUSD", service=offline_service)
        assert resp.symbol == "XAUUSD"

    async def test_risk_endpoint(self, offline_service: ApplicationService) -> None:
        resp = await get_risk_status(symbol="XAUUSD", service=offline_service)
        assert resp.observation_status == "NOT_OBSERVED"
        assert resp.execution_quantity_available is False

    async def test_execution_endpoint(self, offline_service: ApplicationService) -> None:
        resp = await get_execution_state(service=offline_service)
        assert resp.positions == []

    async def test_performance_endpoint(self, offline_service: ApplicationService) -> None:
        resp = await get_performance_summary(service=offline_service)
        assert resp.total_trades == 0

    async def test_system_endpoint(self, offline_service: ApplicationService, monkeypatch) -> None:
        monkeypatch.setattr(settings, "telegram_enabled", False)
        monkeypatch.setattr(settings, "telegram_bot_token", None)
        monkeypatch.setattr(settings, "telegram_allowed_chat_id", None)
        resp = await get_system_status(service=offline_service)
        assert resp.status == "ONLINE"
        assert resp.broker_identity_state == "NOT_APPLICABLE"  # Injected offline gateway.
        assert resp.telegram_status == "DISABLED"
        assert resp.telegram_configured is False


class TestAppFactory:
    def test_create_app_initialization(self) -> None:
        app = create_app()
        assert app.title == "JQE Quant Trading API"
        routes = list(app.openapi()["paths"].keys())
        assert "/health" in routes
        assert any("/api/v1" in r for r in routes)
