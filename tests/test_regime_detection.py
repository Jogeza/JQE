"""Tests for intelligence.market_regime.detect_regime."""

from __future__ import annotations

import pandas as pd

from intelligence.market_regime import detect_legacy_regime, detect_regime


def _df(close: float, ema50: float, ema200: float, rsi: float, atr: float, avg_atr: float = None) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "close": [close] * 15,
            "EMA50": [ema50] * 15,
            "EMA200": [ema200] * 15,
            "RSI": [rsi] * 15,
            "ATR": [avg_atr if avg_atr is not None else atr] * 14 + [atr]
        }
    )
    return df


class TestDetectRegimeCanonical:
    def test_bullish_alignment_is_trending(self) -> None:
        df = _df(close=105, ema50=100, ema200=90, rsi=60, atr=2)
        assert detect_regime(df) == "TRENDING"

    def test_bearish_alignment_is_trending(self) -> None:
        df = _df(close=75, ema50=80, ema200=90, rsi=40, atr=2)
        assert detect_regime(df) == "TRENDING"

    def test_tight_ema_spread_is_ranging(self) -> None:
        df = _df(close=100, ema50=100, ema200=100.5, rsi=50, atr=5)
        assert detect_regime(df) == "RANGING"

    def test_ambiguous_conditions_default_to_unknown(self) -> None:
        df = _df(close=105, ema50=100, ema200=90, rsi=45, atr=1)
        assert detect_regime(df) == "UNKNOWN"

    def test_high_volatility(self) -> None:
        df = _df(close=105, ema50=100, ema200=90, rsi=60, atr=10, avg_atr=2)
        assert detect_regime(df) == "HIGH_VOLATILITY"


class TestDetectRegimeLegacy:
    def test_bullish_alignment_is_trend_up(self) -> None:
        df = _df(close=105, ema50=100, ema200=90, rsi=60, atr=2)
        assert detect_legacy_regime(df) == "TREND_UP"

    def test_bearish_alignment_is_trend_down(self) -> None:
        df = _df(close=75, ema50=80, ema200=90, rsi=40, atr=2)
        assert detect_legacy_regime(df) == "TREND_DOWN"

    def test_tight_ema_spread_is_range(self) -> None:
        df = _df(close=100, ema50=100, ema200=100.5, rsi=50, atr=5)
        assert detect_legacy_regime(df) == "RANGE"

    def test_ambiguous_conditions_default_to_no_trade(self) -> None:
        df = _df(close=105, ema50=100, ema200=90, rsi=45, atr=1)
        assert detect_legacy_regime(df) == "NO_TRADE"
