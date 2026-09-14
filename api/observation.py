"""Read-only observation-window API."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from broker.types import TIMEFRAME_SECONDS
from config.settings import settings
from monitoring.observation_window import (
    discover_live_evidence,
    read_observation_cycles,
    read_observation_health,
    summarize_observations,
)
from monitoring.observation_daemon import DaemonConfig


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
    config = DaemonConfig.from_settings(settings)
    longest_interval = max(TIMEFRAME_SECONDS[pair.timeframe] for pair in config.watches)
    heartbeat = read_observation_health(
        config.evidence_path,
        now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        maximum_age=__import__("datetime").timedelta(
            seconds=longest_interval * config.heartbeat_stale_cycles
        ),
    )
    return ObservationHealthResponse(**heartbeat)
