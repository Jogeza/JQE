"""Deterministic chronological dataset splitting for JQE research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from broker.types import Candle
from core.exceptions import MarketDataError


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    """Chronological train/validation/out-of-sample candle partitions."""

    train: tuple[Candle, ...]
    validation: tuple[Candle, ...]
    out_of_sample: tuple[Candle, ...]

    @property
    def total_count(self) -> int:
        return len(self.train) + len(self.validation) + len(self.out_of_sample)


def chronological_split(
    candles: Sequence[Candle],
    *,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
) -> DatasetSplit:
    """Split canonical candles chronologically without overlap or shuffling."""
    ordered = tuple(candles)

    if len(ordered) < 3:
        raise MarketDataError(
            "Research dataset requires at least three candles for chronological splitting"
        )

    if any(
        current.time <= previous.time
        for previous, current in zip(ordered, ordered[1:])
    ):
        raise MarketDataError(
            "Research dataset split requires strictly increasing timestamps"
        )

    if not 0.0 < train_fraction < 1.0:
        raise MarketDataError(
            "Research train fraction must be between zero and one"
        )

    if not 0.0 < validation_fraction < 1.0:
        raise MarketDataError(
            "Research validation fraction must be between zero and one"
        )

    if train_fraction + validation_fraction >= 1.0:
        raise MarketDataError(
            "Research train and validation fractions must leave an out-of-sample partition"
        )

    total = len(ordered)
    train_end = int(total * train_fraction)
    validation_end = train_end + int(total * validation_fraction)

    if train_end <= 0:
        raise MarketDataError("Research train partition is empty")

    if validation_end <= train_end:
        raise MarketDataError("Research validation partition is empty")

    if validation_end >= total:
        raise MarketDataError("Research out-of-sample partition is empty")

    return DatasetSplit(
        train=ordered[:train_end],
        validation=ordered[train_end:validation_end],
        out_of_sample=ordered[validation_end:],
    )
