"""Tests for backtesting.backtest.run_backtest.

Verifies JQE's own orchestration (error mapping, guaranteed
``mt5.shutdown()``, no import-time side effects) rather than the
statistics/engine logic itself, which is covered separately.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backtesting import backtest
from core.exceptions import BrokerConnectionError, MarketDataError


class TestModuleImport:
    def test_importing_module_has_no_side_effects(self) -> None:
        # Regression guard: backtesting/backtest.py used to be a top-level
        # script that connected to MT5 and ran a full backtest at import
        # time. Importing it now must be inert.
        assert callable(backtest.run_backtest)


class TestRunBacktest:
    @patch("backtesting.backtest.mt5")
    def test_raises_broker_connection_error_when_mt5_init_fails(self, mock_mt5: MagicMock) -> None:
        mock_mt5.initialize.return_value = False
        with pytest.raises(BrokerConnectionError):
            backtest.run_backtest()

    @patch("backtesting.backtest.MarketData")
    @patch("backtesting.backtest.mt5")
    def test_raises_market_data_error_when_no_data(
        self, mock_mt5: MagicMock, mock_market_data_cls: MagicMock
    ) -> None:
        mock_mt5.initialize.return_value = True
        mock_market_data_cls.return_value.get_candles.return_value = []
        with pytest.raises(MarketDataError):
            backtest.run_backtest()
        mock_mt5.shutdown.assert_called_once()

    @patch("backtesting.backtest.MarketData")
    @patch("backtesting.backtest.mt5")
    def test_mt5_shutdown_is_always_called(
        self, mock_mt5: MagicMock, mock_market_data_cls: MagicMock
    ) -> None:
        mock_mt5.initialize.return_value = True
        mock_market_data_cls.return_value.get_candles.return_value = []
        with pytest.raises(MarketDataError):
            backtest.run_backtest()
        mock_mt5.shutdown.assert_called_once()
