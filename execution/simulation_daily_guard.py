"""Durable UTC-day submission cap for offline simulation only.

This module deliberately has no broker dependencies. It authorizes and counts
starts at an offline simulation boundary; it cannot construct or route orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3


DEMO_DAILY_SUBMISSION_CAP_REACHED = "DEMO_DAILY_SUBMISSION_CAP_REACHED"


class SimulationDailyCapReached(RuntimeError):
    code = DEMO_DAILY_SUBMISSION_CAP_REACHED


@dataclass(frozen=True)
class SimulationDailyGuardStatus:
    scope: str
    utc_date: str
    count: int
    limit: int
    reset_at: datetime

    @property
    def available(self) -> bool:
        return self.count < self.limit


class SQLiteSimulationDailySubmissionGuard:
    """Atomically count offline mock submission starts by scope and UTC day."""

    def __init__(self, path: str | Path, *, limit: int) -> None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("Simulation daily submission limit must be a positive integer")
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(resolved)
        self.limit = limit
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS simulation_daily_submission_counter (
                    scope TEXT NOT NULL, utc_date TEXT NOT NULL,
                    submissions INTEGER NOT NULL CHECK (submissions >= 0),
                    updated_at TEXT NOT NULL, PRIMARY KEY(scope, utc_date)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _scope(scope: str) -> str:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("Simulation account scope must be nonblank")
        normalized = scope.strip()
        if not normalized.lower().startswith("simulation:"):
            raise ValueError("Simulation daily guard only accepts simulation account scopes")
        return normalized

    @staticmethod
    def _day(now: datetime | None) -> tuple[datetime, str]:
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("Guard timestamps must be timezone-aware")
        utc = instant.astimezone(timezone.utc)
        return utc, utc.date().isoformat()

    def status(self, scope: str, *, now: datetime | None = None) -> SimulationDailyGuardStatus:
        normalized = self._scope(scope)
        utc, day = self._day(now)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT submissions FROM simulation_daily_submission_counter WHERE scope=? AND utc_date=?",
                (normalized, day),
            ).fetchone()
        return SimulationDailyGuardStatus(
            scope=normalized, utc_date=day,
            count=0 if row is None else int(row[0]), limit=self.limit,
            reset_at=datetime.combine(utc.date() + timedelta(days=1), time.min, tzinfo=timezone.utc),
        )

    def assert_available(self, scope: str, *, now: datetime | None = None) -> None:
        status = self.status(scope, now=now)
        if not status.available:
            raise SimulationDailyCapReached(
                f"Offline simulation daily submission cap reached ({status.count}/{status.limit})"
            )

    def consume(self, scope: str, *, now: datetime | None = None) -> SimulationDailyGuardStatus:
        normalized = self._scope(scope)
        utc, day = self._day(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT submissions FROM simulation_daily_submission_counter WHERE scope=? AND utc_date=?",
                (normalized, day),
            ).fetchone()
            count = 0 if row is None else int(row[0])
            if count >= self.limit:
                raise SimulationDailyCapReached(
                    f"Offline simulation daily submission cap reached ({count}/{self.limit})"
                )
            connection.execute(
                """INSERT INTO simulation_daily_submission_counter(scope, utc_date, submissions, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, utc_date) DO UPDATE SET
                    submissions=excluded.submissions, updated_at=excluded.updated_at""",
                (normalized, day, count + 1, utc.isoformat()),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.status(normalized, now=utc)
