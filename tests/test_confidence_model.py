"""Tests for intelligence.confidence_model."""

from __future__ import annotations

import pytest

from intelligence.confidence_model import (
    LIQUIDITY_WEIGHT,
    MOMENTUM_WEIGHT,
    RISK_WEIGHT,
    STRUCTURE_WEIGHT,
    TOTAL_WEIGHT,
    TREND_WEIGHT,
    VOLATILITY_WEIGHT,
    ConfidenceModel,
    classify_risk_conditions,
    classify_structure,
)


class TestWeights:
    def test_weights_sum_to_one_hundred(self) -> None:
        assert TOTAL_WEIGHT == 100
        assert (
            TREND_WEIGHT
            + STRUCTURE_WEIGHT
            + LIQUIDITY_WEIGHT
            + MOMENTUM_WEIGHT
            + VOLATILITY_WEIGHT
            + RISK_WEIGHT
            == 100
        )

    def test_weights_match_the_documented_design(self) -> None:
        # Trend 25 / Structure 20 / Liquidity 20 / Momentum 15 /
        # Volatility 10 / Risk 10 — the platform's documented Quant
        # Intelligence Engine scoring design.
        assert TREND_WEIGHT == 25
        assert STRUCTURE_WEIGHT == 20
        assert LIQUIDITY_WEIGHT == 20
        assert MOMENTUM_WEIGHT == 15
        assert VOLATILITY_WEIGHT == 10
        assert RISK_WEIGHT == 10


class TestConfidenceModelCalculate:
    def test_best_case_scores_full_one_hundred(self) -> None:
        breakdown = ConfidenceModel().calculate(
            trend="BULLISH",
            structure="CONFIRMED",
            liquidity="GOOD",
            momentum="STRONG",
            volatility="MEDIUM",
            risk="FAVORABLE",
        )
        assert breakdown.total == 100
        assert breakdown.meets_threshold(100)

    def test_worst_case_scores_zero(self) -> None:
        breakdown = ConfidenceModel().calculate(
            trend="SIDEWAYS",
            structure="NONE",
            liquidity="LOW",
            momentum="WEAK",
            volatility="UNKNOWN",
            risk="UNFAVORABLE",
        )
        assert breakdown.total == 0
        assert breakdown.meets_threshold(1) is False

    def test_unknown_inputs_score_zero_not_full_weight(self) -> None:
        # Every factor's "unknown"/unrecognized value must score 0 —
        # missing data must never look as good as confirmed data.
        breakdown = ConfidenceModel().calculate(
            trend="UNKNOWN",
            structure="UNKNOWN",
            liquidity="UNKNOWN",
            momentum="UNKNOWN",
            volatility="UNKNOWN",
            risk="UNKNOWN",
        )
        assert breakdown.total == 0

    def test_bearish_trend_scores_the_same_as_bullish(self) -> None:
        bullish = ConfidenceModel().calculate(
            "BULLISH", "NONE", "LOW", "WEAK", "LOW", "UNFAVORABLE"
        )
        bearish = ConfidenceModel().calculate(
            "BEARISH", "NONE", "LOW", "WEAK", "LOW", "UNFAVORABLE"
        )
        assert bullish.trend_score == bearish.trend_score == 25

    def test_partial_factors_score_partial_weight(self) -> None:
        breakdown = ConfidenceModel().calculate(
            trend="UNKNOWN",
            structure="WEAK",
            liquidity="MEDIUM",
            momentum="MODERATE",
            volatility="HIGH",
            risk="MODERATE",
        )
        assert breakdown.structure_score == STRUCTURE_WEIGHT // 2
        assert breakdown.liquidity_score == LIQUIDITY_WEIGHT // 2
        assert breakdown.momentum_score == (MOMENTUM_WEIGHT * 2) // 3
        assert breakdown.volatility_score == (VOLATILITY_WEIGHT * 2) // 3
        assert breakdown.risk_score == RISK_WEIGHT // 2

    def test_total_is_always_the_sum_of_components(self) -> None:
        breakdown = ConfidenceModel().calculate(
            "BULLISH", "WEAK", "MEDIUM", "MODERATE", "HIGH", "MODERATE"
        )
        assert breakdown.total == (
            breakdown.trend_score
            + breakdown.structure_score
            + breakdown.liquidity_score
            + breakdown.momentum_score
            + breakdown.volatility_score
            + breakdown.risk_score
        )

    def test_factors_dict_echoes_raw_inputs(self) -> None:
        breakdown = ConfidenceModel().calculate(
            "BULLISH", "CONFIRMED", "GOOD", "STRONG", "MEDIUM", "FAVORABLE"
        )
        assert breakdown.factors == {
            "trend": "BULLISH",
            "structure": "CONFIRMED",
            "liquidity": "GOOD",
            "momentum": "STRONG",
            "volatility": "MEDIUM",
            "risk": "FAVORABLE",
        }

    @pytest.mark.parametrize(
        "threshold,expected", [(50, True), (70, True), (95, True), (96, False)]
    )
    def test_meets_threshold(self, threshold: int, expected: bool) -> None:
        breakdown = ConfidenceModel().calculate(
            "BULLISH", "CONFIRMED", "GOOD", "STRONG", "MEDIUM", "MODERATE"
        )
        assert breakdown.meets_threshold(threshold) is expected


class TestClassifyStructure:
    def test_not_enough_data_is_unknown(self) -> None:
        assert classify_structure([{"high": 1, "low": 1, "close": 1}] * 5) == "UNKNOWN"

    def test_breakout_above_range_is_confirmed(self) -> None:
        candles = [{"high": 105, "low": 95, "close": 100} for _ in range(20)]
        candles.append({"high": 111, "low": 109, "close": 110})
        assert classify_structure(candles) == "CONFIRMED"

    def test_breakout_below_range_is_confirmed(self) -> None:
        candles = [{"high": 105, "low": 95, "close": 100} for _ in range(20)]
        candles.append({"high": 91, "low": 89, "close": 90})
        assert classify_structure(candles) == "CONFIRMED"

    def test_price_near_range_edge_is_weak(self) -> None:
        candles = [{"high": 110, "low": 90, "close": 100} for _ in range(20)]
        candles.append({"high": 109, "low": 107, "close": 108})  # top quartile, inside range
        assert classify_structure(candles) == "WEAK"

    def test_price_mid_range_is_none(self) -> None:
        candles = [{"high": 110, "low": 90, "close": 100} for _ in range(20)]
        candles.append({"high": 101, "low": 99, "close": 100})
        assert classify_structure(candles) == "NONE"

    def test_zero_width_range_is_unknown(self) -> None:
        candles = [{"high": 100, "low": 100, "close": 100} for _ in range(21)]
        assert classify_structure(candles) == "UNKNOWN"


class TestClassifyRiskConditions:
    def test_missing_data_is_unknown(self) -> None:
        assert classify_risk_conditions(spread=None, atr=1.0, price=100) == "UNKNOWN"
        assert classify_risk_conditions(spread=1.0, atr=None, price=100) == "UNKNOWN"

    def test_zero_atr_is_unknown_not_a_division_error(self) -> None:
        assert classify_risk_conditions(spread=1.0, atr=0, price=100) == "UNKNOWN"

    def test_tight_spread_relative_to_atr_is_favorable(self) -> None:
        assert classify_risk_conditions(spread=1.0, atr=10.0, price=100) == "FAVORABLE"

    def test_moderate_spread_relative_to_atr_is_moderate(self) -> None:
        assert classify_risk_conditions(spread=2.5, atr=10.0, price=100) == "MODERATE"

    def test_wide_spread_relative_to_atr_is_unfavorable(self) -> None:
        assert classify_risk_conditions(spread=8.0, atr=10.0, price=100) == "UNFAVORABLE"
