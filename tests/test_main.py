"""Tests for main.py's orchestration logic (run / main).

The BrokerGateway is mocked at the ``main`` module boundary — these
tests verify JQE's own control flow (error mapping, guaranteed
disconnect via the gateway's async context manager, top-level error
handling), not the behavior of any specific broker.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

import main
from core.exceptions import MarketDataError


def _fake_gateway(candles: list) -> MagicMock:
    """A MagicMock configured to behave like an async-context-managed gateway."""
    gateway = MagicMock()
    gateway.__aenter__ = AsyncMock(return_value=gateway)
    gateway.__aexit__ = AsyncMock(return_value=None)
    gateway.get_candles = AsyncMock(return_value=candles)
    return gateway


class TestRun:
    @patch("main.get_gateway")
    async def test_raises_market_data_error_when_no_candles(
        self, mock_get_gateway: MagicMock
    ) -> None:
        mock_get_gateway.return_value = _fake_gateway([])
        with pytest.raises(MarketDataError):
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
        with pytest.raises(MarketDataError):
            await main.run()
        gateway.__aexit__.assert_called_once()


class TestMain:
    """main() is the outermost boundary: JQEError must never escape it."""

    @patch("main.asyncio.run", side_effect=MarketDataError("boom"))
    def test_catches_jqe_error_and_does_not_raise(self, mock_run: MagicMock) -> None:
        main.main()  # must not raise

    @patch("main.asyncio.run", side_effect=ValueError("unexpected, non-platform error"))
    def test_non_jqe_error_still_propagates(self, mock_run: MagicMock) -> None:
        with pytest.raises(ValueError):
            main.main()
