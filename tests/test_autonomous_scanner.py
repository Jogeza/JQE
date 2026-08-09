"""Tests for core.market_scanner.MarketScanner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.market_scanner import MarketScanner


class TestAutonomousScanner:
    @patch("core.market_scanner.MarketData")
    def test_autonomous_scanner(self, mock_market_data_cls: MagicMock) -> None:
        """Tests that the scanner builds a snapshot for each symbol."""
        # Setup mock
        mock_data_engine = mock_market_data_cls.return_value
        
        # When get_market_data is called, return a basic dict
        mock_data_engine.get_market_data.return_value = {
            "symbol": "GOLD",
            "price": 2000.0,
            "bid": 1999.5,
            "ask": 2000.5,
            "spread": 100,
        }
        
        # When get_candles is called, return an empty list (engines handle this)
        mock_data_engine.get_candles.return_value = []

        scanner = MarketScanner(["GOLD"])
        markets = scanner.autonomous_scan()

        assert len(markets) == 1
        assert markets[0]["symbol"] == "GOLD"
        assert "market_score" in markets[0]
        assert "trade_ready" in markets[0]

    @patch("core.market_scanner.MarketData")
    def test_autonomous_scan_handles_missing_data(self, mock_market_data_cls: MagicMock) -> None:
        """Tests that a missing symbol gracefully returns an UNKNOWN state rather than skipping."""
        mock_data_engine = mock_market_data_cls.return_value
        mock_data_engine.get_market_data.return_value = None

        scanner = MarketScanner(["MISSING"])
        markets = scanner.autonomous_scan()

        assert len(markets) == 1
        assert markets[0]["symbol"] == "MISSING"
        assert markets[0]["trend"] == "UNKNOWN"
        assert markets[0]["trade_ready"] is False