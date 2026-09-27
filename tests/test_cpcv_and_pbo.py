"""Unit tests for Combinatorial Purged Cross-Validation (CPCV) and PBO estimation (Phase 6).

Validates:
1. CPCVConfig parameter validation and combination counting.
2. partition_groups contiguous block splitting and timestamp validation.
3. generate_cpcv_splits combinatorial generation, disjointness, purging, and embargoing.
4. calculate_pbo matrix validation, non-parametric ranking, and overfit likelihood.
5. calculate_single_model_cpcv_stability single-strategy degradation metrics.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
import pytest

from analytics.pbo import (
    PBOResult,
    calculate_pbo,
    calculate_single_model_cpcv_stability,
)
from broker.types import Candle
from core.exceptions import MarketDataError
from research.cpcv import (
    CPCVConfig,
    CPCVGroup,
    CPCVSplit,
    generate_cpcv_splits,
    partition_groups,
)


def _make_candles(n: int) -> list[Candle]:
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(
            time=base_time + timedelta(minutes=5 * i),
            open=100.0 + i,
            high=105.0 + i,
            low=95.0 + i,
            close=102.0 + i,
            volume=100.0,
            source="synthetic",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. CPCVConfig tests
# ---------------------------------------------------------------------------

class TestCPCVConfig:
    def test_default_config(self) -> None:
        cfg = CPCVConfig()
        assert cfg.n_groups == 5
        assert cfg.k_test_groups == 2
        assert cfg.total_combinations == 10  # C(5, 2) = 10

    def test_combinations_formula(self) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=2)
        assert cfg.total_combinations == 15  # C(6, 2) = 15
        cfg2 = CPCVConfig(n_groups=4, k_test_groups=1)
        assert cfg2.total_combinations == 4  # C(4, 1) = 4

    def test_invalid_n_groups(self) -> None:
        with pytest.raises(ValueError, match="at least 3 groups"):
            CPCVConfig(n_groups=2)

    def test_invalid_k_test_groups(self) -> None:
        with pytest.raises(ValueError, match="must be in"):
            CPCVConfig(n_groups=5, k_test_groups=5)
        with pytest.raises(ValueError, match="must be in"):
            CPCVConfig(n_groups=5, k_test_groups=0)

    def test_invalid_embargo_fraction(self) -> None:
        with pytest.raises(ValueError, match="embargo_fraction"):
            CPCVConfig(embargo_fraction=-0.01)
        with pytest.raises(ValueError, match="embargo_fraction"):
            CPCVConfig(embargo_fraction=0.6)


# ---------------------------------------------------------------------------
# 2. Partition groups tests
# ---------------------------------------------------------------------------

class TestPartitionGroups:
    def test_partition_contiguous_and_exhaustive(self) -> None:
        candles = _make_candles(100)
        groups = partition_groups(candles, n_groups=5)
        assert len(groups) == 5

        # Check contiguity and coverage
        prev_end = 0
        for i, grp in enumerate(groups):
            assert grp.group_id == i
            assert grp.start_index == prev_end
            assert grp.end_index > grp.start_index
            prev_end = grp.end_index

        assert prev_end == 100
        assert sum(g.candle_count for g in groups) == 100

    def test_partition_insufficient_candles(self) -> None:
        candles = _make_candles(10)
        with pytest.raises(MarketDataError, match="Insufficient candles"):
            partition_groups(candles, n_groups=5)

    def test_partition_non_increasing_timestamps(self) -> None:
        candles = _make_candles(50)
        # Invert one timestamp
        broken = list(candles)
        broken[10] = Candle(
            time=broken[9].time,  # duplicate timestamp
            open=100.0, high=105.0, low=95.0, close=102.0, volume=100.0, source="synthetic",
        )
        with pytest.raises(MarketDataError, match="strictly increasing"):
            partition_groups(broken, n_groups=5)


# ---------------------------------------------------------------------------
# 3. CPCV Split Generation & Purged Embargo
# ---------------------------------------------------------------------------

class TestCPCVSplitGeneration:
    def test_split_counts_and_disjointness(self) -> None:
        candles = _make_candles(150)
        cfg = CPCVConfig(n_groups=5, k_test_groups=2, embargo_fraction=0.02, min_embargo_bars=2)
        splits = generate_cpcv_splits(candles, cfg)

        assert len(splits) == 10  # C(5, 2) = 10

        for split in splits:
            assert len(split.test_group_ids) == 2
            assert len(split.train_group_ids) == 3
            assert split.train_count > 0
            assert split.test_count > 0

            # Disjointness: Train and Test sets must never intersect!
            train_set = set(split.train_indices)
            test_set = set(split.test_indices)
            assert train_set.isdisjoint(test_set), "Train and Test sets must be strictly disjoint!"

            # Embargo indices must come from raw train candidates
            if split.embargoed_count > 0:
                embargo_set = set(split.embargoed_indices)
                assert embargo_set.isdisjoint(train_set)
                assert embargo_set.isdisjoint(test_set)

    def test_purging_removes_preceding_bars(self) -> None:
        candles = _make_candles(200)
        # Purge 5 bars before each test set
        cfg = CPCVConfig(n_groups=4, k_test_groups=1, purge_bars=5, embargo_fraction=0.01)
        splits = generate_cpcv_splits(candles, cfg)

        assert len(splits) == 4
        # For splits where test group is > 0 (has preceding train group), purged_count > 0
        non_zero_purges = [s for s in splits if s.purged_count > 0]
        assert len(non_zero_purges) >= 2

    def test_deterministic_reproducibility(self) -> None:
        candles = _make_candles(120)
        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        s1 = generate_cpcv_splits(candles, cfg)
        s2 = generate_cpcv_splits(candles, cfg)
        for split_a, split_b in zip(s1, s2):
            assert split_a.train_indices == split_b.train_indices
            assert split_a.test_indices == split_b.test_indices


# ---------------------------------------------------------------------------
# 4. Probability of Backtest Overfitting (PBO)
# ---------------------------------------------------------------------------

class TestPBOEstimation:
    def test_pbo_perfect_consistency_is_zero(self) -> None:
        """When the best in-sample model is also the best out-of-sample in all splits,
        PBO should be 0.0 (zero overfitting)."""
        # 5 splits, 4 models
        # Model 3 always best in both IS and OOS
        is_matrix = [
            [1.0, 1.2, 0.8, 2.5],
            [0.5, 1.1, 0.9, 3.0],
            [1.1, 1.4, 0.6, 2.8],
            [0.9, 1.0, 0.7, 2.2],
            [1.2, 1.3, 0.8, 2.9],
        ]
        oos_matrix = [
            [0.8, 1.0, 0.5, 2.1],
            [0.4, 0.9, 0.6, 2.4],
            [0.9, 1.1, 0.4, 2.2],
            [0.7, 0.8, 0.5, 1.9],
            [1.0, 1.1, 0.6, 2.3],
        ]
        res = calculate_pbo(is_matrix, oos_matrix)
        assert res.pbo == 0.0
        assert res.degraded_splits_count == 0
        assert res.risk_level == "LOW"
        assert res.is_overfit is False

    def test_pbo_severe_overfitting_is_one(self) -> None:
        """When the best in-sample model is always the worst out-of-sample (rank 1),
        PBO should be 1.0 (severe overfitting)."""
        # Model 0 is best in IS, but worst in OOS in all splits
        is_matrix = [
            [3.0, 1.0, 0.5],
            [2.8, 1.2, 0.4],
            [3.2, 0.9, 0.6],
            [2.9, 1.1, 0.5],
        ]
        oos_matrix = [
            [-1.5, 1.0, 0.8],
            [-1.2, 0.9, 0.6],
            [-2.0, 1.1, 0.7],
            [-1.4, 0.8, 0.5],
        ]
        res = calculate_pbo(is_matrix, oos_matrix)
        assert res.pbo == 1.0
        assert res.degraded_splits_count == 4
        assert res.risk_level == "SEVERE"
        assert res.is_overfit is True

    def test_pbo_validation_errors(self) -> None:
        with pytest.raises(ValueError, match="at least one split"):
            calculate_pbo([], [])
        with pytest.raises(ValueError, match="Dimension mismatch"):
            calculate_pbo([[1.0]], [[1.0], [2.0]])
        with pytest.raises(ValueError, match="at least one model"):
            calculate_pbo([[]], [[]])
        with pytest.raises(ValueError, match="Non-finite value"):
            calculate_pbo([[math.nan]], [[1.0]])

    def test_pbo_tied_models_handled(self) -> None:
        # All models have identical performance
        is_matrix = [[1.5, 1.5], [1.5, 1.5]]
        oos_matrix = [[1.0, 1.0], [1.0, 1.0]]
        res = calculate_pbo(is_matrix, oos_matrix)
        assert 0.0 <= res.pbo <= 1.0


# ---------------------------------------------------------------------------
# 5. Single model stability across CPCV
# ---------------------------------------------------------------------------

class TestSingleModelStability:
    def test_stable_strategy(self) -> None:
        is_sh = [1.5, 1.8, 1.6, 1.7, 1.9]
        oos_sh = [1.2, 1.4, 1.3, 1.5, 1.6]
        res = calculate_single_model_cpcv_stability(is_sh, oos_sh)
        assert res["reversal_count"] == 0
        assert res["reversal_rate"] == 0.0
        assert res["degradation_count"] == 0
        assert res["stability_verdict"] == "STABLE"

    def test_reversal_strategy(self) -> None:
        is_sh = [1.5, 1.8, 1.6, 1.7]
        oos_sh = [-0.5, 0.1, -0.2, 0.2]
        res = calculate_single_model_cpcv_stability(is_sh, oos_sh)
        assert res["reversal_count"] == 2
        assert res["reversal_rate"] == 0.5
        assert res["stability_verdict"] == "UNSTABLE"
