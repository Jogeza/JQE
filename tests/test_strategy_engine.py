"""Tests for strategy.strategy_engine (Canonical Strategy Engine)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategy.strategy_engine import (
    RegimeTranslator,
    StrategyDecision,
    StrategyEngine,
)


def _make_df(
    n: int = 30,
    close: float = 100.0,
    ema50: float = 100.0,
    ema200: float = 90.0,
    rsi: float = 65.0,
    atr: float = 2.0,
    spread: float = 1.0,
) -> pd.DataFrame:
    """Builds a test OHLC DataFrame with indicator columns."""
    return pd.DataFrame(
        {
            "close": np.full(n, close),
            "high": np.full(n, close + 1.0),
            "low": np.full(n, close - 1.0),
            "EMA50": np.full(n, ema50),
            "EMA200": np.full(n, ema200),
            "RSI": np.full(n, rsi),
            "ATR": np.full(n, atr),
            "spread": np.full(n, spread),
        }
    )


class TestRegimeTranslator:
    def test_translates_legacy_up_down_range(self) -> None:
        assert RegimeTranslator.to_canonical("TREND_UP") == "TRENDING"
        assert RegimeTranslator.to_canonical("TREND_DOWN") == "TRENDING"
        assert RegimeTranslator.to_canonical("RANGE") == "RANGING"
        assert RegimeTranslator.to_canonical("SIDEWAYS") == "RANGING"

    def test_preserves_canonical_names(self) -> None:
        assert RegimeTranslator.to_canonical("TRENDING") == "TRENDING"
        assert RegimeTranslator.to_canonical("RANGING") == "RANGING"
        assert RegimeTranslator.to_canonical("HIGH_VOLATILITY") == "HIGH_VOLATILITY"

    def test_handles_unknown_or_none(self) -> None:
        assert RegimeTranslator.to_canonical(None) == "UNKNOWN"
        assert RegimeTranslator.to_canonical("NO_TRADE") == "UNKNOWN"
        assert RegimeTranslator.to_canonical("SOMETHING_ELSE") == "UNKNOWN"

    def test_case_insensitive(self) -> None:
        assert RegimeTranslator.to_canonical("trend_up") == "TRENDING"
        assert RegimeTranslator.to_canonical("ranging") == "RANGING"


class TestStrategyDecision:
    def test_to_pipeline_dict_exact_keys(self) -> None:
        decision = StrategyDecision(
            symbol="BTCUSD",
            signal="BUY",
            confidence=80,
            quality="HIGH",
            score=85,
            reasons=["Strong trend"],
            intelligence={"trend": "BULLISH"},
        )
        d = decision.to_pipeline_dict()
        assert set(d.keys()) == {
            "signal",
            "confidence",
            "quality",
            "score",
            "reasons",
            "intelligence",
        }
        assert d["signal"] == "BUY"
        assert d["confidence"] == 80


class TestStrategyEngine:
    def test_raises_key_error_without_atr(self) -> None:
        engine = StrategyEngine()
        df = pd.DataFrame({"close": [100.0, 101.0]})
        with pytest.raises(KeyError, match="missing ATR column"):
            engine.evaluate(df)

    def test_bullish_trend_strong_momentum_produces_buy(self) -> None:
        engine = StrategyEngine()
        df = _make_df(close=105.0, ema50=100.0, ema200=90.0, rsi=65.0, atr=2.0)
        decision = engine.evaluate(df, symbol="EURUSD")

        assert decision.signal == "BUY"
        assert decision.intelligence["trend"] == "BULLISH"
        assert decision.intelligence["momentum"] == "STRONG"
        assert decision.intelligence["regime"] == "TRENDING"
        assert decision.confidence_breakdown is not None
        assert decision.confidence_breakdown.total > 0
        assert decision.trade_plan is not None
        assert decision.trade_plan.is_valid()
        assert decision.trade_plan.signal == "BUY"
        assert decision.trade_plan.stop_loss < decision.trade_plan.entry < decision.trade_plan.take_profit

    def test_bearish_trend_strong_momentum_produces_sell(self) -> None:
        engine = StrategyEngine()
        # EMA50 < EMA200 -> BEARISH, RSI > 60 -> STRONG momentum, regime=TRENDING -> SELL
        df = _make_df(close=75.0, ema50=80.0, ema200=90.0, rsi=65.0, atr=2.0)
        decision = engine.evaluate(df, symbol="GBPUSD", regime="TRENDING")

        assert decision.signal == "SELL"
        assert decision.intelligence["trend"] == "BEARISH"
        assert decision.intelligence["regime"] == "TRENDING"
        assert decision.trade_plan is not None
        assert decision.trade_plan.is_valid()
        assert decision.trade_plan.signal == "SELL"
        assert decision.trade_plan.take_profit < decision.trade_plan.entry < decision.trade_plan.stop_loss

    def test_neutral_momentum_produces_no_trade(self) -> None:
        engine = StrategyEngine()
        df = _make_df(ema50=100.0, ema200=90.0, rsi=50.0)
        decision = engine.evaluate(df, symbol="USDJPY")

        assert decision.signal == "NO_TRADE"
        assert decision.trade_plan is not None
        assert decision.trade_plan.signal == "NO_TRADE"
        assert not decision.trade_plan.is_valid()

    def test_ranging_regime_produces_no_trade(self) -> None:
        engine = StrategyEngine()
        df = _make_df(ema50=100.0, ema200=100.5, rsi=65.0, atr=5.0)
        decision = engine.evaluate(df, symbol="AUDUSD")

        assert decision.signal == "NO_TRADE"
        assert decision.intelligence["regime"] == "RANGING"

    def test_high_volatility_regime_protection(self) -> None:
        engine = StrategyEngine()
        df = _make_df(close=105.0, ema50=100.0, ema200=90.0, rsi=65.0)
        # Pass explicit HIGH_VOLATILITY regime
        decision = engine.evaluate(df, symbol="XAUUSD", regime="HIGH_VOLATILITY")

        assert decision.signal == "NO_TRADE"
        assert decision.intelligence["regime"] == "HIGH_VOLATILITY"

    def test_confidence_model_breakdown_included(self) -> None:
        engine = StrategyEngine()
        df = _make_df(close=105.0, ema50=100.0, ema200=90.0, rsi=65.0, atr=2.0, spread=1.0)
        decision = engine.evaluate(df, symbol="EURUSD")

        assert "confidence_breakdown" in decision.intelligence
        assert "institutional_confidence" in decision.intelligence
        cb = decision.confidence_breakdown
        assert cb is not None
        assert cb.trend_score == 25  # BULLISH
        assert cb.liquidity_score == 20  # GOOD (spread=1.0)
        assert cb.momentum_score == 15  # STRONG (RSI=65)

    def test_price_and_spread_override(self) -> None:
        engine = StrategyEngine()
        df = _make_df(close=105.0, ema50=100.0, ema200=90.0, rsi=65.0, atr=2.0)
        decision = engine.evaluate(df, symbol="EURUSD", price=110.0, spread=5.0)

        assert decision.intelligence["spread"] == 5.0
        assert decision.intelligence["liquidity"] == "MEDIUM"
        assert decision.trade_plan is not None
        assert decision.trade_plan.entry == 110.0
