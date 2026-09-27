"""Focused, storage-only checks for the observation health route."""

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import json
import os

import api.observation as observation
import pytest
from broker.types import TIMEFRAME_SECONDS
from monitoring.observation_daemon import parse_watch_list
from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    SQLiteExecutionSafetyStore,
)


def _settings(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        observation_symbols="FX Vol 20:M1,SFX Vol 99:M5",
        observation_heartbeat_stale_cycles=2,
        observation_evidence_path=str(path),
        execution_safety_store_path=path.parent / "execution_safety.sqlite3",
        painx_forward_progress_path=path.parent / "painx" / "progress.json",
    )


def test_health_missing_store_preserves_response_and_creates_nothing(tmp_path, monkeypatch):
    missing = tmp_path / "missing" / "heartbeat.sqlite3"
    monkeypatch.setattr(observation, "settings", _settings(missing))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A gateway or write-capable watchlist store was constructed")

    monkeypatch.setattr("broker.factory.get_gateway", forbidden)
    monkeypatch.setattr("data.watchlist.WatchlistStore", forbidden)
    result = observation.get_observation_health()

    assert result.source == "WELTRADE_SUPERVISOR_EXECUTION_SAFETY+PAINX_FORWARD_PROGRESS"
    assert result.running is False
    assert result.healthy is False
    assert "HEARTBEAT_NOT_OBSERVED" in result.last_error
    assert result.supervisor.running is False
    assert result.forward_collector.running is False
    assert not missing.parent.exists()


def test_health_uses_live_supervisor_and_forward_progress_not_legacy_db(tmp_path, monkeypatch):
    legacy = tmp_path / "heartbeat.sqlite3"
    configured = _settings(legacy)
    monkeypatch.setattr(observation, "settings", configured)

    observed_at = datetime.now(timezone.utc)
    SQLiteExecutionSafetyStore(configured.execution_safety_store_path, initialize=True).publish(
        ExecutionSafetySnapshot(
            observed_at=observed_at,
            emergency_stop_state=EmergencyStopState.CLEAR,
            execution_mode=ExecutionMode.DURABLE,
            broker="weltrade",
            environment="development",
            durable_executor_enabled=True,
            daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
            unresolved_intent_count=0,
            unresolved_intent_blocked=False,
            execution_authorization=ExecutionAuthorization.AUTHORIZED,
            reason_codes=("AUTHORIZED",),
        )
    )
    configured.painx_forward_progress_path.parent.mkdir(parents=True)
    configured.painx_forward_progress_path.write_text(json.dumps({
        "pid": os.getpid(),
        "updated_at": observed_at.isoformat(),
        "execution_enabled": False,
        "fresh_closed_bar_received": True,
        "mode": "READ_ONLY_FORWARD_SHADOW",
        "error": None,
    }), encoding="utf-8")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy observation-daemon DB must not feed current health")

    monkeypatch.setattr(observation, "read_observation_health", forbidden)
    result = observation.get_observation_health()

    assert result.running is True
    assert result.healthy is True
    assert result.supervisor.healthy is True
    assert result.forward_collector.healthy is True
    assert result.forward_collector.pid == os.getpid()
    assert not legacy.exists()


@pytest.mark.parametrize("value", [
    "FX Vol 20:M1,SFX Vol 99:M5",
    " r_75:h1 , R_75:H1, XAUUSD:M15 ",
])
def test_read_only_watch_parser_matches_daemon_parser(value):
    expected = tuple(TIMEFRAME_SECONDS[pair.timeframe] for pair in parse_watch_list(value))
    assert observation._parse_observation_intervals(value) == expected


@pytest.mark.parametrize("value", ["", "R_75", ":H1", "R_75:INVALID"])
def test_read_only_watch_parser_rejects_every_daemon_malformed_input(value):
    with pytest.raises((ValueError, KeyError)) as daemon_error:
        parse_watch_list(value)
    with pytest.raises(type(daemon_error.value)):
        observation._parse_observation_intervals(value)
