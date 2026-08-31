"""Cross-process, broker-neutral execution-safety observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import math
import sqlite3


SCHEMA_VERSION = 1
RISK_OBSERVATION_SCHEMA_VERSION = 2


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


class RiskEvaluationState(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    BLOCKED = "BLOCKED"
    NOT_EVALUATED = "NOT_EVALUATED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class RiskAuthorizationSnapshot:
    """Latest broker-neutral risk result produced by the durable cycle."""

    observed_at: datetime
    broker: str
    environment: str
    account_id: str | None
    evaluation_state: RiskEvaluationState
    balance: float | None
    equity: float | None
    currency: str | None
    max_daily_loss: float | None
    max_trades_daily: int | None
    daily_trades_count: int | None
    daily_loss_percent: float | None
    risk_allowed: bool | None
    risk_message: str
    rejection_reason: str
    authorized_risk_amount: float | None
    authorized_risk_percent: float | None
    execution_quantity_available: bool
    execution_quantity_value: float | None
    execution_quantity_unit: str | None
    execution_quantity_reason: str
    schema_version: int = RISK_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RISK_OBSERVATION_SCHEMA_VERSION:
            raise ValueError("Unsupported risk-observation schema version")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("Risk-observation observed_at must be timezone-aware")
        if not self.broker.strip() or not self.environment.strip():
            raise ValueError("Risk-observation broker and environment are required")
        if self.account_id is not None and not self.account_id.strip():
            raise ValueError("Risk-observation account_id must be nonblank when present")
        if (
            self.evaluation_state in (RiskEvaluationState.AUTHORIZED, RiskEvaluationState.BLOCKED)
            and self.account_id is None
        ):
            raise ValueError("Authoritative risk observations require account_id")
        numeric_values = (
            self.balance,
            self.equity,
            self.max_daily_loss,
            self.daily_loss_percent,
            self.authorized_risk_amount,
            self.authorized_risk_percent,
            self.execution_quantity_value,
        )
        if any(value is not None and not math.isfinite(value) for value in numeric_values):
            raise ValueError("Risk-observation numeric values must be finite")
        if self.max_trades_daily is not None and self.max_trades_daily < 0:
            raise ValueError("Maximum daily trades cannot be negative")
        if self.daily_trades_count is not None and self.daily_trades_count < 0:
            raise ValueError("Daily trade count cannot be negative")
        if self.evaluation_state is not RiskEvaluationState.AUTHORIZED:
            if self.authorized_risk_amount is not None or self.authorized_risk_percent is not None:
                raise ValueError("Only authorized risk observations may expose risk capital")
            if self.execution_quantity_available:
                raise ValueError("Blocked or unavailable risk cannot expose quantity")
        if self.execution_quantity_available:
            if (
                self.execution_quantity_value is None
                or self.execution_quantity_value <= 0
                or not self.execution_quantity_unit
            ):
                raise ValueError("Available execution quantity requires a positive typed value")
        elif self.execution_quantity_value is not None or self.execution_quantity_unit is not None:
            raise ValueError("Unavailable execution quantity cannot expose value or unit")


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
            connection.execute(
                """CREATE TABLE IF NOT EXISTS risk_authorization_snapshot (
                    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                    schema_version INTEGER NOT NULL, observed_at TEXT NOT NULL,
                    broker TEXT NOT NULL, environment TEXT NOT NULL,
                    account_id TEXT,
                    evaluation_state TEXT NOT NULL,
                    balance REAL, equity REAL, currency TEXT,
                    max_daily_loss REAL, max_trades_daily INTEGER,
                    daily_trades_count INTEGER, daily_loss_percent REAL,
                    risk_allowed INTEGER, risk_message TEXT NOT NULL,
                    rejection_reason TEXT NOT NULL,
                    authorized_risk_amount REAL, authorized_risk_percent REAL,
                    execution_quantity_available INTEGER NOT NULL,
                    execution_quantity_value REAL, execution_quantity_unit TEXT,
                    execution_quantity_reason TEXT NOT NULL
                )"""
            )
            risk_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(risk_authorization_snapshot)"
                )
            }
            if "account_id" not in risk_columns:
                connection.execute(
                    "ALTER TABLE risk_authorization_snapshot ADD COLUMN account_id TEXT"
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

    def publish_risk(self, snapshot: RiskAuthorizationSnapshot) -> None:
        values = (
            snapshot.schema_version,
            snapshot.observed_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            snapshot.broker,
            snapshot.environment,
            snapshot.account_id,
            snapshot.evaluation_state.value,
            snapshot.balance,
            snapshot.equity,
            snapshot.currency,
            snapshot.max_daily_loss,
            snapshot.max_trades_daily,
            snapshot.daily_trades_count,
            snapshot.daily_loss_percent,
            None if snapshot.risk_allowed is None else int(snapshot.risk_allowed),
            snapshot.risk_message,
            snapshot.rejection_reason,
            snapshot.authorized_risk_amount,
            snapshot.authorized_risk_percent,
            int(snapshot.execution_quantity_available),
            snapshot.execution_quantity_value,
            snapshot.execution_quantity_unit,
            snapshot.execution_quantity_reason,
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO risk_authorization_snapshot (
                    singleton_id, schema_version, observed_at, broker, environment,
                    account_id, evaluation_state, balance, equity, currency,
                    max_daily_loss, max_trades_daily, daily_trades_count,
                    daily_loss_percent, risk_allowed, risk_message, rejection_reason,
                    authorized_risk_amount, authorized_risk_percent,
                    execution_quantity_available, execution_quantity_value,
                    execution_quantity_unit, execution_quantity_reason
                ) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                schema_version=excluded.schema_version, observed_at=excluded.observed_at,
                broker=excluded.broker, environment=excluded.environment,
                account_id=excluded.account_id,
                evaluation_state=excluded.evaluation_state, balance=excluded.balance,
                equity=excluded.equity, currency=excluded.currency,
                max_daily_loss=excluded.max_daily_loss,
                max_trades_daily=excluded.max_trades_daily,
                daily_trades_count=excluded.daily_trades_count,
                daily_loss_percent=excluded.daily_loss_percent,
                risk_allowed=excluded.risk_allowed, risk_message=excluded.risk_message,
                rejection_reason=excluded.rejection_reason,
                authorized_risk_amount=excluded.authorized_risk_amount,
                authorized_risk_percent=excluded.authorized_risk_percent,
                execution_quantity_available=excluded.execution_quantity_available,
                execution_quantity_value=excluded.execution_quantity_value,
                execution_quantity_unit=excluded.execution_quantity_unit,
                execution_quantity_reason=excluded.execution_quantity_reason""",
                values,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def read_risk(self) -> RiskAuthorizationSnapshot | None:
        if not self._path.is_file():
            return None
        with self._connect(read_only=True) as connection:
            row = connection.execute(
                "SELECT * FROM risk_authorization_snapshot WHERE singleton_id=1"
            ).fetchone()
        if row is None:
            return None
        try:
            return RiskAuthorizationSnapshot(
                schema_version=int(row["schema_version"]),
                observed_at=datetime.fromisoformat(row["observed_at"]),
                broker=row["broker"],
                environment=row["environment"],
                account_id=row["account_id"],
                evaluation_state=RiskEvaluationState(row["evaluation_state"]),
                balance=None if row["balance"] is None else float(row["balance"]),
                equity=None if row["equity"] is None else float(row["equity"]),
                currency=row["currency"],
                max_daily_loss=None if row["max_daily_loss"] is None else float(row["max_daily_loss"]),
                max_trades_daily=None if row["max_trades_daily"] is None else int(row["max_trades_daily"]),
                daily_trades_count=None if row["daily_trades_count"] is None else int(row["daily_trades_count"]),
                daily_loss_percent=None if row["daily_loss_percent"] is None else float(row["daily_loss_percent"]),
                risk_allowed=None if row["risk_allowed"] is None else bool(row["risk_allowed"]),
                risk_message=row["risk_message"], rejection_reason=row["rejection_reason"],
                authorized_risk_amount=None if row["authorized_risk_amount"] is None else float(row["authorized_risk_amount"]),
                authorized_risk_percent=None if row["authorized_risk_percent"] is None else float(row["authorized_risk_percent"]),
                execution_quantity_available=bool(row["execution_quantity_available"]),
                execution_quantity_value=None if row["execution_quantity_value"] is None else float(row["execution_quantity_value"]),
                execution_quantity_unit=row["execution_quantity_unit"],
                execution_quantity_reason=row["execution_quantity_reason"],
            )
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, sqlite3.DatabaseError) as exc:
            raise ValueError("Malformed risk-authorization snapshot") from exc


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
