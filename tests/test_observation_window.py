"""Observation readiness metrics stay factual, durable, and read-only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json
import sqlite3

from api import observation as observation_api
from api.observation import ObservationSummaryResponse, get_observation_summary
from monitoring import observation_window
from monitoring.observation_window import (
    ObservationCycle,
    read_observation_cycles,
    summarize_observations,
)


def test_fixed_observation_window_summary_and_execution_isolation() -> None:
    now = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

    def cycle(hours: int, conclusion: str, score: float, freshness: str) -> ObservationCycle:
        return ObservationCycle(
            timestamp=now - timedelta(hours=hours),
            symbol="XAUUSD",
            timeframe="M15",
            conclusion=conclusion,
            quality_score=score,
            data_freshness=freshness,
            regime="TREND_UP",
        )

    summary = summarize_observations(
        [
            cycle(30, "BUY", 99, "fresh"),  # outside the 24-hour window
            cycle(5, "NO_TRADE", 40, "fresh"),
            cycle(4, "BUY", 80, "fresh"),
            cycle(3, "NO_TRADE", 60, "stale"),
            cycle(2, "SELL", 90, "fresh"),
            cycle(1, "NO_TRADE", 70, "fresh"),
        ],
        lookback_hours=24,
        quality_threshold=70,
        now=now,
    )

    assert summary == {
        "lookback_hours": 24,
        "quality_threshold": 70,
        "total_cycles": 5,
        "no_trade_count": 3,
        "actionable_count": 2,
        "quality_count": 5,
        "quality_min": 40,
        "quality_max": 90,
        "quality_median": 70,
        "quality_at_or_above_threshold": 3,
        "longest_fresh_streak": 2,
        "current_fresh_streak": 2,
        "first_cycle_at": (now - timedelta(hours=5)).isoformat(),
        "most_recent_cycle_at": (now - timedelta(hours=1)).isoformat(),
    }

    source = inspect.getsource(observation_window)
    assert "broker_execution_enabled" not in source
    assert "order_send" not in source
    assert "submit_order" not in source
    assert "mode=ro" in source


def test_existing_evidence_schema_is_read_without_mutation(tmp_path) -> None:
    path = tmp_path / "campaign.evidence.sqlite3"
    payload = {
        "event_id": "signal-1",
        "event_type": "SIGNAL",
        "candidate_id": None,
        "occurred_at": "2026-09-14T10:00:00+00:00",
        "facts": {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "conclusion": "BUY",
            "quality_score": 82,
            "data_freshness": "fresh",
            "regime": "TREND_UP",
        },
    }
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE evidence(session_id TEXT, event_id TEXT, payload TEXT)"
    )
    connection.execute(
        "INSERT INTO evidence VALUES(?,?,?)", ("session", "signal-1", json.dumps(payload))
    )
    connection.commit()
    connection.close()
    before = path.read_bytes()

    cycles = read_observation_cycles([path])

    assert len(cycles) == 1
    assert cycles[0].conclusion == "BUY"
    assert cycles[0].quality_score == 82
    assert path.read_bytes() == before


def test_observation_summary_endpoint_is_a_thin_read_only_view(monkeypatch) -> None:
    expected = ObservationSummaryResponse(
        lookback_hours=24,
        quality_threshold=70,
        total_cycles=0,
        no_trade_count=0,
        actionable_count=0,
        quality_count=0,
        quality_at_or_above_threshold=0,
        longest_fresh_streak=0,
        current_fresh_streak=0,
    )

    monkeypatch.setattr(observation_api, "discover_live_evidence", lambda: ())
    actual = get_observation_summary(lookback_hours=24, quality_threshold=70)
    assert actual == expected
    source = inspect.getsource(get_observation_summary)
    assert "execution" not in source
