"""Durable, broker-agnostic intent persistence backed by SQLite."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
import sqlite3
from pathlib import Path

from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderSide
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
    symbol: str | None = None
    side: str | None = None
    quantity_value: float | None = None
    quantity_unit: str | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    authorized_risk_amount: float | None = None
    expected_loss_at_stop: float | None = None
    broker: str | None = None
    account_id: str | None = None
    reconstruction_valid: bool = False
    recovery_outcome: str | None = None
    reconciliation_state: str | None = None
    recovery_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PositionLedgerEntry:
    """One campaign-opened broker position tracked across process restarts."""

    broker: str
    symbol: str
    position_id: str
    order_id: str
    opened_at: str
    closed_at: str | None = None
    close_price: float | None = None
    realized_pnl: float | None = None
    currency: str | None = None
    reconciliation_state: str | None = None


class SQLitePositionLedger:
    """Instance-scoped position identity ledger backed by durable SQLite writes.

    This is recovery metadata, not authoritative position state. Every startup
    reconciles its open rows against the broker's current position snapshot.
    """

    def __init__(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(resolved)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS live_paper_positions (
                    broker TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    close_price REAL,
                    realized_pnl REAL,
                    currency TEXT,
                    reconciliation_state TEXT,
                    PRIMARY KEY (broker, position_id)
                )
                """
            )
            existing = {
                row[1]
                for row in connection.execute("PRAGMA table_info(live_paper_positions)")
            }
            for name, kind in (
                ("close_price", "REAL"),
                ("realized_pnl", "REAL"),
                ("currency", "TEXT"),
                ("reconciliation_state", "TEXT"),
            ):
                if name not in existing:
                    connection.execute(
                        f"ALTER TABLE live_paper_positions ADD COLUMN {name} {kind}"
                    )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _required_text(name: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonblank string")
        return value.strip()

    def record_open(
        self,
        *,
        broker: str,
        symbol: str,
        position_id: str,
        order_id: str,
        opened_at: datetime,
    ) -> None:
        if opened_at.tzinfo is None or opened_at.utcoffset() is None:
            raise ValueError("opened_at must be timezone-aware")
        values = (
            self._required_text("broker", broker),
            self._required_text("symbol", symbol),
            self._required_text("position_id", position_id),
            self._required_text("order_id", order_id),
            opened_at.astimezone(timezone.utc).isoformat(),
        )
        with self._connect() as connection:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """
                INSERT INTO live_paper_positions
                    (broker, symbol, position_id, order_id, opened_at, closed_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(broker, position_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    order_id=excluded.order_id,
                    opened_at=excluded.opened_at,
                    closed_at=NULL
                """,
                values,
            )

    def mark_closed(
        self,
        *,
        broker: str,
        position_id: str,
        closed_at: datetime,
        close_price: float | None = None,
        realized_pnl: float | None = None,
        currency: str | None = None,
        reconciliation_state: str | None = None,
    ) -> bool:
        if closed_at.tzinfo is None or closed_at.utcoffset() is None:
            raise ValueError("closed_at must be timezone-aware")
        with self._connect() as connection:
            connection.execute("PRAGMA synchronous=FULL")
            changed = connection.execute(
                """
                UPDATE live_paper_positions
                SET closed_at=?, close_price=?, realized_pnl=?, currency=?,
                    reconciliation_state=?
                WHERE broker=? AND position_id=? AND closed_at IS NULL
                """,
                (
                    closed_at.astimezone(timezone.utc).isoformat(),
                    close_price,
                    realized_pnl,
                    currency,
                    reconciliation_state,
                    self._required_text("broker", broker),
                    self._required_text("position_id", position_id),
                ),
            ).rowcount
        return changed == 1

    def open_entries(self, *, broker: str) -> tuple[PositionLedgerEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT broker, symbol, position_id, order_id, opened_at, closed_at,
                       close_price, realized_pnl, currency, reconciliation_state
                FROM live_paper_positions
                WHERE broker=? AND closed_at IS NULL
                ORDER BY opened_at, position_id
                """,
                (self._required_text("broker", broker),),
            ).fetchall()
        return tuple(PositionLedgerEntry(**dict(row)) for row in rows)

    def entries(self) -> tuple[PositionLedgerEntry, ...]:
        """Return all rows for diagnostics and tests."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT broker, symbol, position_id, order_id, opened_at, closed_at,
                       close_price, realized_pnl, currency, reconciliation_state
                FROM live_paper_positions
                ORDER BY opened_at, position_id
                """
            ).fetchall()
        return tuple(PositionLedgerEntry(**dict(row)) for row in rows)


class SQLiteOneShotExecutionGuard:
    """Durable account-scoped lifetime submission cap.

    Consuming the slot is intentionally irreversible: an indeterminate broker
    outcome must never make a second submission possible.
    """

    def __init__(self, path: str | Path, *, limit: int = 1) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit != 1:
            raise ValueError("Only the one-order lifetime limit is supported")
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(resolved)
        self.limit = limit
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS execution_lifetime_counter (
                    scope TEXT PRIMARY KEY,
                    submissions INTEGER NOT NULL CHECK (submissions >= 0),
                    updated_at TEXT NOT NULL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _scope(scope: str) -> str:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("Execution lifetime scope must be nonblank")
        return scope.strip()

    def count(self, scope: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT submissions FROM execution_lifetime_counter WHERE scope=?",
                (self._scope(scope),),
            ).fetchone()
        return 0 if row is None else int(row[0])

    def assert_available(self, scope: str) -> None:
        if self.count(scope) >= self.limit:
            raise RuntimeError("One-order lifetime execution cap has already been consumed")

    def consume(self, scope: str) -> None:
        normalized = self._scope(scope)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT submissions FROM execution_lifetime_counter WHERE scope=?",
                (normalized,),
            ).fetchone()
            count = 0 if row is None else int(row[0])
            if count >= self.limit:
                connection.rollback()
                raise RuntimeError("One-order lifetime execution cap has already been consumed")
            connection.execute(
                """INSERT INTO execution_lifetime_counter(scope, submissions, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(scope) DO UPDATE SET submissions=1, updated_at=excluded.updated_at""",
                (normalized, _utc_now()),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

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
        initialize: bool = True,
    ) -> None:
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(resolved)
        self.recovery_mode = recovery_mode
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if initialize:
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
                    updated_at TEXT NOT NULL,
                    symbol TEXT,
                    side TEXT,
                    quantity_value REAL,
                    quantity_unit TEXT,
                    entry REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    authorized_risk_amount REAL,
                    expected_loss_at_stop REAL,
                    broker TEXT,
                    account_id TEXT
                    , recovery_outcome TEXT
                    , reconciliation_state TEXT
                    , recovery_reason TEXT
                )
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(intent_records)")}
            new_columns = (
                ("transaction_id", "TEXT"),
                ("symbol", "TEXT"),
                ("side", "TEXT"),
                ("quantity_value", "REAL"),
                ("quantity_unit", "TEXT"),
                ("entry", "REAL"),
                ("stop_loss", "REAL"),
                ("take_profit", "REAL"),
                ("authorized_risk_amount", "REAL"),
                ("expected_loss_at_stop", "REAL"),
                ("broker", "TEXT"),
                ("account_id", "TEXT"),
                ("recovery_outcome", "TEXT"),
                ("reconciliation_state", "TEXT"),
                ("recovery_reason", "TEXT"),
            )
            for col_name, col_type in new_columns:
                if col_name not in columns:
                    connection.execute(f"ALTER TABLE intent_records ADD COLUMN {col_name} {col_type}")
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
            row_keys = row.keys()
            quantity = None
            if "quantity_value" in row_keys and row["quantity_value"] is not None:
                quantity = ExecutionQuantity(
                    value=float(row["quantity_value"]),
                    unit=ExecutionQuantityUnit(row["quantity_unit"]),
                )
            side = None
            if "side" in row_keys and row["side"] is not None:
                side = OrderSide(row["side"])

            return IntentRecord(
                idempotency_key=row["idempotency_key"],
                status=IntentRecordStatus(row["state"]),
                order_id=row["order_id"],
                transaction_id=row["transaction_id"] if "transaction_id" in row_keys else None,
                symbol=row["symbol"] if "symbol" in row_keys else None,
                side=side,
                quantity=quantity,
                entry=float(row["entry"]) if "entry" in row_keys and row["entry"] is not None else None,
                stop_loss=float(row["stop_loss"]) if "stop_loss" in row_keys and row["stop_loss"] is not None else None,
                take_profit=float(row["take_profit"]) if "take_profit" in row_keys and row["take_profit"] is not None else None,
                authorized_risk_amount=float(row["authorized_risk_amount"]) if "authorized_risk_amount" in row_keys and row["authorized_risk_amount"] is not None else None,
                expected_loss_at_stop=float(row["expected_loss_at_stop"]) if "expected_loss_at_stop" in row_keys and row["expected_loss_at_stop"] is not None else None,
                broker=row["broker"] if "broker" in row_keys else None,
                account_id=row["account_id"] if "account_id" in row_keys else None,
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
                "SELECT * FROM intent_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else self._decode(row)

    def list_unresolved(self) -> tuple[IntentRecord, ...]:
        """Return non-terminal records in deterministic creation order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM intent_records ORDER BY created_at ASC, idempotency_key ASC"
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
                "SELECT * FROM intent_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        record = self._decode(row)
        side_val = record.side.value if isinstance(record.side, OrderSide) else record.side
        quantity_val = record.quantity.value if record.quantity is not None else None
        quantity_unit = record.quantity.unit.value if record.quantity is not None else None
        return IntentRecordInspection(
            idempotency_key=record.idempotency_key,
            status=record.status,
            order_id=record.order_id,
            transaction_id=record.transaction_id,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            symbol=record.symbol,
            side=side_val,
            quantity_value=quantity_val,
            quantity_unit=quantity_unit,
            entry=record.entry,
            stop_loss=record.stop_loss,
            take_profit=record.take_profit,
            authorized_risk_amount=record.authorized_risk_amount,
            expected_loss_at_stop=record.expected_loss_at_stop,
            broker=record.broker,
            account_id=record.account_id,
            reconstruction_valid=record.to_execution_intent() is not None,
            recovery_outcome=row["recovery_outcome"],
            reconciliation_state=row["reconciliation_state"],
            recovery_reason=row["recovery_reason"],
        )

    def list_unresolved_inspections(self) -> tuple[IntentRecordInspection, ...]:
        """Return read-only diagnostics for unresolved rows in creation order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT idempotency_key FROM intent_records "
                "WHERE state IN (?, ?) ORDER BY created_at ASC, idempotency_key ASC",
                (IntentRecordStatus.PENDING.value, IntentRecordStatus.UNKNOWN.value),
            ).fetchall()
        inspections = tuple(self.inspect(row["idempotency_key"]) for row in rows)
        return tuple(item for item in inspections if item is not None)

    def record_recovery_diagnostic(
        self,
        idempotency_key: str,
        *,
        recovery_outcome: str,
        reconciliation_state: str | None,
        recovery_reason: str,
    ) -> bool:
        """Persist recovery-produced metadata; never changes execution state."""
        self._validate_key(idempotency_key)
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE intent_records SET recovery_outcome = ?, "
                "reconciliation_state = ?, recovery_reason = ? "
                "WHERE idempotency_key = ?",
                (
                    recovery_outcome,
                    reconciliation_state,
                    recovery_reason,
                    idempotency_key,
                ),
            ).rowcount
        return updated == 1

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
        side_val = record.side.value if isinstance(record.side, OrderSide) else record.side
        quantity_val = record.quantity.value if record.quantity is not None else None
        quantity_unit = record.quantity.unit.value if record.quantity is not None else None
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
                    """
                    INSERT INTO intent_records (
                        idempotency_key, state, order_id, transaction_id, created_at, updated_at,
                        symbol, side, quantity_value, quantity_unit, entry, stop_loss, take_profit,
                        authorized_risk_amount, expected_loss_at_stop, broker, account_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.idempotency_key,
                        record.status.value,
                        record.order_id,
                        record.transaction_id,
                        now_text,
                        now_text,
                        record.symbol,
                        side_val,
                        quantity_val,
                        quantity_unit,
                        record.entry,
                        record.stop_loss,
                        record.take_profit,
                        record.authorized_risk_amount,
                        record.expected_loss_at_stop,
                        record.broker,
                        record.account_id or scope,
                    ),
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
        side_val = record.side.value if isinstance(record.side, OrderSide) else record.side
        quantity_val = record.quantity.value if record.quantity is not None else None
        quantity_unit = record.quantity.unit.value if record.quantity is not None else None
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO intent_records (
                        idempotency_key, state, order_id, transaction_id, created_at, updated_at,
                        symbol, side, quantity_value, quantity_unit, entry, stop_loss, take_profit,
                        authorized_risk_amount, expected_loss_at_stop, broker, account_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.idempotency_key,
                        record.status.value,
                        record.order_id,
                        record.transaction_id,
                        now,
                        now,
                        record.symbol,
                        side_val,
                        quantity_val,
                        quantity_unit,
                        record.entry,
                        record.stop_loss,
                        record.take_profit,
                        record.authorized_risk_amount,
                        record.expected_loss_at_stop,
                        record.broker,
                        record.account_id,
                    ),
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
                "SELECT * FROM intent_records WHERE idempotency_key = ?",
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
