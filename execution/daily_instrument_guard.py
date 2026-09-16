"""Durable per-account, per-instrument UTC-day submission-start cap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import Callable


DAILY_INSTRUMENT_CAP_REACHED = "DAILY_INSTRUMENT_CAP_REACHED"


class DailyInstrumentCapReached(RuntimeError):
    reason_code = DAILY_INSTRUMENT_CAP_REACHED

    def __init__(self, *, scope: str, instrument: str, utc_date: str, limit: int) -> None:
        self.scope = scope
        self.instrument = instrument
        self.utc_date = utc_date
        self.limit = limit
        super().__init__(DAILY_INSTRUMENT_CAP_REACHED)


@dataclass(frozen=True, slots=True)
class DailyInstrumentUsage:
    scope: str
    instrument: str
    utc_date: str
    count: int
    limit: int
    reset_at: datetime


class DailyInstrumentTradeGuard:
    """Atomically count submission starts and fail closed once the daily cap is reached."""

    def __init__(
        self,
        path: str | Path,
        *,
        limit: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("Daily instrument trade limit must be a positive integer")
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self._path = str(resolved)
        self.limit = limit
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS daily_instrument_trade_counter (
                    scope TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    utc_date TEXT NOT NULL,
                    submission_starts INTEGER NOT NULL CHECK (submission_starts >= 0),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(scope, instrument, utc_date)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10.0)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _key(scope: str, instrument: str) -> tuple[str, str]:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("Account scope must be nonblank")
        if not isinstance(instrument, str) or not instrument.strip():
            raise ValueError("Instrument must be nonblank")
        return scope.strip(), instrument.strip().upper()

    def _now(self, at: datetime | None = None) -> datetime:
        value = at or self._clock()
        if value.tzinfo is None:
            raise ValueError("Daily instrument guard clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    def usage(self, scope: str, instrument: str, *, at: datetime | None = None) -> DailyInstrumentUsage:
        normalized_scope, normalized_instrument = self._key(scope, instrument)
        now = self._now(at)
        utc_date = now.date().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT submission_starts FROM daily_instrument_trade_counter
                   WHERE scope=? AND instrument=? AND utc_date=?""",
                (normalized_scope, normalized_instrument, utc_date),
            ).fetchone()
        reset_at = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc)
        return DailyInstrumentUsage(
            normalized_scope, normalized_instrument, utc_date,
            0 if row is None else int(row[0]), self.limit, reset_at,
        )

    def consume(self, scope: str, instrument: str, *, at: datetime | None = None) -> DailyInstrumentUsage:
        normalized_scope, normalized_instrument = self._key(scope, instrument)
        now = self._now(at)
        utc_date = now.date().isoformat()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT submission_starts FROM daily_instrument_trade_counter
                   WHERE scope=? AND instrument=? AND utc_date=?""",
                (normalized_scope, normalized_instrument, utc_date),
            ).fetchone()
            count = 0 if row is None else int(row[0])
            if count >= self.limit:
                connection.rollback()
                raise DailyInstrumentCapReached(
                    scope=normalized_scope, instrument=normalized_instrument,
                    utc_date=utc_date, limit=self.limit,
                )
            count += 1
            connection.execute(
                """INSERT INTO daily_instrument_trade_counter
                   (scope, instrument, utc_date, submission_starts, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(scope, instrument, utc_date) DO UPDATE SET
                     submission_starts=excluded.submission_starts,
                     updated_at=excluded.updated_at""",
                (normalized_scope, normalized_instrument, utc_date, count, now.isoformat()),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.usage(normalized_scope, normalized_instrument, at=now)
