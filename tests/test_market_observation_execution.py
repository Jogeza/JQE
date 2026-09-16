"""Checkpoint-1 tests for read-only market observations and simulation fills."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import main
from broker.simulation_gateway import SimulationGateway
from broker.types import Candle, OrderSide, Timeframe
from config import EmergencyStopState, settings
from core.exceptions import ConfigurationError, ExecutionError, MarketDataError
from data.market_observation import closed_observations_from_candles


def _candles(*, close: float = 2_345.67, count: int = 3) -> list[Candle]:
    last_open = datetime.now(timezone.utc) - timedelta(hours=2)
    return [
        Candle(
            time=last_open - timedelta(hours=count - index - 1),
            open=close - 2,
            high=close + 3,
            low=close - 4,
            close=close,
            volume=10.0,
            source="deriv",
        )
        for index in range(count)
    ]


@pytest.fixture(autouse=True)
def _settings(tmp_path):
    original = (
        settings.broker, settings.market_data_source, settings.default_candle_count,
        settings.intent_store_path, settings.execution_safety_store_path,
        settings.emergency_stop, settings.default_symbol,
        settings.daily_instrument_trade_store_path,
    )
    settings.broker = "simulation"
    settings.market_data_source = "deriv_public"
    settings.default_candle_count = 2
    settings.intent_store_path = tmp_path / "intents.sqlite3"
    settings.execution_safety_store_path = tmp_path / "safety.sqlite3"
    settings.emergency_stop = EmergencyStopState.CLEAR
    settings.default_symbol = "XAUUSD"
    settings.daily_instrument_trade_store_path = tmp_path / "daily-instrument.sqlite3"
    yield
    (
        settings.broker, settings.market_data_source, settings.default_candle_count,
        settings.intent_store_path, settings.execution_safety_store_path,
        settings.emergency_stop, settings.default_symbol,
        settings.daily_instrument_trade_store_path,
    ) = original


@asynccontextmanager
async def _public_fixture_source(_settings):
    class PublicOnlySource:
        async def get_candles(self, *, symbol, timeframe, count):
            assert symbol == "frxXAUUSD"
            assert timeframe is Timeframe.M5
            assert count == 3
            return _candles()
    yield PublicOnlySource(), "deriv_public"


@asynccontextmanager
async def _failed_public_source(_settings):
    class PublicOnlySource:
        async def get_candles(self, **_kwargs):
            raise MarketDataError("fixture public source unavailable")
    yield PublicOnlySource(), "deriv_public"


def _approved_plan():
    return SimpleNamespace(
        symbol="XAUUSD", signal="BUY", stop_loss=2_340.0, take_profit=2_356.0,
        warnings=[], invalidation=None, is_valid=lambda: True,
    )


@pytest.mark.asyncio
async def test_public_closed_candle_drives_exact_simulation_fill() -> None:
    gateway = SimulationGateway(starting_balance=1_000.0)
    captured = []
    original_submit = gateway.submit_order_from_market_observation

    async def capture(order, observation):
        result = await original_submit(order, observation)
        captured.append((order, observation, result))
        return result

    with (
        patch("main.get_gateway", return_value=gateway),
        patch("main.resolved_market_source", _public_fixture_source),
        patch("main.validate_market_data", return_value=True),
        patch("main.calculate_indicators", side_effect=lambda frame: frame.assign(ATR=2.0)),
        patch("main.detect_regime", return_value="TREND_UP"),
        patch("main.generate_trading_signal", return_value={
            "signal": "BUY", "confidence": 90, "intelligence": {"atr": 2.0},
        }),
        patch("main.approve_trade", return_value={
            "approved": True, "reason": "ok", "risk_percent": 1.0,
            "authorized_risk_amount": 10.0,
        }),
        patch("main.TradePlanBuilder.build", return_value=_approved_plan()),
        patch.object(gateway, "submit_order_from_market_observation", side_effect=capture),
    ):
        await main.run()

    assert len(captured) == 1
    order, observation, result = captured[0]
    assert observation.canonical_symbol == order.symbol == "XAUUSD"
    assert observation.provider_symbol == "frxXAUUSD"
    assert observation.close == 2_345.67
    assert result.filled_price == observation.reference_price == 2_345.67
    assert result.filled_price != 100.0


def test_forming_candle_is_excluded_and_fails_closed_when_no_closed_candle() -> None:
    candle = Candle(
        time=datetime.now(timezone.utc) - timedelta(minutes=1),
        open=100, high=101, low=99, close=100, source="deriv",
    )
    with pytest.raises(MarketDataError, match="provably closed"):
        closed_observations_from_candles(
            candles=[candle], canonical_symbol="XAUUSD", provider_symbol="frxXAUUSD",
            source="deriv_public", timeframe=Timeframe.M5,
        )


@pytest.mark.asyncio
async def test_cross_symbol_trade_plan_fails_before_simulation_submission() -> None:
    gateway = SimulationGateway()
    invalid = _approved_plan()
    invalid.symbol = "EURUSD"
    with (
        patch("main.get_gateway", return_value=gateway),
        patch("main.resolved_market_source", _public_fixture_source),
        patch("main.validate_market_data", return_value=True),
        patch("main.calculate_indicators", side_effect=lambda frame: frame.assign(ATR=2.0)),
        patch("main.detect_regime", return_value="TREND_UP"),
        patch("main.generate_trading_signal", return_value={"signal": "BUY", "confidence": 90, "intelligence": {"atr": 2.0}}),
        patch("main.approve_trade", return_value={"approved": True, "reason": "ok", "risk_percent": 1.0, "authorized_risk_amount": 10.0}),
        patch("main.TradePlanBuilder.build", return_value=invalid),
    ):
        with pytest.raises(ExecutionError, match="Trade plan symbol"):
            await main.run()
    assert gateway._positions == {}


@pytest.mark.asyncio
async def test_public_data_failure_stops_before_simulation_submission() -> None:
    gateway = SimulationGateway()
    with patch("main.get_gateway", return_value=gateway), patch(
        "main.resolved_market_source", _failed_public_source
    ), pytest.raises(MarketDataError, match="fixture public source unavailable"):
        await main.run()
    assert gateway._positions == {}


@pytest.mark.asyncio
async def test_risk_rejection_keeps_the_observation_out_of_simulation_submission() -> None:
    gateway = SimulationGateway()
    with (
        patch("main.get_gateway", return_value=gateway),
        patch("main.resolved_market_source", _public_fixture_source),
        patch("main.validate_market_data", return_value=True),
        patch("main.calculate_indicators", side_effect=lambda frame: frame.assign(ATR=2.0)),
        patch("main.detect_regime", return_value="TREND_UP"),
        patch("main.generate_trading_signal", return_value={"signal": "BUY", "confidence": 90, "intelligence": {"atr": 2.0}}),
        patch("main.approve_trade", return_value={"approved": False, "reason": "risk rejected", "risk_percent": 0.0}),
    ):
        await main.run()
    assert gateway._positions == {}


@pytest.mark.asyncio
async def test_emergency_stop_blocks_the_observation_before_a_simulation_fill() -> None:
    settings.emergency_stop = EmergencyStopState.ACTIVE
    gateway = SimulationGateway()
    with (
        patch("main.get_gateway", return_value=gateway),
        patch("main.resolved_market_source", _public_fixture_source),
        patch("main.validate_market_data", return_value=True),
        patch("main.calculate_indicators", side_effect=lambda frame: frame.assign(ATR=2.0)),
        patch("main.detect_regime", return_value="TREND_UP"),
        patch("main.generate_trading_signal", return_value={"signal": "BUY", "confidence": 90, "intelligence": {"atr": 2.0}}),
        patch("main.approve_trade", return_value={"approved": True, "reason": "ok", "risk_percent": 1.0, "authorized_risk_amount": 10.0}),
        patch("main.TradePlanBuilder.build", return_value=_approved_plan()),
    ):
        await main.run()
    assert gateway._positions == {}


@pytest.mark.asyncio
async def test_non_simulation_configuration_rejects_before_any_gateway_factory_call() -> None:
    settings.broker = "deriv"
    factory = MagicMock()
    with patch("main.get_gateway", factory), pytest.raises(ConfigurationError, match="simulation only"):
        await main.run()
    factory.assert_not_called()
