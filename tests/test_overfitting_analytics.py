"""Tests for institutional overfitting and multiple-testing analytics."""
import math
import numpy as np
import pytest

from analytics.overfitting import (
    calculate_haircut_sharpe,
    calculate_partition_degradation,
    calculate_return_moments,
    calculate_sharpe_ratio,
    deflated_sharpe_ratio,
    expected_max_sharpe,
)


def test_calculate_return_moments_normal() -> None:
    # Deterministic standard normal sample
    np.random.seed(42)
    sample = np.random.normal(loc=0.01, scale=0.02, size=1000).tolist()
    moments = calculate_return_moments(sample)

    assert moments.sample_size == 1000
    assert abs(moments.mean - 0.01) < 0.005
    assert abs(moments.std - 0.02) < 0.005
    # Skewness should be near 0
    assert abs(moments.skewness) < 0.2
    # Pearson kurtosis for normal is around 3.0
    assert abs(moments.kurtosis - 3.0) < 0.5


def test_calculate_return_moments_insufficient_samples() -> None:
    with pytest.raises(ValueError, match="At least 4 return observations"):
        calculate_return_moments([0.01, 0.02, -0.01])


def test_calculate_return_moments_zero_variance() -> None:
    moments = calculate_return_moments([0.05, 0.05, 0.05, 0.05, 0.05])
    assert moments.std == 0.0
    assert moments.skewness == 0.0
    assert moments.kurtosis == 3.0


def test_calculate_sharpe_ratio() -> None:
    returns = [0.01, 0.02, -0.005, 0.015, 0.01]
    sr = calculate_sharpe_ratio(returns, risk_free_rate=0.0, annualization_factor=252.0)
    assert sr > 0.0

    # Flat returns yield Sharpe of 0.0
    assert calculate_sharpe_ratio([0.01, 0.01, 0.01]) == 0.0
    # Empty or single observation yields 0.0
    assert calculate_sharpe_ratio([0.01]) == 0.0


def test_expected_max_sharpe_properties() -> None:
    # 1 trial should have expected max Sharpe = 0.0
    assert expected_max_sharpe(n_trials=1, variance_sharpe=0.5) == 0.0
    # 0 variance should yield 0.0
    assert expected_max_sharpe(n_trials=50, variance_sharpe=0.0) == 0.0

    # Increasing trials increases expected maximum Sharpe under the null
    sr_star_10 = expected_max_sharpe(n_trials=10, variance_sharpe=0.25)
    sr_star_100 = expected_max_sharpe(n_trials=100, variance_sharpe=0.25)
    sr_star_1000 = expected_max_sharpe(n_trials=1000, variance_sharpe=0.25)

    assert 0.0 < sr_star_10 < sr_star_100 < sr_star_1000


def test_deflated_sharpe_ratio_behavior() -> None:
    # Case 1: Exceptionally high Sharpe with modest trials -> High DSR (statistically significant)
    dsr_high = deflated_sharpe_ratio(
        estimated_sharpe=2.5,
        n_trials=10,
        variance_sharpe=0.2,
        sample_length=500,
        skewness=0.0,
        kurtosis=3.0,
    )
    assert dsr_high >= 0.95

    # Case 2: Mediocre Sharpe discovered after massive search (N=10,000) -> Low DSR (overfit / snooped)
    dsr_overfit = deflated_sharpe_ratio(
        estimated_sharpe=1.1,
        n_trials=10000,
        variance_sharpe=0.5,
        sample_length=250,
        skewness=0.0,
        kurtosis=3.0,
    )
    assert dsr_overfit < 0.20

    # Case 3: Negative skewness increases hurdle (reduces DSR)
    dsr_normal = deflated_sharpe_ratio(
        estimated_sharpe=1.5,
        n_trials=20,
        variance_sharpe=0.2,
        sample_length=250,
        skewness=0.0,
        kurtosis=3.0,
    )
    dsr_neg_skew = deflated_sharpe_ratio(
        estimated_sharpe=1.5,
        n_trials=20,
        variance_sharpe=0.2,
        sample_length=250,
        skewness=-1.5,
        kurtosis=6.0,
    )
    assert dsr_neg_skew < dsr_normal


def test_haircut_sharpe_ratio() -> None:
    raw_sr = 2.0
    haircut_1 = calculate_haircut_sharpe(raw_sr, n_trials=1)
    assert haircut_1 == raw_sr

    haircut_10 = calculate_haircut_sharpe(raw_sr, n_trials=10)
    haircut_100 = calculate_haircut_sharpe(raw_sr, n_trials=100)

    assert 0.0 < haircut_100 < haircut_10 < raw_sr


def test_calculate_partition_degradation_healthy() -> None:
    train_m = {
        "Net P&L": 10.0,
        "Total Trades": 20,
        "Win Rate %": 60.0,
        "Profit Factor": 1.8,
        "Maximum Drawdown": 2.0,
    }
    oos_m = {
        "Net P&L": 3.0,
        "Total Trades": 7,
        "Win Rate %": 57.0,
        "Profit Factor": 1.6,
        "Maximum Drawdown": 2.2,
    }
    deg = calculate_partition_degradation(train_m, oos_m)

    assert deg["train_pnl"] == 10.0
    assert deg["oos_pnl"] == 3.0
    assert deg["pnl_degradation_ratio"] == 0.3
    assert deg["win_rate_decay"] == 3.0
    assert not deg["is_overfit_suspect"]
    assert len(deg["warning_reasons"]) == 0


def test_calculate_partition_degradation_profit_reversal() -> None:
    train_m = {
        "Net P&L": 5.0,
        "Total Trades": 10,
        "Win Rate %": 60.0,
        "Profit Factor": 2.0,
        "Maximum Drawdown": 1.0,
    }
    oos_m = {
        "Net P&L": -2.5,
        "Total Trades": 4,
        "Win Rate %": 25.0,
        "Profit Factor": 0.3,
        "Maximum Drawdown": 3.0,
    }
    deg = calculate_partition_degradation(train_m, oos_m)

    assert deg["is_overfit_suspect"]
    assert any("PROFIT_REVERSAL" in r for r in deg["warning_reasons"])
    assert any("WIN_RATE_COLLAPSE" in r for r in deg["warning_reasons"])
    assert any("DRAWDOWN_EXPANSION" in r for r in deg["warning_reasons"])
