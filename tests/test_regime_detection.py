"""Tests for intelligence.market_regime.detect_regime.

Named tests/test_regime_detection.py — not tests/test_market_regime.py
— to avoid colliding with the pre-existing, unrelated debug script at
that path (see docs/roadmap.md, "Known test debt"). detect_regime is
also already exercised indirectly via tests/test_strategy_pipeline.py;
these tests cover it directly and in isolation.
"""

from __future__ import annotations

import pandas as pd

from intelligence.market_regime import detect_regime


def _df(close: float, ema50: float, ema200: float, rsi: float, atr: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"close": [close], "EMA50": [ema50], "EMA200": [ema200], "RSI": [rsi], "ATR": [atr]}
    )


class TestDetectRegime:
    def test_bullish_alignment_is_trend_up(self) -> None:
        df = _df(close=105, ema50=100, ema200=90, rsi=60, atr=2)
        assert detect_regime(df) == "TREND_UP"

    def test_bearish_alignment_is_trend_down(self) -> None:
        df = _df(close=75, ema50=80, ema200=90, rsi=40, atr=2)
        assert detect_regime(df) == "TREND_DOWN"

    def test_tight_ema_spread_is_range(self) -> None:
        df = _df(close=100, ema50=100, ema200=100.5, rsi=50, atr=5)
        assert detect_regime(df) == "RANGE"

    def test_ambiguous_conditions_default_to_no_trade(self) -> None:
        # Bullish price/EMA alignment but RSI doesn't confirm (<=50),
        # and the EMA spread is too wide to be a RANGE either.
        df = _df(close=105, ema50=100, ema200=90, rsi=45, atr=1)
        assert detect_regime(df) == "NO_TRADE"

    def test_only_examines_the_latest_row(self) -> None:
        df = pd.concat(
            [
                _df(close=75, ema50=80, ema200=90, rsi=40, atr=2),  # would be TREND_DOWN
                _df(close=105, ema50=100, ema200=90, rsi=60, atr=2),  # latest: TREND_UP
            ],
            ignore_index=True,
        )
        assert detect_regime(df) == "TREND_UP"
