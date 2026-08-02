"""Tests for broker.mt5_gateway.MT5Gateway.

MT5's real terminal isn't available in this environment (Windows-only
SDK — see tests/conftest.py). These tests patch the module-level
``mt5`` object and MT5Gateway's collaborators directly, verifying
MT5Gateway's own mapping/error-handling logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from broker.mt5_gateway import MT5Gateway
from broker.types import OrderRequest, OrderSide, OrderStatus, Timeframe
from core.exceptions import BrokerConnectionError, ExecutionError, MarketDataError


@pytest.fixture
def gateway() -> MT5Gateway:
    return MT5Gateway()


class TestConnectionLifecycle:
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_connect_success(self, mock_connect: MagicMock, gateway: MT5Gateway) -> None:
        await gateway.connect()
        assert gateway.is_connected is True

    @patch("broker.mt5_gateway.mt5_connect", return_value=False)
    async def test_connect_failure_raises(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        with pytest.raises(BrokerConnectionError):
            await gateway.connect()
        assert gateway.is_connected is False

    @patch("broker.mt5_gateway.mt5_disconnect")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_disconnect_marks_not_connected(
        self, mock_connect: MagicMock, mock_disconnect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        await gateway.disconnect()
        assert gateway.is_connected is False
        mock_disconnect.assert_called_once()

    async def test_get_account_info_raises_when_not_connected(self, gateway: MT5Gateway) -> None:
        with pytest.raises(BrokerConnectionError):
            await gateway.get_account_info()


class TestGetAccountInfo:
    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_maps_account_info(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        mock_mt5.account_info.return_value = MagicMock(
            login=12345, balance=1000.0, currency="USD", equity=1010.0, leverage=100.0
        )
        account = await gateway.get_account_info()
        assert account.account_id == "12345"
        assert account.balance == 1000.0

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_account_info_is_none(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        mock_mt5.account_info.return_value = None
        with pytest.raises(BrokerConnectionError):
            await gateway.get_account_info()


class TestGetCandles:
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_maps_market_data_candles(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.get_candles.return_value = [
            {
                "time": "2024-01-01T00:00:00",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
            }
        ]
        candles = await gateway.get_candles("XAUUSD", Timeframe.H1, 1)
        assert len(candles) == 1
        assert candles[0].close == 1.5

    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_no_candles_returned(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.get_candles.return_value = []
        with pytest.raises(MarketDataError):
            await gateway.get_candles("XAUUSD", Timeframe.H1, 10)


class TestSubmitOrder:
    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_rejects_unknown_symbol(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = None
        with pytest.raises(ExecutionError):
            await gateway.submit_order(OrderRequest(symbol="NOPE", side=OrderSide.BUY, volume=0.1))

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_successful_order_fills(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_info_tick.return_value = MagicMock(ask=2000.5, bid=2000.0)
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value = MagicMock(retcode=10009, order=555, price=2000.5)

        result = await gateway.submit_order(
            OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1)
        )
        assert result.status is OrderStatus.FILLED
        assert result.order_id == "555"

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_rejected_order_returns_rejected_status(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_info_tick.return_value = MagicMock(ask=2000.5, bid=2000.0)
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value = MagicMock(retcode=10004, order=None, price=None)

        result = await gateway.submit_order(
            OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1)
        )
        assert result.status is OrderStatus.REJECTED
