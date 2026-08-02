"""Tests for backtesting.engine.BacktestEngine."""

from __future__ import annotations

import pandas as pd

from backtesting.engine import BacktestEngine


def _price_path(closes: list[float], atr: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "ATR": [atr] * len(closes),
            "spread": [5.0] * len(closes),
        }
    )


class TestExecuteTrade:
    def test_no_trade_signal_returns_none_without_calling_risk(self) -> None:
        engine = BacktestEngine(starting_balance=1000)
        df = _price_path([100.0] * 25)
        result = engine.execute_trade({"signal": "NO_TRADE"}, 0, df)
        assert result is None
        assert engine.total_trades == 0

    def test_low_confidence_signal_is_risk_rejected(self) -> None:
        engine = BacktestEngine(starting_balance=1000)
        df = _price_path([100.0] * 25)
        result = engine.execute_trade({"signal": "BUY", "confidence": 10}, 0, df)
        assert result is None
        assert engine.total_trades == 0

    def test_approved_winning_trade_updates_balance_and_stats(self) -> None:
        engine = BacktestEngine(starting_balance=1000)
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "high"] = 110.0  # triggers a WIN for a BUY at index 0
        result = engine.execute_trade({"signal": "BUY", "confidence": 90}, 0, df)
        assert result == {"profit": 3, "result": "WIN"}
        assert engine.balance == 1003
        assert engine.total_trades == 1
        assert engine.wins == 1
        assert engine.losses == 0
        assert len(engine.trades) == 1
        assert engine.equity_curve[-1] == 1003

    def test_approved_losing_trade_updates_balance_and_stats(self) -> None:
        engine = BacktestEngine(starting_balance=1000)
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "low"] = 90.0  # triggers a LOSS for a BUY at index 0
        result = engine.execute_trade({"signal": "BUY", "confidence": 90}, 0, df)
        assert result == {"profit": -1, "result": "LOSS"}
        assert engine.balance == 999
        assert engine.wins == 0
        assert engine.losses == 1

    def test_risk_engine_only_sees_data_up_to_current_index(self) -> None:
        # A spread spike *after* current_index must not affect the risk
        # decision at current_index (approve_trade only sees history).
        engine = BacktestEngine(starting_balance=1000)
        df = _price_path([100.0] * 25, atr=1.0)
        df.loc[5, "spread"] = 999  # would reject if (wrongly) visible at index 0
        result = engine.execute_trade({"signal": "BUY", "confidence": 90}, 0, df)
        assert result is not None  # approved despite the future spike

    def test_trade_record_includes_lot_size(self) -> None:
        engine = BacktestEngine(starting_balance=1000)
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        engine.execute_trade({"signal": "BUY", "confidence": 90}, 0, df)
        assert engine.trades[0]["lot_size"] > 0


class TestStatistics:
    def test_statistics_with_no_trades(self) -> None:
        engine = BacktestEngine(starting_balance=500)
        stats = engine.statistics()
        assert stats == {
            "Starting Balance": 500,
            "Ending Balance": 500,
            "Net Profit": 0,
            "Trades": 0,
            "Wins": 0,
            "Losses": 0,
        }

    def test_statistics_reflect_executed_trades(self) -> None:
        engine = BacktestEngine(starting_balance=1000)
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "high"] = 110.0
        engine.execute_trade({"signal": "BUY", "confidence": 90}, 0, df)
        stats = engine.statistics()
        assert stats["Trades"] == 1
        assert stats["Wins"] == 1
        assert stats["Net Profit"] == 3
