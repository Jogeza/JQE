"""Focused, storage-only checks for the observation health route."""

from pathlib import Path
from types import SimpleNamespace

import api.observation as observation
import pytest
from broker.types import TIMEFRAME_SECONDS
from monitoring.observation_daemon import parse_watch_list


def _settings(path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        observation_symbols="FX Vol 20:M1,SFX Vol 99:M5",
        observation_heartbeat_stale_cycles=2,
        observation_evidence_path=str(path),
    )


def test_health_missing_store_preserves_response_and_creates_nothing(tmp_path, monkeypatch):
    missing = tmp_path / "missing" / "heartbeat.sqlite3"
    monkeypatch.setattr(observation, "settings", _settings(missing))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("A gateway or write-capable watchlist store was constructed")

    monkeypatch.setattr("broker.factory.get_gateway", forbidden)
    monkeypatch.setattr("data.watchlist.WatchlistStore", forbidden)
    result = observation.get_observation_health()

    assert result.model_dump().keys() == {
        "running", "healthy", "updated_at", "last_success_at", "last_error",
        "cycles_completed", "session_id",
    }
    assert result.running is False
    assert result.healthy is False
    assert result.last_error == "NOT_STARTED"
    assert not missing.parent.exists()


def test_health_uses_only_settings_needed_for_read_only_threshold(tmp_path, monkeypatch):
    missing = tmp_path / "heartbeat.sqlite3"
    monkeypatch.setattr(observation, "settings", _settings(missing))
    recorded = {}

    def read(path, *, now, maximum_age):
        recorded.update(path=path, now=now, maximum_age=maximum_age)
        return {
            "running": False, "healthy": False, "updated_at": now.isoformat(),
            "last_success_at": None, "last_error": "NOT_STARTED",
            "cycles_completed": 0, "session_id": "",
        }

    monkeypatch.setattr(observation, "read_observation_health", read)
    result = observation.get_observation_health()
    assert result.running is False
    assert recorded["path"] == missing
    assert recorded["maximum_age"].total_seconds() == 600
    assert not missing.exists()


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
