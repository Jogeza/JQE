"""Durable, broker-agnostic intent persistence backed by SQLite."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import sqlite3
from pathlib import Path

from execution.models import (
    ClaimState,
    ExecutionReservation,
    IntentRecord,
    IntentRecordStatus,
    ReservationState,
)


@dataclass(frozen=True, slots=True)
class IntentRecordInspection:
    idempotency_key: str
    status: IntentRecordStatus
    order_id: str | None
    transaction_id: str | None
    created_at: str
    updated_at: str


_ALLOWED_TRANSITIONS: dict[IntentRecordStatus, frozenset[IntentRecordStatus]] = {
    IntentRecordStatus.PENDING: frozenset({IntentRecordStatus.ACCEPTED, IntentRecordStatus.REJECTED, IntentRecordStatus.UNKNOWN}),
    IntentRecordStatus.UNKNOWN: frozenset({IntentRecordStatus.ACCEPTED, IntentRecordStatus.REJECTED, IntentRecordStatus.UNKNOWN}),
    IntentRecordStatus.ACCEPTED: frozenset({IntentRecordStatus.ACCEPTED}),
    IntentRecordStatus.REJECTED: frozenset({IntentRecordStatus.REJECTED}),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class SQLiteIntentRecordStore:
    """SQLite implementation of the durable ``IntentRecordStore`` contract.

    Each operation uses a short-lived connection and a write transaction. The
    primary-key constraint and ``BEGIN IMMEDIATE`` make claims atomic across
    threads and processes sharing the database file.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        recovery_mode: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(resolved)
        self.recovery_mode = recovery_mode
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS intent_records (
                    idempotency_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    order_id TEXT,
                    transaction_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(intent_records)")}
            if "transaction_id" not in columns:
                connection.execute("ALTER TABLE intent_records ADD COLUMN transaction_id TEXT")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_reservations (
                    scope TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Idempotency key must be a nonblank string")

    @staticmethod
    def _decode(row: sqlite3.Row) -> IntentRecord:
        try:
            return IntentRecord(
                idempotency_key=row["idempotency_key"],
                status=IntentRecordStatus(row["state"]),
                order_id=row["order_id"],
                transaction_id=row["transaction_id"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Malformed persisted intent record") from exc

    @staticmethod
    def _validate_reservation_identity(scope: str, owner_id: str) -> None:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("Reservation scope must be a nonblank string")
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("Reservation owner must be a nonblank string")

    @staticmethod
    def _decode_reservation(row: sqlite3.Row) -> ExecutionReservation:
        try:
            acquired_at = datetime.fromisoformat(row["acquired_at"])
            expires_at = datetime.fromisoformat(row["expires_at"])
            reservation = ExecutionReservation(
                scope=row["scope"],
                owner_id=row["owner_id"],
                acquired_at=acquired_at,
                expires_at=expires_at,
            )
            if (
                not reservation.scope.strip()
                or not reservation.owner_id.strip()
                or acquired_at.tzinfo is None
                or acquired_at.utcoffset() is None
                or expires_at.tzinfo is None
                or expires_at.utcoffset() is None
                or expires_at <= acquired_at
            ):
                raise ValueError
            return reservation
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Malformed execution reservation") from exc

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Reservation clock must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)

    @staticmethod
    def _has_other_unresolved_intent(
        connection: sqlite3.Connection, intent_key: str
    ) -> bool:
        rows = connection.execute(
            "SELECT idempotency_key, state FROM intent_records"
        ).fetchall()
        states = tuple(
            (row["idempotency_key"], IntentRecordStatus(row["state"])) for row in rows
        )
        return any(
            key != intent_key
            and state in {IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN}
            for key, state in states
        )

    def get(self, idempotency_key: str) -> IntentRecord | None:
        self._validate_key(idempotency_key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT idempotency_key, state, order_id, transaction_id FROM intent_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else self._decode(row)

    def list_unresolved(self) -> tuple[IntentRecord, ...]:
        """Return non-terminal records in deterministic creation order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT idempotency_key, state, order_id, transaction_id "
                "FROM intent_records ORDER BY created_at ASC, idempotency_key ASC"
            ).fetchall()
        records = tuple(self._decode(row) for row in rows)
        return tuple(
            record
            for record in records
            if record.status in {IntentRecordStatus.PENDING, IntentRecordStatus.UNKNOWN}
        )

    def inspect(self, idempotency_key: str) -> IntentRecordInspection | None:
        """Read-only operational inspection; never changes intent state."""
        self._validate_key(idempotency_key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT idempotency_key, state, order_id, transaction_id, created_at, updated_at FROM intent_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        record = self._decode(row)
        return IntentRecordInspection(record.idempotency_key, record.status, record.order_id, record.transaction_id, row["created_at"], row["updated_at"])

    def backup_to(self, destination: str | Path) -> None:
        """Create a consistent SQLite backup without mutating this store."""
        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self._connect()
        try:
            backup = sqlite3.connect(str(target))
            try:
                source.backup(backup)
            finally:
                backup.close()
        finally:
            source.close()

    def acquire_reservation(
        self, scope: str, owner_id: str, lease_seconds: int, intent_key: str
    ) -> ReservationState:
        self._validate_reservation_identity(scope, owner_id)
        self._validate_key(intent_key)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or lease_seconds <= 0:
            raise ValueError("Reservation lease duration must be a positive integer")
        now = self._now()
        expires_at = now + timedelta(seconds=lease_seconds)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT scope, owner_id, acquired_at, expires_at "
                "FROM execution_reservations WHERE scope = ?",
                (scope,),
            ).fetchone()
            if row is not None:
                current = self._decode_reservation(row)
                if current.expires_at > now:
                    connection.rollback()
                    return ReservationState.HELD
            if self._has_other_unresolved_intent(connection, intent_key):
                connection.rollback()
                return ReservationState.UNRESOLVED_INTENT
            connection.execute(
                """INSERT INTO execution_reservations (scope, owner_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET owner_id=excluded.owner_id,
                acquired_at=excluded.acquired_at, expires_at=excluded.expires_at""",
                (
                    scope,
                    owner_id,
                    now.isoformat(timespec="microseconds"),
                    expires_at.isoformat(timespec="microseconds"),
                ),
            )
            connection.commit()
            return ReservationState.ACQUIRED
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def release_reservation(self, scope: str, owner_id: str) -> bool:
        self._validate_reservation_identity(scope, owner_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute(
                "DELETE FROM execution_reservations WHERE scope = ? AND owner_id = ?",
                (scope, owner_id),
            ).rowcount
            connection.commit()
            return deleted == 1
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def try_claim_under_reservation(
        self, record: IntentRecord, scope: str, owner_id: str
    ) -> ClaimState:
        self._validate_key(record.idempotency_key)
        self._validate_reservation_identity(scope, owner_id)
        now = self._now()
        now_text = now.isoformat(timespec="microseconds")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT scope, owner_id, acquired_at, expires_at "
                "FROM execution_reservations WHERE scope = ?",
                (scope,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return ClaimState.CONFLICT
            reservation = self._decode_reservation(row)
            if reservation.owner_id != owner_id or reservation.expires_at <= now:
                connection.rollback()
                return ClaimState.CONFLICT
            try:
                connection.execute(
                    "INSERT INTO intent_records (idempotency_key, state, order_id, transaction_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (record.idempotency_key, record.status.value, record.order_id, record.transaction_id, now_text, now_text),
                )
            except sqlite3.IntegrityError:
                connection.rollback()
                return ClaimState.ALREADY_EXISTS
            connection.commit()
            return ClaimState.CLAIMED
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def try_claim(self, record: IntentRecord) -> ClaimState:
        self._validate_key(record.idempotency_key)
        now = _utc_now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO intent_records (idempotency_key, state, order_id, transaction_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (record.idempotency_key, record.status.value, record.order_id, record.transaction_id, now, now),
                )
            except sqlite3.IntegrityError:
                connection.rollback()
                return ClaimState.ALREADY_EXISTS
            connection.commit()
            return ClaimState.CLAIMED
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def transition(self, record: IntentRecord) -> bool:
        self._validate_key(record.idempotency_key)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT idempotency_key, state, order_id, transaction_id FROM intent_records WHERE idempotency_key = ?",
                (record.idempotency_key,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            current = self._decode(row)
            if record.status not in _ALLOWED_TRANSITIONS[current.status]:
                connection.rollback()
                return False
            connection.execute(
                "UPDATE intent_records SET state = ?, order_id = ?, transaction_id = ?, updated_at = ? WHERE idempotency_key = ?",
                (record.status.value, record.order_id, record.transaction_id, _utc_now(), record.idempotency_key),
            )
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
