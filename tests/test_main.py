"""Tests for main.py's orchestration logic (run / main).

MT5, market data, and validation calls are mocked at the ``main``
module boundary — these tests verify JQE's own control flow (error
mapping, guaranteed disconnect, top-level error handling), not the
behavior of MT5 or the data/validation modules themselves.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import main
from core.exceptions import BrokerConnectionError, MarketDataError


class TestRun:
    @patch("main.connect", return_value=False)
    def test_raises_broker_connection_error_when_connect_fails(
        self, mock_connect: MagicMock
    ) -> None:
        with pytest.raises(BrokerConnectionError):
            main.run()
        mock_connect.assert_called_once()

    @patch("main.disconnect")
    @patch("main.MarketData")
    @patch("main.connect", return_value=True)
    def test_raises_market_data_error_when_no_candles(
        self,
        mock_connect: MagicMock,
        mock_market_data_cls: MagicMock,
        mock_disconnect: MagicMock,
    ) -> None:
        mock_market_data_cls.return_value.get_candles.return_value = []
        with pytest.raises(MarketDataError):
            main.run()
        mock_disconnect.assert_called_once()

    @patch("main.disconnect")
    @patch("main.validate_market_data", return_value=False)
    @patch("main.MarketData")
    @patch("main.connect", return_value=True)
    def test_raises_market_data_error_when_validation_fails(
        self,
        mock_connect: MagicMock,
        mock_market_data_cls: MagicMock,
        mock_validate: MagicMock,
        mock_disconnect: MagicMock,
    ) -> None:
        mock_market_data_cls.return_value.get_candles.return_value = [
            {"time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}
        ]
        with pytest.raises(MarketDataError):
            main.run()
        mock_disconnect.assert_called_once()

    @patch("main.disconnect")
    @patch("main.MarketData")
    @patch("main.connect", return_value=True)
    def test_disconnect_is_always_called_even_on_failure(
        self,
        mock_connect: MagicMock,
        mock_market_data_cls: MagicMock,
        mock_disconnect: MagicMock,
    ) -> None:
        mock_market_data_cls.return_value.get_candles.return_value = []
        with pytest.raises(MarketDataError):
            main.run()
        mock_disconnect.assert_called_once()


class TestMain:
    """main() is the outermost boundary: JQEError must never escape it."""

    @patch("main.run", side_effect=BrokerConnectionError("boom"))
    def test_catches_jqe_error_and_does_not_raise(self, mock_run: MagicMock) -> None:
        main.main()  # must not raise

    @patch("main.run", side_effect=ValueError("unexpected, non-platform error"))
    def test_non_jqe_error_still_propagates(self, mock_run: MagicMock) -> None:
        with pytest.raises(ValueError):
            main.main()
