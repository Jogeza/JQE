"""Cross-process execution-safety snapshot persistence tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

import pytest

from execution.safety import (
    DailyStateAuthority,
    EmergencyStopState,
    ExecutionAuthorization,
    ExecutionMode,
    ExecutionSafetySnapshot,
    SQLiteExecutionSafetyStore,
)


def _snapshot(index: int = 0, *, authorization=ExecutionAuthorization.AUTHORIZED):
    return ExecutionSafetySnapshot(
        schema_version=1,
        observed_at=datetime(2026, 8, 30, 12, 0, index, tzinfo=timezone.utc),
        emergency_stop_state=EmergencyStopState.CLEAR,
        execution_mode=ExecutionMode.DURABLE,
        broker="simulation",
        environment="development",
        durable_executor_enabled=True,
        daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
        unresolved_intent_count=0,
        unresolved_intent_blocked=False,
        execution_authorization=authorization,
        reason_codes=(authorization.value,),
    )


def test_reader_missing_database_does_not_create_it(tmp_path) -> None:
    path = tmp_path / "missing.sqlite3"
    assert SQLiteExecutionSafetyStore(path, initialize=False).read() is None
    assert path.exists() is False


def test_atomic_latest_snapshot_round_trip_is_utc_and_read_only(tmp_path) -> None:
    path = tmp_path / "safety.sqlite3"
    writer = SQLiteExecutionSafetyStore(path, initialize=True)
    first, latest = _snapshot(), _snapshot(1, authorization=ExecutionAuthorization.BLOCKED)
    writer.publish(first)
    writer.publish(latest)
    reader = SQLiteExecutionSafetyStore(path, initialize=False)
    assert reader.read() == latest
    assert reader.read() == latest
    assert reader.read().observed_at.utcoffset().total_seconds() == 0
    assert reader.read().schema_version == 1


@pytest.mark.parametrize(
    ("column", "value"),
    [("emergency_stop_state", "BROKEN"), ("observed_at", "not-a-time"), ("schema_version", 99)],
)
def test_malformed_persisted_snapshot_fails_closed(tmp_path, column, value) -> None:
    path = tmp_path / "safety.sqlite3"
    store = SQLiteExecutionSafetyStore(path, initialize=True)
    store.publish(_snapshot())
    with sqlite3.connect(path) as connection:
        connection.execute(f"UPDATE execution_safety_snapshot SET {column}=?", (value,))
    with pytest.raises(ValueError, match="Malformed|Unsupported"):
        store.read()


def test_concurrent_reader_and_writer_are_safe(tmp_path) -> None:
    path = tmp_path / "safety.sqlite3"
    store = SQLiteExecutionSafetyStore(path, initialize=True)
    store.publish(_snapshot())
    def operation(index: int):
        if index % 2:
            store.publish(_snapshot(index))
            return None
        return store.read()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(operation, range(20)))
    assert all(result is None or isinstance(result, ExecutionSafetySnapshot) for result in results)
