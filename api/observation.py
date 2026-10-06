"""Read-only observation-window API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from core.processes import is_process_alive
from monitoring.execution_heartbeat import read_execution_heartbeat
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from broker.types import TIMEFRAME_SECONDS, Timeframe
from config.settings import settings
from execution.safety import SQLiteExecutionSafetyStore
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


class ObservationComponentResponse(BaseModel):
    name: str
    running: bool
    healthy: bool
    updated_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    pid: int | None = None
    source: str
    mode: str | None = None


class ObservationHealthResponse(BaseModel):
    execution_supervisor: dict | None = None
    running: bool
    healthy: bool
    updated_at: str
    last_success_at: str | None
    last_error: str | None
    cycles_completed: int
    session_id: str
    source: str = "WELTRADE_SUPERVISOR_EXECUTION_SAFETY+PAINX_FORWARD_PROGRESS"
    supervisor: ObservationComponentResponse
    forward_collector: ObservationComponentResponse


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
    """Read live Weltrade execution and PainX collector heartbeats only.

    The old observation-daemon evidence database is intentionally not part of
    this health projection.  Its September heartbeat can remain useful for
    historical analysis, but it must not determine current dashboard health.
    The five-minute execution loop and the existing stale-cycle setting define
    this monitoring freshness window; this does not alter any trading rule.
    """
    now = datetime.now(timezone.utc)
    maximum_age = timedelta(seconds=300 * settings.observation_heartbeat_stale_cycles)

    def _timestamp(value: object) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _fresh(timestamp: datetime | None) -> bool:
        return timestamp is not None and now - timestamp <= maximum_age

    supervisor = ObservationComponentResponse(
        name="Weltrade execution supervisor",
        running=False,
        healthy=False,
        last_error="HEARTBEAT_NOT_OBSERVED",
        source="execution_safety.sqlite3 (published by the live Weltrade loop)",
    )
    safety_path = Path(
        getattr(settings, "execution_safety_store_path", "state/execution_safety.sqlite3")
    )
    try:
        snapshot = SQLiteExecutionSafetyStore(safety_path, initialize=False).read()
        if snapshot is not None:
            observed_at = snapshot.observed_at.astimezone(timezone.utc)
            fresh = _fresh(observed_at)
            broker_matches = snapshot.broker.strip().lower() == "weltrade"
            supervisor = ObservationComponentResponse(
                name="Weltrade execution supervisor",
                running=fresh and broker_matches,
                healthy=fresh and broker_matches,
                updated_at=observed_at.isoformat(),
                last_success_at=observed_at.isoformat() if fresh and broker_matches else None,
                last_error=None if broker_matches else "BROKER_CONTEXT_MISMATCH",
                source="execution_safety.sqlite3 (published by the live Weltrade loop)",
                mode=snapshot.execution_mode.value,
            )
    except Exception as exc:
        supervisor = ObservationComponentResponse(
            name="Weltrade execution supervisor",
            running=False,
            healthy=False,
            last_error=type(exc).__name__,
            source="execution_safety.sqlite3 (published by the live Weltrade loop)",
        )

    collector_path = Path(
        getattr(settings, "painx_forward_progress_path", "state/painx1200_forward/progress.json")
    )
    collector = ObservationComponentResponse(
        name="PainX forward collector",
        running=False,
        healthy=False,
        last_error="PROGRESS_NOT_OBSERVED",
        source=str(collector_path),
        mode="READ_ONLY_FORWARD_SHADOW",
    )
    try:
        payload = json.loads(collector_path.read_text(encoding="utf-8"))
        updated_at = _timestamp(payload.get("updated_at"))
        fresh = _fresh(updated_at)
        pid = payload.get("pid")
        pid_value = int(pid) if pid is not None else None
        pid_alive = is_process_alive(pid_value) if pid_value is not None else False
        error = payload.get("error") or None
        execution_enabled = payload.get("execution_enabled")
        collector = ObservationComponentResponse(
            name="PainX forward collector",
            running=fresh and pid_alive,
            healthy=fresh and pid_alive and execution_enabled is False and error is None,
            updated_at=updated_at.isoformat() if updated_at else None,
            last_success_at=updated_at.isoformat()
            if fresh and pid_alive and execution_enabled is False and error is None
            else None,
            last_error=str(error) if error else ("STALE_HEARTBEAT" if not fresh else None),
            pid=pid_value,
            source=str(collector_path),
            mode=str(payload.get("mode") or "READ_ONLY_FORWARD_SHADOW"),
        )
    except FileNotFoundError:
        pass
    except Exception as exc:
        collector = ObservationComponentResponse(
            name="PainX forward collector",
            running=False,
            healthy=False,
            last_error=type(exc).__name__,
            source=str(collector_path),
            mode="READ_ONLY_FORWARD_SHADOW",
        )

    component_times = [
        _timestamp(supervisor.updated_at),
        _timestamp(collector.updated_at),
    ]
    latest = max((item for item in component_times if item is not None), default=now)
    errors = [
        f"supervisor:{supervisor.last_error}" if supervisor.last_error else None,
        f"forward_collector:{collector.last_error}" if collector.last_error else None,
    ]
    all_healthy = supervisor.healthy and collector.healthy
    return ObservationHealthResponse(
        execution_supervisor=read_execution_heartbeat(
            'state/weltrade_execution_supervisor_heartbeat.json',
            max_age_seconds=maximum_age.total_seconds()),
        running=supervisor.running and collector.running,
        healthy=all_healthy,
        updated_at=latest.isoformat(),
        last_success_at=latest.isoformat() if all_healthy else None,
        last_error="; ".join(error for error in errors if error) or None,
        cycles_completed=0,
        session_id="weltrade-supervisor+painx-forward",
        supervisor=supervisor,
        forward_collector=collector,
    )
