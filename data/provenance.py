"""Typed historical dataset provenance; never infer volume semantics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class VolumeType(str, Enum):
    REAL_VOLUME = "REAL_VOLUME"
    TICK_VOLUME = "TICK_VOLUME"
    BROKER_VOLUME = "BROKER_VOLUME"
    SIMULATED_VOLUME = "SIMULATED_VOLUME"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DatasetProvenance:
    provider: str
    symbol: str
    timeframe: str
    source: str
    provider_symbol: str
    volume_type: VolumeType
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class CachedDatasetSummary:
    provider: str
    canonical_symbol: str
    provider_symbol: str
    timeframe: str
    start: datetime
    end: datetime
    candle_count: int
    dataset_identity: str
    volume_type: VolumeType
    volume_source: str
    gap_count: int
