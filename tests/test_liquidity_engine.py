"""Tests for intelligence.liquidity_engine.LiquidityEngine."""

from __future__ import annotations

from intelligence.liquidity_engine import LiquidityEngine


class TestLiquidityEngine:
    def test_tight_spread_is_good(self) -> None:
        result = LiquidityEngine().analyze(1.5)
        assert result == {"liquidity": "GOOD", "spread": 1.5}

    def test_moderate_spread_is_medium(self) -> None:
        result = LiquidityEngine().analyze(5.0)
        assert result["liquidity"] == "MEDIUM"

    def test_wide_spread_is_low(self) -> None:
        result = LiquidityEngine().analyze(15.0)
        assert result["liquidity"] == "LOW"

    def test_none_spread_is_unknown_not_favorable(self) -> None:
        result = LiquidityEngine().analyze(None)
        assert result == {"liquidity": "UNKNOWN", "spread": None}

    def test_boundary_just_below_good_threshold(self) -> None:
        assert LiquidityEngine().analyze(2.99)["liquidity"] == "GOOD"

    def test_boundary_at_good_threshold_is_medium(self) -> None:
        assert LiquidityEngine().analyze(3.0)["liquidity"] == "MEDIUM"

    def test_boundary_at_medium_threshold_is_low(self) -> None:
        assert LiquidityEngine().analyze(8.0)["liquidity"] == "LOW"
