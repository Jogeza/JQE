"""Deterministic, research-only Fixed Range Volume Profile engine."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from enum import Enum
from typing import Sequence

from broker.types import Candle
from data.provenance import VolumeType

FRVP_ALGORITHM_VERSION = "frvp-contract-v1"
MAX_PROFILE_BINS = 2_000


class VolumeAllocationMethod(str, Enum):
    UNIFORM_RANGE_OVERLAP_V1 = "UNIFORM_RANGE_OVERLAP_V1"


class VolumeProfileEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    VOLUME_UNAVAILABLE = "VOLUME_UNAVAILABLE"
    VOLUME_SEMANTICS_UNKNOWN = "VOLUME_SEMANTICS_UNKNOWN"
    INVALID_RANGE = "INVALID_RANGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_BIN_CONFIGURATION = "INVALID_BIN_CONFIGURATION"
    MISSING_CANDLE_VOLUME = "MISSING_CANDLE_VOLUME"
    INVALID_CANDLE_DATA = "INVALID_CANDLE_DATA"
    ALGORITHM_VERSION_UNSUPPORTED = "ALGORITHM_VERSION_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class VolumeProfileRequest:
    """Inclusive candle-index range and reproducible FRVP configuration."""
    start_index: int
    end_index: int
    bin_size: Decimal
    value_area_fraction: Decimal = Decimal("0.70")
    allocation_method: VolumeAllocationMethod = VolumeAllocationMethod.UNIFORM_RANGE_OVERLAP_V1
    algorithm_version: str = FRVP_ALGORITHM_VERSION


@dataclass(frozen=True, slots=True)
class VolumeProfileBin:
    low: Decimal
    high: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class VolumeProfileSnapshot:
    dataset_identity: str
    request: VolumeProfileRequest
    start_time: datetime
    end_time: datetime
    candle_count: int
    volume_type: VolumeType
    volume_source: str
    profile_low: Decimal
    profile_high: Decimal
    total_volume: Decimal
    bins: tuple[VolumeProfileBin, ...]
    point_of_control: Decimal
    value_area_high: Decimal
    value_area_low: Decimal
    range_has_gaps: bool
    gap_count: int

    def to_json_bytes(self) -> bytes:
        def normalize(value):
            if isinstance(value, Decimal): return str(value)
            if isinstance(value, datetime): return value.isoformat()
            if isinstance(value, Enum): return value.value
            if isinstance(value, dict): return {key: normalize(item) for key, item in sorted(value.items())}
            if isinstance(value, (tuple, list)): return [normalize(item) for item in value]
            return value
        return (json.dumps(normalize(asdict(self)), sort_keys=True, separators=(",", ":")) + "\n").encode()


@dataclass(frozen=True, slots=True)
class VolumeProfileResult:
    eligibility: VolumeProfileEligibility
    reason: str
    snapshot: VolumeProfileSnapshot | None = None

    @property
    def eligible(self) -> bool:
        return self.eligibility is VolumeProfileEligibility.ELIGIBLE


_ELIGIBLE_TYPES = {VolumeType.REAL_VOLUME, VolumeType.TICK_VOLUME, VolumeType.BROKER_VOLUME, VolumeType.SIMULATED_VOLUME}


def _decimal(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite(): raise InvalidOperation
    return result


def calculate_volume_profile(candles: Sequence[Candle], *, dataset_identity: str,
                             volume_type: VolumeType, volume_source: str,
                             request: VolumeProfileRequest, step_seconds: int | None = None) -> VolumeProfileResult:
    """Calculate FRVP from canonical candles; start/end indexes are inclusive."""
    if volume_type is VolumeType.UNAVAILABLE:
        return VolumeProfileResult(VolumeProfileEligibility.VOLUME_UNAVAILABLE, "Volume data is unavailable")
    if volume_type is VolumeType.UNKNOWN:
        return VolumeProfileResult(VolumeProfileEligibility.VOLUME_SEMANTICS_UNKNOWN, "Volume semantics are unknown")
    if volume_type not in _ELIGIBLE_TYPES:
        return VolumeProfileResult(VolumeProfileEligibility.VOLUME_SEMANTICS_UNKNOWN, "Volume semantics are unsupported")
    if request.algorithm_version != FRVP_ALGORITHM_VERSION:
        return VolumeProfileResult(VolumeProfileEligibility.ALGORITHM_VERSION_UNSUPPORTED, "Algorithm version is unsupported")
    if request.allocation_method is not VolumeAllocationMethod.UNIFORM_RANGE_OVERLAP_V1:
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_BIN_CONFIGURATION, "Allocation method is unsupported")
    if request.start_index < 0 or request.end_index < request.start_index or request.end_index >= len(candles):
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_RANGE, "Selected candle range is invalid")
    try:
        bin_size, fraction = _decimal(request.bin_size), _decimal(request.value_area_fraction)
    except (InvalidOperation, ValueError):
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_BIN_CONFIGURATION, "Bin configuration must be finite Decimal values")
    if bin_size <= 0 or not Decimal(0) < fraction <= Decimal(1):
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_BIN_CONFIGURATION, "Bin size and value-area fraction are invalid")
    selected = tuple(candles[request.start_index:request.end_index + 1])
    if not selected:
        return VolumeProfileResult(VolumeProfileEligibility.INSUFFICIENT_DATA, "Selected range contains no candles")
    try:
        lows, highs = [_decimal(c.low) for c in selected], [_decimal(c.high) for c in selected]
        volumes = [_decimal(c.volume) if c.volume is not None else None for c in selected]
    except (InvalidOperation, ValueError):
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_CANDLE_DATA, "Candle values must be finite")
    if any(volume is None for volume in volumes):
        return VolumeProfileResult(VolumeProfileEligibility.MISSING_CANDLE_VOLUME, "Every selected candle requires volume")
    if any(low > high for low, high in zip(lows, highs)) or any(volume < 0 for volume in volumes if volume is not None):
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_CANDLE_DATA, "Candle ranges and volumes must be valid")
    profile_low, profile_high = min(lows), max(highs)
    span = profile_high - profile_low
    if span > bin_size * MAX_PROFILE_BINS:
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_BIN_CONFIGURATION, f"Profile exceeds {MAX_PROFILE_BINS} bins")
    bin_count = max(1, int((span / bin_size).to_integral_value(rounding=ROUND_CEILING)))
    if bin_count > MAX_PROFILE_BINS:
        return VolumeProfileResult(VolumeProfileEligibility.INVALID_BIN_CONFIGURATION, f"Profile exceeds {MAX_PROFILE_BINS} bins")
    boundaries = [profile_low + bin_size * index for index in range(bin_count)]
    boundaries.append(profile_high if span > 0 else profile_low + bin_size)
    allocated = [Decimal(0) for _ in range(bin_count)]
    for low, high, volume in zip(lows, highs, volumes):
        assert volume is not None
        if high == low:
            index = min(int((low - profile_low) // bin_size), bin_count - 1)
            allocated[index] += volume
            continue
        distributed, last_overlap = Decimal(0), None
        for index in range(bin_count):
            overlap = min(high, boundaries[index + 1]) - max(low, boundaries[index])
            if overlap > 0:
                share = volume * overlap / (high - low)
                allocated[index] += share
                distributed += share
                last_overlap = index
        if last_overlap is not None:
            allocated[last_overlap] += volume - distributed
    bins = tuple(VolumeProfileBin(boundaries[i], boundaries[i + 1], allocated[i]) for i in range(bin_count))
    total_volume = sum((item.volume for item in bins), Decimal(0))
    poc_index = max(range(bin_count), key=lambda index: (bins[index].volume, -index))
    low_index = high_index = poc_index
    included, threshold = bins[poc_index].volume, total_volume * fraction
    while included < threshold and (low_index > 0 or high_index < bin_count - 1):
        below = bins[low_index - 1].volume if low_index > 0 else None
        above = bins[high_index + 1].volume if high_index < bin_count - 1 else None
        if below is not None and (above is None or below >= above):
            low_index -= 1; included += bins[low_index].volume
        else:
            high_index += 1; included += bins[high_index].volume
    gap_count = 0
    if step_seconds is not None:
        gap_count = sum((b.time - a.time).total_seconds() > step_seconds * 1.5 for a, b in zip(selected, selected[1:]))
    poc = (bins[poc_index].low + bins[poc_index].high) / Decimal(2)
    snapshot = VolumeProfileSnapshot(dataset_identity, request, selected[0].time, selected[-1].time,
        len(selected), volume_type, volume_source, profile_low, profile_high, total_volume, bins, poc,
        bins[high_index].high, bins[low_index].low, gap_count > 0, gap_count)
    return VolumeProfileResult(VolumeProfileEligibility.ELIGIBLE, "Eligible volume semantics", snapshot)
