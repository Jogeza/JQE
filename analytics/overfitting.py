"""Institutional overfitting and multiple-testing analytics.

Implements the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014),
Haircut Sharpe Ratio (Harvey & Liu, 2014), and Train-to-Out-of-Sample
(OOS) performance degradation metrics.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats

EULER_MASCHERONI = 0.5772156649015328606


@dataclass(frozen=True, slots=True)
class ReturnMoments:
    """Statistical moments of a strategy return series."""

    mean: float
    std: float
    skewness: float
    kurtosis: float  # Pearson kurtosis (normal distribution = 3.0)
    sample_size: int


def calculate_return_moments(returns: Sequence[float]) -> ReturnMoments:
    """Calculate the first four statistical moments of a return series.

    Returns Pearson kurtosis where a standard normal distribution has kurtosis = 3.0.
    """
    clean = [float(r) for r in returns if not (math.isnan(r) or math.isinf(r))]
    n = len(clean)
    if n < 4:
        raise ValueError(f"At least 4 return observations required, got {n}")

    arr = np.asarray(clean, dtype=np.float64)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))

    if std <= 1e-12:
        return ReturnMoments(
            mean=mean,
            std=0.0,
            skewness=0.0,
            kurtosis=3.0,
            sample_size=n,
        )

    # scipy.stats.skew with bias=False computes sample skewness
    skew = float(stats.skew(arr, bias=False))
    # scipy.stats.kurtosis computes Fisher excess kurtosis (normal = 0.0) by default;
    # convert to Pearson kurtosis (normal = 3.0) for Bailey-Lopez de Prado formulation
    fisher_kurt = float(stats.kurtosis(arr, fisher=True, bias=False))
    pearson_kurt = fisher_kurt + 3.0

    return ReturnMoments(
        mean=mean,
        std=std,
        skewness=skew,
        kurtosis=max(1.0, pearson_kurt),
        sample_size=n,
    )


def calculate_sharpe_ratio(
    returns: Sequence[float],
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """Calculate the annualized Sharpe Ratio for a return series.

    Parameters
    ----------
    returns : Sequence[float]
        Periodic percentage returns or trade returns.
    risk_free_rate : float, default 0.0
        Per-period risk-free hurdle rate.
    annualization_factor : float, default 252.0
        Annualization multiplier (e.g. 252 for daily, 252*24 for hourly).
    """
    clean = [float(r) for r in returns if not (math.isnan(r) or math.isinf(r))]
    if len(clean) < 2:
        return 0.0

    arr = np.asarray(clean, dtype=np.float64) - risk_free_rate
    std = float(np.std(arr, ddof=1))
    if std <= 1e-12:
        return 0.0

    mean = float(np.mean(arr))
    return float(mean / std * math.sqrt(annualization_factor))


def expected_max_sharpe(
    n_trials: int,
    variance_sharpe: float,
) -> float:
    """Expected maximum Sharpe Ratio under the null hypothesis of multiple testing.

    Approximates E[max_n {SR_n}] using extreme value theory (Bailey & Lopez de Prado 2014):
    E[max] ~ sqrt(V) * ((1 - gamma) * Phi^{-1}(1 - 1/N) + gamma * Phi^{-1}(1 - 1/(N * e)))

    where gamma is the Euler-Mascheroni constant and Phi^{-1} is the probit function.
    """
    if n_trials <= 1:
        return 0.0
    if variance_sharpe <= 0.0:
        return 0.0

    std_trials = math.sqrt(variance_sharpe)
    p1 = 1.0 - (1.0 / n_trials)
    p2 = 1.0 - (1.0 / (n_trials * math.e))

    # Guard against extreme precision clipping
    p1 = min(max(p1, 1e-15), 1.0 - 1e-15)
    p2 = min(max(p2, 1e-15), 1.0 - 1e-15)

    z1 = float(stats.norm.ppf(p1))
    z2 = float(stats.norm.ppf(p2))

    sr_star = std_trials * ((1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2)
    return max(0.0, float(sr_star))


def deflated_sharpe_ratio(
    estimated_sharpe: float,
    n_trials: int,
    variance_sharpe: float,
    sample_length: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Calculate the Deflated Sharpe Ratio (DSR).

    Accounts for:
    1. Number of strategy / parameter trials (N)
    2. Variance of Sharpe ratios across trials (V)
    3. Non-normality (skewness and kurtosis)
    4. Sample length (T)

    Returns a probability value in [0.0, 1.0]. A value >= 0.95 indicates
    statistical significance at the 5% level after multiple-testing correction.
    """
    if sample_length <= 1:
        return 0.0

    sr_star = expected_max_sharpe(n_trials, variance_sharpe)

    # Asymptotic variance of Sharpe ratio under non-normality (Mertens 2002)
    # sigma^2 = (1 - skew * SR + (kurt - 1) / 4 * SR^2) / (T - 1)
    # Ensure variance inside square root is strictly positive
    numerator = 1.0 - (skewness * estimated_sharpe) + ((kurtosis - 1.0) / 4.0 * (estimated_sharpe**2))
    if numerator <= 0.0:
        numerator = 1e-6

    var_sr = numerator / (sample_length - 1)
    std_sr = math.sqrt(var_sr)

    if std_sr <= 1e-12:
        return 1.0 if estimated_sharpe > sr_star else 0.0

    z_score = (estimated_sharpe - sr_star) / std_sr
    dsr = float(stats.norm.cdf(z_score))
    return float(min(max(dsr, 0.0), 1.0))


def calculate_haircut_sharpe(
    estimated_sharpe: float,
    n_trials: int,
    correlation: float = 0.5,
) -> float:
    """Haircut Sharpe Ratio adjusting for multiple testing (Harvey & Liu, 2014).

    Applies a progressive discount based on trial volume and cross-trial correlation.
    """
    if n_trials <= 1 or estimated_sharpe <= 0.0:
        return max(0.0, estimated_sharpe)

    # Effective independent tests N_eff = 1 + (N - 1) * (1 - correlation)
    eff_n = 1.0 + (n_trials - 1) * max(0.0, min(1.0 - correlation, 1.0))
    # Haircut discount factor roughly scales with sqrt(ln(N_eff))
    discount = 1.0 - (1.0 / math.sqrt(1.0 + 0.5 * math.log(eff_n)))
    haircut_sr = estimated_sharpe * (1.0 - discount)
    return max(0.0, float(haircut_sr))


haircut_sharpe_ratio = calculate_haircut_sharpe


def calculate_partition_degradation(
    train_metrics: Mapping[str, Any],
    oos_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """Calculate In-Sample (Train) vs Out-of-Sample (OOS) degradation metrics.

    Evaluates whether strategy performance decays significantly out of sample,
    signaling overfit parameterization.
    """
    train_pnl = float(train_metrics.get("Net P&L", train_metrics.get("Net Profit", 0.0)))
    oos_pnl = float(oos_metrics.get("Net P&L", oos_metrics.get("Net Profit", 0.0)))

    train_trades = int(train_metrics.get("Total Trades", train_metrics.get("Trades", 0)))
    oos_trades = int(oos_metrics.get("Total Trades", oos_metrics.get("Trades", 0)))

    train_wr = float(train_metrics.get("Win Rate %", 0.0))
    oos_wr = float(oos_metrics.get("Win Rate %", 0.0))

    train_pf = float(train_metrics.get("Profit Factor", 0.0))
    oos_pf = float(oos_metrics.get("Profit Factor", 0.0))

    train_dd = float(train_metrics.get("Maximum Drawdown", 0.0))
    oos_dd = float(oos_metrics.get("Maximum Drawdown", 0.0))

    # PnL Degradation Ratio
    if abs(train_pnl) > 1e-6:
        pnl_degradation = round(oos_pnl / train_pnl, 4)
    else:
        pnl_degradation = 0.0

    # Drawdown Expansion Ratio
    if train_dd > 1e-6:
        dd_expansion = round(oos_dd / train_dd, 4)
    else:
        dd_expansion = round(oos_dd, 4) if oos_dd > 0 else 1.0

    # Overfitting Suspect Heuristic:
    # 1. Train profitable (> 0) but OOS loss (< 0)
    # 2. Train Win Rate >= 50% but OOS Win Rate drops by > 20%
    # 3. Drawdown expands by more than 2x in OOS despite smaller bar slice
    is_overfit_suspect = False
    warning_reasons: list[str] = []

    if train_pnl > 0.0 and oos_pnl < 0.0:
        is_overfit_suspect = True
        warning_reasons.append("PROFIT_REVERSAL: In-sample positive PnL turned negative out-of-sample")

    if train_wr >= 50.0 and (train_wr - oos_wr) >= 20.0:
        is_overfit_suspect = True
        warning_reasons.append(f"WIN_RATE_COLLAPSE: Win rate degraded by {train_wr - oos_wr:.1f}%")

    if train_dd > 0.0 and dd_expansion >= 2.0:
        is_overfit_suspect = True
        warning_reasons.append(f"DRAWDOWN_EXPANSION: Out-of-sample drawdown expanded by {dd_expansion:.1f}x")

    return {
        "train_pnl": train_pnl,
        "oos_pnl": oos_pnl,
        "train_trades": train_trades,
        "oos_trades": oos_trades,
        "pnl_degradation_ratio": pnl_degradation,
        "train_win_rate": train_wr,
        "oos_win_rate": oos_wr,
        "win_rate_decay": round(train_wr - oos_wr, 2),
        "train_profit_factor": train_pf,
        "oos_profit_factor": oos_pf,
        "train_max_drawdown": train_dd,
        "oos_max_drawdown": oos_dd,
        "drawdown_expansion_ratio": dd_expansion,
        "is_overfit_suspect": is_overfit_suspect,
        "warning_reasons": warning_reasons,
    }


from analytics.pbo import (
    PBOResult,
    calculate_pbo,
    calculate_single_model_cpcv_stability,
)

__all__ = [
    "calculate_return_moments",
    "calculate_sharpe_ratio",
    "expected_max_sharpe",
    "deflated_sharpe_ratio",
    "calculate_haircut_sharpe",
    "haircut_sharpe_ratio",
    "calculate_partition_degradation",
    "calculate_pbo",
    "calculate_single_model_cpcv_stability",
    "PBOResult",
]

