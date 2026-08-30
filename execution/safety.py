"""Cross-process, broker-neutral execution-safety observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import sqlite3


SCHEMA_VERSION = 1


class EmergencyStopState(str, Enum):
    CLEAR = "CLEAR"
    ACTIVE = "ACTIVE"
    UNKNOWN = "UNKNOWN"


class ObservationState(str, Enum):
    OBSERVED = "OBSERVED"
    NOT_OBSERVED = "NOT_OBSERVED"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


class ExecutionMode(str, Enum):
    DURABLE = "DURABLE"


class DailyStateAuthority(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    NOT_AUTHORITATIVE = "NOT_AUTHORITATIVE"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


class ExecutionAuthorization(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionSafetySnapshot:
    observed_at: datetime
    emergency_stop_state: EmergencyStopState
    execution_mode: ExecutionMode
    broker: str
    environment: str
    durable_executor_enabled: bool
    daily_state_authority: DailyStateAuthority
    unresolved_intent_count: int
    unresolved_intent_blocked: bool
    execution_authorization: ExecutionAuthorization
    reason_codes: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported execution-safety schema version")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Execution-safety observed_at must be timezone-aware")
        if not self.broker.strip() or not self.environment.strip():
            raise ValueError("Execution-safety broker and environment are required")
        if self.unresolved_intent_count < 0:
            raise ValueError("Unresolved intent count cannot be negative")
        if any(not isinstance(code, str) or not code.strip() for code in self.reason_codes):
            raise ValueError("Execution-safety reason codes must be nonblank strings")


class SQLiteExecutionSafetyStore:
    """Single-writer/latest-observation SQLite store; reads never initialize it."""

    def __init__(self, path: str | Path, *, initialize: bool) -> None:
        resolved = Path(path).expanduser().resolve()
        self._path = resolved
        if initialize:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(f"file:{self._path.as_posix()}?mode=ro", uri=True, timeout=1.0)
        else:
            connection = sqlite3.connect(str(self._path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=1000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS execution_safety_snapshot (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    schema_version INTEGER NOT NULL, observed_at TEXT NOT NULL,
                    emergency_stop_state TEXT NOT NULL, execution_mode TEXT NOT NULL,
                    broker TEXT NOT NULL, environment TEXT NOT NULL,
                    durable_executor_enabled INTEGER NOT NULL,
                    daily_state_authority TEXT NOT NULL,
                    unresolved_intent_count INTEGER NOT NULL,
                    unresolved_intent_blocked INTEGER NOT NULL,
                    execution_authorization TEXT NOT NULL,
                    reason_codes TEXT NOT NULL
                )"""
            )

    def publish(self, snapshot: ExecutionSafetySnapshot) -> None:
        values = (
            snapshot.schema_version,
            snapshot.observed_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            snapshot.emergency_stop_state.value,
            snapshot.execution_mode.value,
            snapshot.broker,
            snapshot.environment,
            int(snapshot.durable_executor_enabled),
            snapshot.daily_state_authority.value,
            snapshot.unresolved_intent_count,
            int(snapshot.unresolved_intent_blocked),
            snapshot.execution_authorization.value,
            "\n".join(snapshot.reason_codes),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO execution_safety_snapshot VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                schema_version=excluded.schema_version, observed_at=excluded.observed_at,
                emergency_stop_state=excluded.emergency_stop_state, execution_mode=excluded.execution_mode,
                broker=excluded.broker, environment=excluded.environment,
                durable_executor_enabled=excluded.durable_executor_enabled,
                daily_state_authority=excluded.daily_state_authority,
                unresolved_intent_count=excluded.unresolved_intent_count,
                unresolved_intent_blocked=excluded.unresolved_intent_blocked,
                execution_authorization=excluded.execution_authorization,
                reason_codes=excluded.reason_codes""",
                values,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def read(self) -> ExecutionSafetySnapshot | None:
        if not self._path.is_file():
            return None
        with self._connect(read_only=True) as connection:
            row = connection.execute("SELECT * FROM execution_safety_snapshot WHERE singleton_id=1").fetchone()
        if row is None:
            return None
        try:
            observed_at = datetime.fromisoformat(row["observed_at"])
            return ExecutionSafetySnapshot(
                schema_version=int(row["schema_version"]), observed_at=observed_at,
                emergency_stop_state=EmergencyStopState(row["emergency_stop_state"]),
                execution_mode=ExecutionMode(row["execution_mode"]), broker=row["broker"],
                environment=row["environment"], durable_executor_enabled=bool(row["durable_executor_enabled"]),
                daily_state_authority=DailyStateAuthority(row["daily_state_authority"]),
                unresolved_intent_count=int(row["unresolved_intent_count"]),
                unresolved_intent_blocked=bool(row["unresolved_intent_blocked"]),
                execution_authorization=ExecutionAuthorization(row["execution_authorization"]),
                reason_codes=tuple(filter(None, row["reason_codes"].split("\n"))),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Malformed execution-safety snapshot") from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
