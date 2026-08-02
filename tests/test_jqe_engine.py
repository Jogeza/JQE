"""Tests for core.engine.JQEEngine — the scanning/decisioning composition root.

Note: this file is intentionally named differently from the pre-existing
``tests/test_core_engine.py`` (a manual, non-pytest debug script with a
broken import chain — see docs/roadmap.md, Milestone 4) to avoid
colliding with it while that file is still pending cleanup.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.engine import JQEEngine


class TestJQEEngineConstruction:
    def test_creates_portfolio_and_pipeline(self) -> None:
        engine = JQEEngine()
        assert engine.portfolio is not None
        assert engine.pipeline is not None

    def test_start_does_not_raise(self) -> None:
        JQEEngine().start()  # should log, not print, and not raise


class TestJQEEngineDelegation:
    @patch("core.engine.MarketScanner")
    def test_scan_markets_delegates_to_market_scanner(self, mock_scanner_cls: MagicMock) -> None:
        mock_scanner = mock_scanner_cls.return_value
        mock_scanner.scan.return_value = {"XAUUSD": "bullish"}

        engine = JQEEngine()
        result = engine.scan_markets(["XAUUSD"])

        mock_scanner_cls.assert_called_once_with(["XAUUSD"])
        mock_scanner.scan.assert_called_once()
        assert result == {"XAUUSD": "bullish"}

    def test_evaluate_trade_delegates_to_pipeline(self) -> None:
        engine = JQEEngine()
        engine.pipeline = MagicMock()
        engine.pipeline.decide.return_value = {"approved": True}

        result = engine.evaluate_trade("signal", "score", "risk")

        engine.pipeline.decide.assert_called_once_with("signal", "score", "risk")
        assert result == {"approved": True}
