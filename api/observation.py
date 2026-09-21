"""Read-only observation-window API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from broker.types import TIMEFRAME_SECONDS, Timeframe
from config.settings import settings
from monitoring.observation_window import (
    discover_live_evidence,
    read_observation_cycles,
    read_observation_health,
    summarize_observations,
)


class ObservationSummaryResponse(BaseModel):
    lookback_hours: float
    quality_threshold: float
    total_cycles: int
    no_trade_count: int
    actionable_count: int
    quality_count: int
    quality_min: float | None = None
    quality_max: float | None = None
    quality_median: float | None = None
    quality_at_or_above_threshold: int
    longest_fresh_streak: int
    current_fresh_streak: int
    first_cycle_at: str | None = None
    most_recent_cycle_at: str | None = None


class ObservationHealthResponse(BaseModel):
    running: bool
    healthy: bool
    updated_at: str
    last_success_at: str | None
    last_error: str | None
    cycles_completed: int
    session_id: str


router = APIRouter(prefix="/api/v1/observation", tags=["observation"])


def _parse_observation_intervals(value: str) -> tuple[int, ...]:
    """Parse watch settings without constructing daemon or storage objects."""
    intervals: list[int] = []
    seen: set[str] = set()
    for item in value.split(","):
        parts = item.strip().rsplit(":", 1)
        if len(parts) != 2 or not parts[0].strip():
            raise ValueError("Observation symbols must use SYMBOL:TIMEFRAME pairs")
        symbol = parts[0].strip().upper()
        timeframe = Timeframe(parts[1].strip().upper())
        scope = f"{symbol}:{timeframe.value}"
        if scope not in seen:
            intervals.append(TIMEFRAME_SECONDS[timeframe])
            seen.add(scope)
    if not intervals:
        raise ValueError("At least one observation symbol is required")
    return tuple(intervals)


@router.get("/summary", response_model=ObservationSummaryResponse)
def get_observation_summary(
    lookback_hours: float = Query(default=168.0, gt=0, le=8760),
    quality_threshold: float = Query(default=70.0, ge=0, le=100),
) -> ObservationSummaryResponse:
    result = summarize_observations(
        read_observation_cycles(discover_live_evidence()),
        lookback_hours=lookback_hours,
        quality_threshold=quality_threshold,
    )
    return ObservationSummaryResponse(**result)


@router.get("/health", response_model=ObservationHealthResponse)
def get_observation_health() -> ObservationHealthResponse:
    intervals = _parse_observation_intervals(settings.observation_symbols)
    heartbeat = read_observation_health(
        Path(settings.observation_evidence_path),
        now=datetime.now(timezone.utc),
        maximum_age=timedelta(seconds=max(intervals) * settings.observation_heartbeat_stale_cycles),
    )
    return ObservationHealthResponse(**heartbeat)
