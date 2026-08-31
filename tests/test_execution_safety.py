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
    RiskAuthorizationSnapshot,
    RiskEvaluationState,
    SQLiteExecutionSafetyStore,
)


def _risk_snapshot() -> RiskAuthorizationSnapshot:
    return RiskAuthorizationSnapshot(
        observed_at=datetime(2026, 8, 30, 12, tzinfo=timezone.utc),
        broker="simulation", environment="development",
        account_id="SIMULATED",
        evaluation_state=RiskEvaluationState.AUTHORIZED,
        balance=100.0, equity=101.0, currency="USD",
        max_daily_loss=3.0, max_trades_daily=5,
        daily_trades_count=1, daily_loss_percent=0.25,
        risk_allowed=True, risk_message="Limits OK", rejection_reason="",
        authorized_risk_amount=0.5, authorized_risk_percent=0.5,
        execution_quantity_available=True, execution_quantity_value=0.5,
        execution_quantity_unit="SIMULATION_UNITS",
        execution_quantity_reason="Simulation risk verified",
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


def test_risk_authorization_snapshot_round_trip_uses_existing_store(tmp_path) -> None:
    path = tmp_path / "safety.sqlite3"
    writer = SQLiteExecutionSafetyStore(path, initialize=True)
    snapshot = _risk_snapshot()
    writer.publish_risk(snapshot)
    reader = SQLiteExecutionSafetyStore(path, initialize=False)
    assert reader.read_risk() == snapshot
    assert reader.read_risk().observed_at.utcoffset().total_seconds() == 0


def test_unknown_future_risk_schema_version_fails_closed_on_persisted_read(tmp_path) -> None:
    path = tmp_path / "safety.sqlite3"
    store = SQLiteExecutionSafetyStore(path, initialize=True)
    store.publish_risk(_risk_snapshot())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE risk_authorization_snapshot SET schema_version=99"
        )
    with pytest.raises(ValueError, match="Malformed|Unsupported"):
        store.read_risk()


def test_risk_snapshot_rejects_naive_time_and_quantity_invariant() -> None:
    values = {
        field: getattr(_risk_snapshot(), field)
        for field in _risk_snapshot().__dataclass_fields__
        if field != "schema_version"
    }
    with pytest.raises(ValueError, match="timezone-aware"):
        RiskAuthorizationSnapshot(**{**values, "observed_at": datetime(2026, 8, 30)})
    with pytest.raises(ValueError, match="Unavailable execution quantity"):
        RiskAuthorizationSnapshot(**{
            **values,
            "execution_quantity_available": False,
        })
    with pytest.raises(ValueError, match="account_id"):
        RiskAuthorizationSnapshot(**{**values, "account_id": " "})


def test_legacy_risk_table_migrates_additively_but_record_fails_closed(tmp_path) -> None:
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE risk_authorization_snapshot (
                singleton_id INTEGER PRIMARY KEY, schema_version INTEGER NOT NULL,
                observed_at TEXT NOT NULL, broker TEXT NOT NULL,
                environment TEXT NOT NULL, evaluation_state TEXT NOT NULL,
                balance REAL, equity REAL, currency TEXT, max_daily_loss REAL,
                max_trades_daily INTEGER, daily_trades_count INTEGER,
                daily_loss_percent REAL, risk_allowed INTEGER,
                risk_message TEXT NOT NULL, rejection_reason TEXT NOT NULL,
                authorized_risk_amount REAL, authorized_risk_percent REAL,
                execution_quantity_available INTEGER NOT NULL,
                execution_quantity_value REAL, execution_quantity_unit TEXT,
                execution_quantity_reason TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO risk_authorization_snapshot VALUES
            (1,1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(), "simulation", "development",
                "AUTHORIZED", 100.0, 100.0, "USD", 3.0, 5, 0, 0.0, 1,
                "Limits OK", "", 0.5, 0.5, 1, 0.5, "SIMULATION_UNITS", "verified",
            ),
        )
    store = SQLiteExecutionSafetyStore(path, initialize=True)
    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(risk_authorization_snapshot)"
            )
        }
    assert "account_id" in columns
    with pytest.raises(ValueError, match="Malformed|Unsupported"):
        store.read_risk()


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
