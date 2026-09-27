"""Probability of Backtest Overfitting (PBO) estimation.

Implements the non-parametric PBO formulation from Bailey, Borwein, Lopez de Prado,
and Zhu (2016) / Lopez de Prado (2018):
- Evaluates in-sample (IS) selection vs. out-of-sample (OOS) performance rank.
- Computes empirical probability of selecting a configuration whose OOS rank
  falls below the median (omega_c <= 0.5).
- Provides logit distribution and overfit risk categorization.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class PBOResult:
    """Statistical summary of backtest overfitting across combinatorial splits."""

    pbo: float
    n_splits: int
    n_models: int
    logits: tuple[float, ...]
    relative_ranks: tuple[float, ...]
    degraded_splits_count: int
    median_oos_rank: float
    risk_level: str

    @property
    def is_overfit(self) -> bool:
        """True if PBO indicates greater than 50% likelihood of overfit selection."""
        return self.pbo >= 0.50


def calculate_pbo(
    is_matrix: Sequence[Sequence[float]],
    oos_matrix: Sequence[Sequence[float]],
) -> PBOResult:
    """Calculate Probability of Backtest Overfitting (PBO) from IS and OOS matrices.

    Args:
        is_matrix: In-sample performance matrix of shape (n_splits, n_models).
        oos_matrix: Out-of-sample performance matrix of shape (n_splits, n_models).

    Returns:
        PBOResult containing PBO, relative ranks, logit distribution, and risk categorization.

    Raises:
        ValueError: If matrices are empty, mismatched in dimension, or contain non-finite values.
    """
    n_splits = len(is_matrix)
    if n_splits == 0:
        raise ValueError("is_matrix must contain at least one split")
    if len(oos_matrix) != n_splits:
        raise ValueError(
            f"Dimension mismatch: is_matrix has {n_splits} splits, oos_matrix has {len(oos_matrix)}"
        )

    n_models = len(is_matrix[0])
    if n_models == 0:
        raise ValueError("is_matrix must contain at least one model column")

    # Validate shapes and finitude
    for c in range(n_splits):
        if len(is_matrix[c]) != n_models:
            raise ValueError(f"Split {c} in is_matrix has {len(is_matrix[c])} models, expected {n_models}")
        if len(oos_matrix[c]) != n_models:
            raise ValueError(f"Split {c} in oos_matrix has {len(oos_matrix[c])} models, expected {n_models}")
        for m in range(n_models):
            if not math.isfinite(is_matrix[c][m]) or not math.isfinite(oos_matrix[c][m]):
                raise ValueError(f"Non-finite value at split {c}, model {m}")

    relative_ranks: list[float] = []
    logits: list[float] = []
    degraded_count = 0

    for c in range(n_splits):
        is_row = is_matrix[c]
        oos_row = oos_matrix[c]

        # 1. Identify optimal in-sample model index (m*)
        # In case of tie, take the first occurrence
        best_m = max(range(n_models), key=lambda m: is_row[m])
        oos_selected_perf = oos_row[best_m]

        # 2. Compute fractional rank of m* in OOS performance
        n_less = sum(1 for v in oos_row if v < oos_selected_perf)
        n_equal = sum(1 for v in oos_row if v == oos_selected_perf)

        # Standard mid-rank formula
        rank = n_less + 1 + 0.5 * (n_equal - 1)

        # Normalized relative rank in (0, 1)
        omega = rank / (n_models + 1.0)
        relative_ranks.append(omega)

        # 3. Logit transform lambda_c = ln(omega / (1 - omega))
        # Clamp omega to avoid division by zero or log of non-positive
        clamped_omega = min(max(omega, 1e-6), 1.0 - 1e-6)
        logit = math.log(clamped_omega / (1.0 - clamped_omega))
        logits.append(logit)

        # 4. Count splits where selected model degraded below median (omega <= 0.5)
        if omega <= 0.5:
            degraded_count += 1

    pbo = degraded_count / float(n_splits)

    sorted_ranks = sorted(relative_ranks)
    mid = n_splits // 2
    if n_splits % 2 == 1:
        median_rank = sorted_ranks[mid]
    else:
        median_rank = 0.5 * (sorted_ranks[mid - 1] + sorted_ranks[mid])

    if pbo < 0.15:
        risk_level = "LOW"
    elif pbo < 0.35:
        risk_level = "MODERATE"
    elif pbo < 0.50:
        risk_level = "HIGH"
    else:
        risk_level = "SEVERE"

    return PBOResult(
        pbo=round(pbo, 4),
        n_splits=n_splits,
        n_models=n_models,
        logits=tuple(round(l, 4) for l in logits),
        relative_ranks=tuple(round(r, 4) for r in relative_ranks),
        degraded_splits_count=degraded_count,
        median_oos_rank=round(median_rank, 4),
        risk_level=risk_level,
    )


def calculate_single_model_cpcv_stability(
    is_metrics: Sequence[float],
    oos_metrics: Sequence[float],
) -> dict[str, float | int | str]:
    """Evaluate OOS stability for a single strategy without competing parameter trials.

    Calculates:
    - OOS degradation frequency (fraction of splits where OOS < 0.5 * IS)
    - Reversal rate (fraction of splits where OOS <= 0 despite positive IS)
    - Mean performance retention ratio
    """
    n = len(is_metrics)
    if n == 0 or len(oos_metrics) != n:
        raise ValueError("is_metrics and oos_metrics must have equal non-zero length")

    reversals = 0
    degraded = 0
    retentions: list[float] = []

    for is_val, oos_val in zip(is_metrics, oos_metrics):
        if is_val > 0 and oos_val <= 0:
            reversals += 1
        if oos_val < 0.5 * is_val:
            degraded += 1
        if abs(is_val) > 1e-6:
            retentions.append(oos_val / is_val)

    reversal_rate = reversals / float(n)
    degradation_rate = degraded / float(n)
    mean_retention = sum(retentions) / len(retentions) if retentions else 0.0

    return {
        "n_splits": n,
        "reversal_count": reversals,
        "reversal_rate": round(reversal_rate, 4),
        "degradation_count": degraded,
        "degradation_rate": round(degradation_rate, 4),
        "mean_retention_ratio": round(mean_retention, 4),
        "stability_verdict": (
            "STABLE" if degradation_rate < 0.25 and reversal_rate == 0
            else "MODERATE_DEGRADATION" if degradation_rate < 0.50
            else "UNSTABLE"
        ),
    }
