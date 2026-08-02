"""Tests for execution.simulator — forward-only trade simulation."""

from __future__ import annotations

import pandas as pd
import pytest

from execution.simulator import calculate_stop_target, simulate_trade


class TestCalculateStopTarget:
    def test_buy_stop_is_below_entry_target_is_above(self) -> None:
        stop, target = calculate_stop_target(entry=100.0, atr=2.0, direction="BUY")
        assert stop < 100.0
        assert target > 100.0

    def test_sell_stop_is_above_entry_target_is_below(self) -> None:
        stop, target = calculate_stop_target(entry=100.0, atr=2.0, direction="SELL")
        assert stop > 100.0
        assert target < 100.0

    def test_uses_documented_atr_multiples(self) -> None:
        stop, target = calculate_stop_target(entry=100.0, atr=2.0, direction="BUY")
        assert stop == pytest.approx(100.0 - 2.0 * 1.5)
        assert target == pytest.approx(100.0 + 2.0 * 3.0)


def _price_path(closes: list[float], atr: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "close": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "ATR": [atr] * len(closes),
        }
    )


class TestSimulateTrade:
    def test_returns_none_for_non_buy_sell_signal(self) -> None:
        df = _price_path([100.0] * 25)
        assert simulate_trade({"signal": "NO_TRADE"}, 0, df) is None

    def test_returns_none_for_non_positive_atr(self) -> None:
        df = _price_path([100.0] * 25, atr=0)
        assert simulate_trade({"signal": "BUY"}, 0, df) is None

    def test_buy_hits_target_returns_win(self) -> None:
        # entry=100, atr=1 -> stop=98.5, target=103. Ramp the high
        # price up past the target on the very next candle.
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "high"] = 110.0
        result = simulate_trade({"signal": "BUY"}, 0, df)
        assert result == {"profit": 3, "result": "WIN"}

    def test_buy_hits_stop_returns_loss(self) -> None:
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "low"] = 90.0
        result = simulate_trade({"signal": "BUY"}, 0, df)
        assert result == {"profit": -1, "result": "LOSS"}

    def test_sell_hits_target_returns_win(self) -> None:
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "low"] = 90.0  # below target (100 - 3) for a SELL
        result = simulate_trade({"signal": "SELL"}, 0, df)
        assert result == {"profit": 3, "result": "WIN"}

    def test_sell_hits_stop_returns_loss(self) -> None:
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[1, "high"] = 110.0  # above stop (100 + 1.5) for a SELL
        result = simulate_trade({"signal": "SELL"}, 0, df)
        assert result == {"profit": -1, "result": "LOSS"}

    def test_no_stop_or_target_hit_returns_timeout(self) -> None:
        df = _price_path([100.0] * 25, atr=1.0)
        result = simulate_trade({"signal": "BUY"}, 0, df)
        assert result == {"profit": 0, "result": "TIMEOUT"}

    def test_never_looks_further_back_than_current_index(self) -> None:
        # A stop/target-triggering candle placed *before* current_index
        # must never affect the outcome (no look-ahead bias, backwards).
        closes = [100.0] * 25
        df = _price_path(closes, atr=1.0)
        df.loc[0, "low"] = 0.0  # would trigger LOSS if (wrongly) considered
        result = simulate_trade({"signal": "BUY"}, 5, df)
        assert result == {"profit": 0, "result": "TIMEOUT"}
