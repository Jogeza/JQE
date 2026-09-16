"""Tests for main.py's orchestration logic (run / main).

The BrokerGateway is mocked at the ``main`` module boundary — these
tests verify JQE's own control flow (error mapping, guaranteed
disconnect via the gateway's async context manager, top-level error
handling, and the signal -> risk -> order-submission sequence), not
the behavior of any specific broker or the strategy/risk logic itself.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

import main
from broker.types import (
    AccountInfo,
    OrderResult,
    OrderSide,
    OrderStatus,
    TradeHistoryCompleteness,
    TradeHistorySnapshot,
)
from config import EmergencyStopState, settings
from core.exceptions import MarketDataError


@pytest.fixture(autouse=True)
def _durable_simulation_settings(tmp_path):
    original = (
        settings.broker,
        settings.intent_store_path,
        settings.execution_safety_store_path,
        settings.emergency_stop,
        settings.market_data_source,
        settings.daily_instrument_trade_store_path,
        settings.max_daily_trades_per_instrument,
    )
    settings.broker = "simulation"
    settings.intent_store_path = tmp_path / "intents.sqlite3"
    settings.execution_safety_store_path = tmp_path / "safety.sqlite3"
    settings.emergency_stop = EmergencyStopState.CLEAR
    settings.market_data_source = "simulation"
    settings.daily_instrument_trade_store_path = tmp_path / "daily-instrument.sqlite3"
    settings.max_daily_trades_per_instrument = 20
    yield
    (
        settings.broker,
        settings.intent_store_path,
        settings.execution_safety_store_path,
        settings.emergency_stop,
        settings.market_data_source,
        settings.daily_instrument_trade_store_path,
        settings.max_daily_trades_per_instrument,
    ) = original


def _fake_gateway(candles: list, balance: float = 1000.0) -> MagicMock:
    """A MagicMock configured to behave like an async-context-managed gateway."""
    gateway = MagicMock()
    gateway.__aenter__ = AsyncMock(return_value=gateway)
    gateway.__aexit__ = AsyncMock(return_value=None)
    gateway.get_candles = AsyncMock(return_value=candles)
    gateway.get_account_info = AsyncMock(
        return_value=AccountInfo(account_id="SIMULATED", balance=balance, currency="USD")
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
            order_id="TEST-1",
            status=OrderStatus.FILLED,
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.01,
            filled_price=100.0,
        )
    )
    async def submit_from_observation(order, observation):
        return await gateway.submit_order(order)
    gateway.submit_order_from_market_observation = AsyncMock(side_effect=submit_from_observation)
    return gateway


def _valid_candle() -> MagicMock:
    candle = MagicMock()
    candle.model_dump.return_value = {
        "time": pd.Timestamp.now(),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1.0,
        "ATR_14": 1.0,
    }
    return candle


@asynccontextmanager
async def _empty_market_source(_settings):
    class Source:
        async def get_candles(self, **_kwargs):
            return []
    yield Source(), "fixture"


class TestRun:
    @patch("main.get_gateway")
    async def test_raises_market_data_error_when_no_candles(
        self, mock_get_gateway: MagicMock
    ) -> None:
        mock_get_gateway.return_value = _fake_gateway([])
        with patch("main.resolved_market_source", _empty_market_source), pytest.raises(MarketDataError):
            await main.run()

    @patch("main.validate_market_data", return_value=False)
    @patch("main.get_gateway")
    async def test_raises_market_data_error_when_validation_fails(
        self, mock_get_gateway: MagicMock, mock_validate: MagicMock
    ) -> None:
        candle = MagicMock()
        candle.model_dump.return_value = {
            "time": pd.Timestamp.now(),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
        mock_get_gateway.return_value = _fake_gateway([candle])
        with pytest.raises(MarketDataError):
            await main.run()

    @patch("main.get_gateway")
    async def test_gateway_context_manager_always_exits(self, mock_get_gateway: MagicMock) -> None:
        gateway = _fake_gateway([])
        mock_get_gateway.return_value = gateway
        with patch("main.resolved_market_source", _empty_market_source), pytest.raises(MarketDataError):
            await main.run()
        gateway.__aexit__.assert_called_once()


class TestRunSignalRiskExecution:
    @patch("main.approve_trade")
    @patch("main.generate_trading_signal")
    @patch("main.detect_regime", return_value="TREND_UP")
    @patch("main.validate_market_data", return_value=True)
    @patch("main.get_gateway")
    async def test_order_submitted_when_risk_approves(
        self,
        mock_get_gateway: MagicMock,
        mock_validate: MagicMock,
        mock_detect_regime: MagicMock,
        mock_generate_signal: MagicMock,
        mock_approve_trade: MagicMock,
    ) -> None:
        gateway = _fake_gateway([_valid_candle()])
        mock_get_gateway.return_value = gateway
        mock_generate_signal.return_value = {
            "signal": "BUY",
            "confidence": 90,
            "quality": "HIGH",
            "score": 95,
            "reasons": [],
            "intelligence": {"atr": 1.0},
        }
        mock_approve_trade.return_value = {
            "approved": True,
            "reason": "ok",
            "risk_percent": 0.5,
            "authorized_risk_amount": 5.0,
            "lot_size": 0.05,
        }

        await main.run()

        assert gateway.get_account_info.await_count == 2
        gateway.submit_order.assert_awaited_once()
        submitted_order = gateway.submit_order.call_args[0][0]
        assert submitted_order.symbol == settings.default_symbol == "R_75"
        assert submitted_order.side is OrderSide.BUY
        assert submitted_order.volume == 2.5

    @patch("main.approve_trade")
    @patch("main.generate_trading_signal")
    @patch("main.detect_regime", return_value="RANGE")
    @patch("main.validate_market_data", return_value=True)
    @patch("main.get_gateway")
    async def test_no_order_submitted_when_risk_rejects(
        self,
        mock_get_gateway: MagicMock,
        mock_validate: MagicMock,
        mock_detect_regime: MagicMock,
        mock_generate_signal: MagicMock,
        mock_approve_trade: MagicMock,
    ) -> None:
        gateway = _fake_gateway([_valid_candle()])
        mock_get_gateway.return_value = gateway
        mock_generate_signal.return_value = {
            "signal": "NO_TRADE",
            "confidence": 0,
            "quality": "POOR",
            "score": 0,
            "reasons": [],
            "intelligence": {"atr": 1.0},
        }
        mock_approve_trade.return_value = {
            "approved": False,
            "reason": "No trade signal",
            "risk_percent": 0,
            "lot_size": 0,
        }

        await main.run()

        gateway.submit_order.assert_not_awaited()

    @patch("main.approve_trade")
    @patch("main.generate_trading_signal")
    @patch("main.detect_regime", return_value="TREND_UP")
    @patch("main.validate_market_data", return_value=True)
    @patch("main.get_gateway")
    async def test_risk_engine_receives_real_account_balance(
        self,
        mock_get_gateway: MagicMock,
        mock_validate: MagicMock,
        mock_detect_regime: MagicMock,
        mock_generate_signal: MagicMock,
        mock_approve_trade: MagicMock,
    ) -> None:
        gateway = _fake_gateway([_valid_candle()], balance=54321.0)
        mock_get_gateway.return_value = gateway
        mock_generate_signal.return_value = {
            "signal": "BUY",
            "confidence": 90,
            "quality": "HIGH",
            "score": 95,
            "reasons": [],
            "intelligence": {"atr": 1.0},
        }
        mock_approve_trade.return_value = {
            "approved": False,
            "reason": "test",
            "risk_percent": 0,
            "lot_size": 0,
        }

        await main.run()

        _, kwargs = mock_approve_trade.call_args
        assert kwargs["balance"] == 54321.0

    """main() is the outermost boundary: JQEError must never escape it."""

    @patch("main.asyncio.run", side_effect=MarketDataError("boom"))
    def test_catches_jqe_error_and_does_not_raise(self, mock_run: MagicMock) -> None:
        main.main()  # must not raise

    @patch("main.asyncio.run", side_effect=ValueError("unexpected, non-platform error"))
    def test_non_jqe_error_still_propagates(self, mock_run: MagicMock) -> None:
        with pytest.raises(ValueError):
            main.main()
