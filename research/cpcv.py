"""Combinatorial Purged Cross-Validation (CPCV) for institutional backtest validation.

Implements Marcos Lopez de Prado (Advances in Financial Machine Learning, Ch. 12)
methodology:
- Deterministic division into N contiguous chronological blocks.
- Exhaustive combinatorial generation of C(N, k) test paths.
- Information purging and autoregressive embargoing to guarantee zero lookahead
  or serial correlation leakage.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from broker.types import Candle
from core.exceptions import MarketDataError


@dataclass(frozen=True, slots=True)
class CPCVConfig:
    """Parameters governing combinatorial block generation, purging, and embargoing."""

    n_groups: int = 5
    k_test_groups: int = 2
    embargo_fraction: float = 0.01
    min_embargo_bars: int = 5
    purge_bars: int = 0

    def __post_init__(self) -> None:
        if self.n_groups < 3:
            raise ValueError("CPCV requires at least 3 groups")
        if not (1 <= self.k_test_groups < self.n_groups):
            raise ValueError(
                f"k_test_groups must be in [1, n_groups-1], got k={self.k_test_groups}, n={self.n_groups}"
            )
        if not (0.0 <= self.embargo_fraction < 0.5):
            raise ValueError("embargo_fraction must be in [0.0, 0.5)")
        if self.min_embargo_bars < 0:
            raise ValueError("min_embargo_bars cannot be negative")
        if self.purge_bars < 0:
            raise ValueError("purge_bars cannot be negative")

    @property
    def total_combinations(self) -> int:
        return math.comb(self.n_groups, self.k_test_groups)


@dataclass(frozen=True, slots=True)
class CPCVGroup:
    """A single contiguous chronological slice of candle history."""

    group_id: int
    start_index: int
    end_index: int  # exclusive
    candle_count: int
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True, slots=True)
class CPCVSplit:
    """A single combinatorial train/test split with purged & embargoed masks."""

    split_id: int
    test_group_ids: tuple[int, ...]
    train_group_ids: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_indices: tuple[int, ...]
    purged_indices: tuple[int, ...]
    embargoed_indices: tuple[int, ...]

    @property
    def test_count(self) -> int:
        return len(self.test_indices)

    @property
    def train_count(self) -> int:
        return len(self.train_indices)

    @property
    def purged_count(self) -> int:
        return len(self.purged_indices)

    @property
    def embargoed_count(self) -> int:
        return len(self.embargoed_indices)


def partition_groups(
    candles: Sequence[Candle],
    n_groups: int = 5,
) -> tuple[CPCVGroup, ...]:
    """Deterministically partition candles into N contiguous non-overlapping groups."""
    total = len(candles)
    if total < n_groups * 3:
        raise MarketDataError(
            f"Insufficient candles ({total}) for {n_groups} CPCV groups (minimum {n_groups * 3})"
        )

    # Validate timestamps are strictly increasing
    if any(candles[i].time >= candles[i + 1].time for i in range(total - 1)):
        raise MarketDataError("Candle timestamps must be strictly increasing for CPCV")

    base_size = total // n_groups
    remainder = total % n_groups

    groups: list[CPCVGroup] = []
    current_idx = 0

    for g in range(n_groups):
        # Distribute remainder across the earliest groups
        size = base_size + (1 if g < remainder else 0)
        start_idx = current_idx
        end_idx = current_idx + size
        current_idx = end_idx

        group = CPCVGroup(
            group_id=g,
            start_index=start_idx,
            end_index=end_idx,
            candle_count=size,
            start_time=candles[start_idx].time,
            end_time=candles[end_idx - 1].time,
        )
        groups.append(group)

    return tuple(groups)


def generate_cpcv_splits(
    candles: Sequence[Candle],
    config: CPCVConfig | None = None,
) -> tuple[CPCVSplit, ...]:
    """Generate all C(N, k) combinatorial splits with purging and embargoing."""
    cfg = config or CPCVConfig()
    groups = partition_groups(candles, cfg.n_groups)
    total_candles = len(candles)

    embargo_bars = max(int(total_candles * cfg.embargo_fraction), cfg.min_embargo_bars)

    splits: list[CPCVSplit] = []
    combo_tuples = list(itertools.combinations(range(cfg.n_groups), cfg.k_test_groups))

    for split_id, test_group_ids in enumerate(combo_tuples):
        train_group_ids = tuple(g for g in range(cfg.n_groups) if g not in test_group_ids)

        # Collect raw test indices
        test_indices_set: set[int] = set()
        for gid in test_group_ids:
            grp = groups[gid]
            test_indices_set.update(range(grp.start_index, grp.end_index))

        # Collect raw train candidate indices
        train_candidates: set[int] = set()
        for gid in train_group_ids:
            grp = groups[gid]
            train_candidates.update(range(grp.start_index, grp.end_index))

        # Apply purging & embargoing based on test group boundaries
        purged_set: set[int] = set()
        embargoed_set: set[int] = set()

        for gid in test_group_ids:
            grp = groups[gid]

            # 1. Purge training bars immediately preceding test start
            if cfg.purge_bars > 0:
                purge_start = max(0, grp.start_index - cfg.purge_bars)
                purge_range = range(purge_start, grp.start_index)
                for idx in purge_range:
                    if idx in train_candidates:
                        purged_set.add(idx)

            # 2. Embargo training bars immediately following test end
            if embargo_bars > 0:
                embargo_end = min(total_candles, grp.end_index + embargo_bars)
                embargo_range = range(grp.end_index, embargo_end)
                for idx in embargo_range:
                    if idx in train_candidates:
                        embargoed_set.add(idx)

        # Clean train indices
        final_train_set = train_candidates - purged_set - embargoed_set

        if not final_train_set:
            raise MarketDataError(
                f"CPCV split {split_id} has empty training set after purging/embargoing"
            )
        if not test_indices_set:
            raise MarketDataError(f"CPCV split {split_id} has empty test set")

        split = CPCVSplit(
            split_id=split_id,
            test_group_ids=test_group_ids,
            train_group_ids=train_group_ids,
            test_indices=tuple(sorted(test_indices_set)),
            train_indices=tuple(sorted(final_train_set)),
            purged_indices=tuple(sorted(purged_set)),
            embargoed_indices=tuple(sorted(embargoed_set)),
        )
        splits.append(split)

    return tuple(splits)
