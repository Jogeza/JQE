"""Tests for intelligence.market_state.MarketState.

Named to avoid colliding with the pre-existing, unrelated
tests/test_market_regime.py (a manual debug script referencing a
never-built data.historical_data/strategy.features design — see
docs/roadmap.md, "Known test debt").
"""

from __future__ import annotations

from intelligence.market_state import MarketState


class TestMarketState:
    def test_returns_none_for_none_input(self) -> None:
        assert MarketState().analyze(None) is None

    def test_missing_sub_analyses_default_to_unknown(self) -> None:
        result = MarketState().analyze({"symbol": "GOLD", "price": 2000, "spread": 1})
        assert result["trend"] == "UNKNOWN"
        assert result["volatility"] == "UNKNOWN"
        assert result["momentum"] == "UNKNOWN"

    def test_full_bullish_snapshot_is_trade_ready(self) -> None:
        market = {
            "symbol": "GOLD",
            "price": 2000,
            "spread": 1.0,
            "trend_analysis": {"trend": "BULLISH"},
            "volatility_analysis": {"volatility": "HIGH", "atr": 25},
            "momentum_analysis": {"momentum": "STRONG", "rsi": 65},
        }
        result = MarketState().analyze(market)
        assert result["liquidity"] == "GOOD"
        assert result["market_score"] == 100
        assert result["trade_ready"] is True

    def test_weak_snapshot_is_not_trade_ready(self) -> None:
        market = {
            "symbol": "GOLD",
            "price": 2000,
            "spread": 999,
            "trend_analysis": {"trend": "SIDEWAYS"},
            "volatility_analysis": {"volatility": "LOW", "atr": 1},
            "momentum_analysis": {"momentum": "WEAK", "rsi": 30},
        }
        result = MarketState().analyze(market)
        assert result["liquidity"] == "LOW"
        assert result["trade_ready"] is False

    def test_medium_spread_reaches_market_score_medium_liquidity_branch(self) -> None:
        # Regression guard: MarketScore's "MEDIUM" liquidity branch was
        # unreachable before LiquidityEngine added a middle tier (see
        # intelligence/liquidity_engine.py's docstring). A spread that
        # lands in LiquidityEngine's MEDIUM band must actually score 10
        # liquidity points, not 0 or 20.
        market = {
            "symbol": "GOLD",
            "price": 2000,
            "spread": 5.0,
            "trend_analysis": {"trend": "SIDEWAYS"},
            "volatility_analysis": {"volatility": "UNKNOWN"},
            "momentum_analysis": {"momentum": "UNKNOWN"},
        }
        result = MarketState().analyze(market)
        assert result["liquidity"] == "MEDIUM"
        assert result["market_score"] == 10  # only the liquidity component fires

    def test_passes_through_price_atr_rsi(self) -> None:
        market = {
            "symbol": "GOLD",
            "price": 2050.5,
            "spread": 1,
            "volatility_analysis": {"volatility": "MEDIUM", "atr": 12.3},
            "momentum_analysis": {"momentum": "MODERATE", "rsi": 55.2},
        }
        result = MarketState().analyze(market)
        assert result["price"] == 2050.5
        assert result["atr"] == 12.3
        assert result["rsi"] == 55.2
