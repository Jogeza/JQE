"""Read-only observation-window summaries over existing campaign evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from statistics import median
from typing import Iterable, Mapping, Any


@dataclass(frozen=True, slots=True)
class ObservationCycle:
    timestamp: datetime
    symbol: str
    timeframe: str
    conclusion: str
    quality_score: float | None
    data_freshness: str
    regime: str | None = None


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_observation_cycles(paths: Iterable[Path]) -> tuple[ObservationCycle, ...]:
    """Read SIGNAL events without creating, migrating, or writing any database."""
    cycles: list[ObservationCycle] = []
    seen: set[tuple[str, str]] = set()
    for path in paths:
        resolved = Path(path).resolve()
        if not resolved.is_file():
            continue
        connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT session_id, event_id, payload FROM evidence ORDER BY rowid"
            ).fetchall()
        except sqlite3.Error:
            continue
        finally:
            connection.close()
        for session_id, event_id, raw_payload in rows:
            if (str(session_id), str(event_id)) in seen:
                continue
            seen.add((str(session_id), str(event_id)))
            try:
                payload = json.loads(raw_payload)
                facts = payload.get("facts", {})
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("event_type") != "SIGNAL" or not isinstance(facts, Mapping):
                continue
            timestamp = _parse_timestamp(facts.get("observed_at") or payload.get("occurred_at"))
            if timestamp is None:
                continue
            raw_score = facts.get("quality_score", facts.get("confidence"))
            try:
                score = float(raw_score) if raw_score is not None else None
            except (TypeError, ValueError):
                score = None
            cycles.append(ObservationCycle(
                timestamp=timestamp,
                symbol=str(facts.get("symbol", "UNKNOWN")),
                timeframe=str(facts.get("timeframe", "UNKNOWN")),
                conclusion=str(facts.get("conclusion", facts.get("direction", "NO_TRADE"))).upper(),
                quality_score=score,
                data_freshness=str(facts.get("data_freshness", "cached")).lower(),
                regime=str(facts["regime"]) if facts.get("regime") is not None else None,
            ))
    return tuple(sorted(cycles, key=lambda cycle: cycle.timestamp))


def summarize_observations(
    cycles: Iterable[ObservationCycle],
    *,
    lookback_hours: float,
    quality_threshold: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute factual readiness metrics; this function has no execution authority."""
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = observed_now - timedelta(hours=lookback_hours)
    window = sorted(
        (cycle for cycle in cycles if cutoff <= cycle.timestamp <= observed_now),
        key=lambda cycle: cycle.timestamp,
    )
    scores = sorted(cycle.quality_score for cycle in window if cycle.quality_score is not None)
    current_fresh = 0
    for cycle in reversed(window):
        if cycle.data_freshness != "fresh":
            break
        current_fresh += 1
    longest_fresh = 0
    run = 0
    for cycle in window:
        run = run + 1 if cycle.data_freshness == "fresh" else 0
        longest_fresh = max(longest_fresh, run)
    actionable = sum(cycle.conclusion in {"BUY", "SELL"} for cycle in window)
    return {
        "lookback_hours": lookback_hours,
        "quality_threshold": quality_threshold,
        "total_cycles": len(window),
        "no_trade_count": sum(cycle.conclusion == "NO_TRADE" for cycle in window),
        "actionable_count": actionable,
        "quality_count": len(scores),
        "quality_min": min(scores) if scores else None,
        "quality_max": max(scores) if scores else None,
        "quality_median": median(scores) if scores else None,
        "quality_at_or_above_threshold": sum(score >= quality_threshold for score in scores),
        "longest_fresh_streak": longest_fresh,
        "current_fresh_streak": current_fresh,
        "first_cycle_at": window[0].timestamp.isoformat() if window else None,
        "most_recent_cycle_at": window[-1].timestamp.isoformat() if window else None,
    }


def discover_live_evidence(root: Path = Path("state")) -> tuple[Path, ...]:
    """Find existing live-paper evidence stores without creating any path."""
    return tuple(sorted(root.glob("live_paper*/**/*.evidence.sqlite3")))


def read_observation_health(
    path: Path, *, now: datetime, maximum_age: timedelta
) -> dict[str, Any]:
    """Read daemon health without creating or modifying its evidence store."""
    resolved = Path(path).resolve()
    unavailable = {
        "running": False, "healthy": False, "updated_at": now.isoformat(),
        "last_success_at": None, "last_error": "NOT_STARTED",
        "cycles_completed": 0, "session_id": "",
    }
    if not resolved.is_file():
        return unavailable
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT payload FROM observation_heartbeat WHERE id=1"
        ).fetchone()
    except sqlite3.Error:
        return unavailable
    finally:
        connection.close()
    if not row:
        return unavailable
    payload = json.loads(row[0])
    updated_at = _parse_timestamp(payload.get("updated_at"))
    if updated_at is None or now - updated_at > maximum_age:
        payload.update(running=False, healthy=False, last_error="STALE_HEARTBEAT")
    return payload
