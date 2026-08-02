"""Tests for backtesting.backtest.run_backtest.

The BrokerGateway is mocked at the ``backtest`` module boundary —
these tests verify JQE's own orchestration (error mapping, guaranteed
disconnect via the gateway's async context manager), not the behavior
of any specific broker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backtesting import backtest
from core.exceptions import MarketDataError


def _fake_gateway(candles: list) -> MagicMock:
    gateway = MagicMock()
    gateway.__aenter__ = AsyncMock(return_value=gateway)
    gateway.__aexit__ = AsyncMock(return_value=None)
    gateway.get_candles = AsyncMock(return_value=candles)
    return gateway


class TestModuleImport:
    def test_importing_module_has_no_side_effects(self) -> None:
        # Regression guard: backtesting/backtest.py used to be a top-level
        # script that connected to MT5 and ran a full backtest at import
        # time. Importing it now must be inert.
        assert callable(backtest.run_backtest)


class TestRunBacktest:
    @patch("backtesting.backtest.get_gateway")
    async def test_raises_market_data_error_when_no_data(self, mock_get_gateway: MagicMock) -> None:
        mock_get_gateway.return_value = _fake_gateway([])
        with pytest.raises(MarketDataError):
            await backtest.run_backtest()

    @patch("backtesting.backtest.get_gateway")
    async def test_gateway_context_manager_always_exits(self, mock_get_gateway: MagicMock) -> None:
        gateway = _fake_gateway([])
        mock_get_gateway.return_value = gateway
        with pytest.raises(MarketDataError):
            await backtest.run_backtest()
        gateway.__aexit__.assert_called_once()
