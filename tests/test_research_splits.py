from datetime import datetime, timedelta, timezone

import pytest

from broker.types import Candle
from core.exceptions import MarketDataError
from research.splits import chronological_split


def _candles(count: int) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    return [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="research-fixture",
        )
        for i in range(count)
    ]


def test_chronological_split_is_deterministic() -> None:
    candles = _candles(100)

    first = chronological_split(candles)
    second = chronological_split(candles)

    assert first == second
    assert first.total_count == 100


def test_chronological_split_uses_60_20_20_default() -> None:
    result = chronological_split(_candles(100))

    assert len(result.train) == 60
    assert len(result.validation) == 20
    assert len(result.out_of_sample) == 20


def test_chronological_split_has_no_overlap_and_preserves_order() -> None:
    candles = _candles(100)
    result = chronological_split(candles)

    combined = (
        result.train
        + result.validation
        + result.out_of_sample
    )

    assert combined == tuple(candles)
    assert result.train[-1].time < result.validation[0].time
    assert result.validation[-1].time < result.out_of_sample[0].time


def test_chronological_split_supports_explicit_fractions() -> None:
    result = chronological_split(
        _candles(100),
        train_fraction=0.70,
        validation_fraction=0.15,
    )

    assert len(result.train) == 70
    assert len(result.validation) == 15
    assert len(result.out_of_sample) == 15


@pytest.mark.parametrize(
    ("train_fraction", "validation_fraction"),
    [
        (0.0, 0.20),
        (1.0, 0.20),
        (0.60, 0.0),
        (0.60, 1.0),
        (0.80, 0.20),
        (0.90, 0.20),
    ],
)
def test_chronological_split_rejects_invalid_fractions(
    train_fraction: float,
    validation_fraction: float,
) -> None:
    with pytest.raises(MarketDataError):
        chronological_split(
            _candles(100),
            train_fraction=train_fraction,
            validation_fraction=validation_fraction,
        )


def test_chronological_split_rejects_non_monotonic_data() -> None:
    candles = _candles(5)
    candles[2], candles[3] = candles[3], candles[2]

    with pytest.raises(MarketDataError):
        chronological_split(candles)


def test_chronological_split_rejects_too_small_dataset() -> None:
    with pytest.raises(MarketDataError):
        chronological_split(_candles(2))
