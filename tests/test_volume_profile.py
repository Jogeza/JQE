from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from broker.types import Candle
from data.provenance import VolumeType
from research.volume_profile import (
    FRVP_ALGORITHM_VERSION, MAX_PROFILE_BINS, VolumeAllocationMethod,
    VolumeProfileEligibility, VolumeProfileRequest,
    calculate_volume_profile,
)


def candle(index: int, low: float, high: float, volume: float | None) -> Candle:
    return Candle(time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * index),
                  open=low, high=high, low=low, close=high, volume=volume, source="fixture")


def profile(candles, *, volume_type=VolumeType.REAL_VOLUME, start=0, end=None,
            bin_size="1", fraction="0.70", step_seconds=900):
    request = VolumeProfileRequest(start, len(candles)-1 if end is None else end,
                                   Decimal(bin_size), Decimal(fraction))
    return calculate_volume_profile(candles, dataset_identity="sha256:" + "a" * 64,
                                    volume_type=volume_type, volume_source="fixture",
                                    request=request, step_seconds=step_seconds)


@pytest.mark.parametrize("volume_type", [VolumeType.REAL_VOLUME, VolumeType.TICK_VOLUME,
    VolumeType.BROKER_VOLUME, VolumeType.SIMULATED_VOLUME])
def test_supported_volume_semantics_are_eligible(volume_type):
    assert profile([candle(0, 1, 2, 10)], volume_type=volume_type).eligible


@pytest.mark.parametrize("volume_type,reason", [
    (VolumeType.UNAVAILABLE, VolumeProfileEligibility.VOLUME_UNAVAILABLE),
    (VolumeType.UNKNOWN, VolumeProfileEligibility.VOLUME_SEMANTICS_UNKNOWN),
])
def test_unproven_volume_semantics_fail_closed(volume_type, reason):
    result = profile([candle(0, 1, 2, None)], volume_type=volume_type)
    assert result.eligibility is reason and result.snapshot is None


def test_single_candle_single_bin():
    snapshot = profile([candle(0, 1, 2, 10)], bin_size="2").snapshot
    assert snapshot.bins == ((type(snapshot.bins[0]))(Decimal("1"), Decimal("2"), Decimal("10")),)
    assert snapshot.point_of_control == Decimal("1.5")


def test_uniform_overlap_and_exact_volume_conservation():
    snapshot = profile([candle(0, 0.1, 0.3, 3)], bin_size="0.1").snapshot
    assert [item.volume for item in snapshot.bins] == [Decimal("1.5"), Decimal("1.5")]
    assert sum((item.volume for item in snapshot.bins), Decimal(0)) == snapshot.total_volume == Decimal("3")
    assert snapshot.point_of_control == Decimal("0.15")  # lower-bin POC tie break


def test_multiple_candles_value_area_expands_contiguously_lower_first_on_tie():
    candles = [candle(0, 0, 1, 2), candle(1, 1, 2, 5), candle(2, 2, 3, 2)]
    snapshot = profile(candles, fraction="0.75").snapshot
    assert [item.volume for item in snapshot.bins] == [Decimal(2), Decimal(5), Decimal(2)]
    assert snapshot.point_of_control == Decimal("1.5")
    assert snapshot.value_area_low == Decimal(0)
    assert snapshot.value_area_high == Decimal(2)


def test_zero_range_candle_allocates_all_volume_to_containing_bin():
    snapshot = profile([candle(0, 0, 2, 2), candle(1, 1, 1, 7)]).snapshot
    assert snapshot.bins[1].volume == Decimal(8)
    assert snapshot.total_volume == Decimal(9)


@pytest.mark.parametrize("candles,expected", [
    ([candle(0, 0, 1, 10), candle(1, 1, 3, 2)], Decimal("0.5")),
    ([candle(0, 0, 2, 2), candle(1, 2, 3, 10)], Decimal("2.5")),
])
def test_poc_can_be_at_profile_edges(candles, expected):
    assert profile(candles).snapshot.point_of_control == expected


def test_missing_volume_fails_closed():
    result = profile([candle(0, 1, 2, None)])
    assert result.eligibility is VolumeProfileEligibility.MISSING_CANDLE_VOLUME
    assert result.snapshot is None


@pytest.mark.parametrize("start,end", [(-1, 0), (1, 0), (0, 2)])
def test_invalid_ranges_return_typed_result(start, end):
    assert profile([candle(0, 1, 2, 1)], start=start, end=end).eligibility is VolumeProfileEligibility.INVALID_RANGE


@pytest.mark.parametrize("size,fraction", [("0", "0.7"), ("-1", "0.7"), ("1", "0"), ("1", "1.1")])
def test_invalid_bin_configuration(size, fraction):
    result = profile([candle(0, 1, 2, 1)], bin_size=size, fraction=fraction)
    assert result.eligibility is VolumeProfileEligibility.INVALID_BIN_CONFIGURATION


def test_unsupported_allocation_method_fails_closed():
    request = VolumeProfileRequest(0, 0, Decimal("1"), allocation_method="OTHER")  # type: ignore[arg-type]
    result = calculate_volume_profile([candle(0, 1, 2, 1)], dataset_identity="sha256:test",
        volume_type=VolumeType.REAL_VOLUME, volume_source="fixture", request=request)
    assert result.eligibility is VolumeProfileEligibility.INVALID_BIN_CONFIGURATION


def test_excessive_bin_request_rejected_before_allocation():
    result = profile([candle(0, 0, 1, 1)], bin_size=str(Decimal(1) / (MAX_PROFILE_BINS + 1)))
    assert result.eligibility is VolumeProfileEligibility.INVALID_BIN_CONFIGURATION


def test_one_bin_value_area_and_exact_threshold():
    snapshot = profile([candle(0, 10, 10.2, 5)], bin_size="0.3", fraction="1").snapshot
    assert snapshot.value_area_low == Decimal("10")
    assert snapshot.value_area_high == Decimal("10.2")


def test_small_fx_and_large_gold_decimal_boundaries():
    fx = profile([candle(0, 1.0001, 1.0003, 2)], bin_size="0.0001").snapshot
    gold = profile([candle(0, 4400.1, 4400.3, 2)], bin_size="0.1").snapshot
    assert len(fx.bins) == len(gold.bins) == 2
    assert fx.total_volume == gold.total_volume == Decimal(2)


def test_snapshot_is_reproducible_and_preserves_identity_and_version():
    candles = [candle(0, 1, 3, 10), candle(1, 2, 4, 5)]
    first, second = profile(candles).snapshot, profile(list(candles)).snapshot
    assert first == second
    assert first.to_json_bytes() == second.to_json_bytes()
    assert first.dataset_identity == "sha256:" + "a" * 64
    assert first.request.algorithm_version == FRVP_ALGORITHM_VERSION


def test_gap_metadata_is_preserved_without_interpolation():
    candles = [candle(0, 1, 2, 1), candle(4, 1, 2, 1)]
    snapshot = profile(candles).snapshot
    assert snapshot.range_has_gaps and snapshot.gap_count == 1


def test_bin_invariants_and_value_area_threshold():
    snapshot = profile([candle(0, 0, 3, 9)], fraction="0.7").snapshot
    assert all(item.volume >= 0 for item in snapshot.bins)
    assert all(left.high == right.low for left, right in zip(snapshot.bins, snapshot.bins[1:]))
    assert snapshot.bins[0].low == snapshot.profile_low
    assert snapshot.bins[-1].high == snapshot.profile_high
    assert snapshot.value_area_low <= snapshot.point_of_control <= snapshot.value_area_high
    selected = [b for b in snapshot.bins if b.low >= snapshot.value_area_low and b.high <= snapshot.value_area_high]
    assert sum((b.volume for b in selected), Decimal(0)) >= snapshot.total_volume * snapshot.request.value_area_fraction
