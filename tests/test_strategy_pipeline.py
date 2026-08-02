"""Tests for strategy.pipeline.generate_trading_signal.

Verifies the adapter logic (column aliasing, regime mapping, action->
signal translation) using small, hand-built DataFrames — not real
market data — so behavior is deterministic and each branch is
independently verifiable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategy.pipeline import generate_trading_signal


def _make_indicator_df(
    n: int = 30,
    close: float = 100.0,
    ema50: float = 100.0,
    ema200: float = 90.0,
    rsi: float = 65.0,
    atr: float = 2.0,
) -> pd.DataFrame:
    """Builds a minimal calculate_indicators()-shaped DataFrame.

    All rows carry the same indicator values (only the latest row
    matters to FeatureEngine/detect_regime), which is enough to drive
    generate_trading_signal deterministically without needing real
    price history.
    """
    return pd.DataFrame(
        {
            "close": np.full(n, close),
            "high": np.full(n, close + 1.0),
            "low": np.full(n, close - 1.0),
            "EMA50": np.full(n, ema50),
            "EMA200": np.full(n, ema200),
            "RSI": np.full(n, rsi),
            "ATR": np.full(n, atr),
        }
    )


class TestGenerateTradingSignal:
    def test_raises_key_error_without_atr_column(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0]})
        with pytest.raises(KeyError):
            generate_trading_signal(df)

    def test_bullish_trend_strong_momentum_produces_buy(self) -> None:
        # close > EMA50 > EMA200 and RSI > 50 -> TREND_UP -> TRENDING;
        # EMA50 > EMA200 -> BULLISH; RSI > 60 -> STRONG momentum.
        df = _make_indicator_df(close=105.0, ema50=100.0, ema200=90.0, rsi=65.0)
        signal = generate_trading_signal(df, "TEST")
        assert signal["signal"] == "BUY"
        assert signal["intelligence"]["regime"] == "TRENDING"
        assert signal["intelligence"]["trend"] == "BULLISH"

    def test_bearish_trend_strong_momentum_produces_sell(self) -> None:
        # close < EMA50 < EMA200 and RSI < 50 -> TREND_DOWN -> TRENDING;
        # EMA50 < EMA200 -> BEARISH.
        df = _make_indicator_df(close=75.0, ema50=80.0, ema200=90.0, rsi=30.0)
        signal = generate_trading_signal(df, "TEST")
        assert signal["intelligence"]["trend"] == "BEARISH"
        assert signal["intelligence"]["regime"] == "TRENDING"

    def test_neutral_momentum_produces_no_trade(self) -> None:
        # RSI in [40, 60] -> NEUTRAL momentum -> SignalEngine's
        # trend-confirmed branches require STRONG, so this falls
        # through to WAIT/NO_TRADE regardless of trend direction.
        df = _make_indicator_df(ema50=100.0, ema200=90.0, rsi=50.0)
        signal = generate_trading_signal(df, "TEST")
        assert signal["signal"] == "NO_TRADE"

    def test_ranging_market_produces_no_trade(self) -> None:
        # abs(EMA50 - EMA200) < ATR * 0.5 -> RANGE -> RANGING -> WAIT.
        df = _make_indicator_df(ema50=100.0, ema200=100.5, rsi=65.0, atr=5.0)
        signal = generate_trading_signal(df, "TEST")
        assert signal["signal"] == "NO_TRADE"
        assert signal["intelligence"]["regime"] == "RANGING"

    def test_explicit_regime_overrides_detection(self) -> None:
        df = _make_indicator_df(ema50=100.0, ema200=90.0, rsi=65.0)
        # Force RANGING despite indicator values that would normally
        # detect TREND_UP, to verify the pre-computed `regime` param
        # is actually used instead of recomputing.
        signal = generate_trading_signal(df, "TEST", regime="RANGE")
        assert signal["intelligence"]["regime"] == "RANGING"
        assert signal["signal"] == "NO_TRADE"

    def test_result_contains_all_expected_keys(self) -> None:
        df = _make_indicator_df()
        signal = generate_trading_signal(df, "TEST")
        assert set(signal.keys()) == {
            "signal",
            "confidence",
            "quality",
            "score",
            "reasons",
            "intelligence",
        }

    def test_signal_is_always_risk_engine_compatible(self) -> None:
        # signal must always be one of the three values approve_trade/
        # simulate_trade recognize, never SignalEngine's raw "WAIT".
        for ema50, ema200, rsi in [(100, 90, 65), (80, 90, 30), (100, 100.5, 65)]:
            df = _make_indicator_df(ema50=ema50, ema200=ema200, rsi=rsi)
            signal = generate_trading_signal(df, "TEST")
            assert signal["signal"] in ("BUY", "SELL", "NO_TRADE")
