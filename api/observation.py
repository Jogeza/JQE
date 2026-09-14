"""Read-only observation-window API."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from monitoring.observation_window import (
    discover_live_evidence,
    read_observation_cycles,
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
