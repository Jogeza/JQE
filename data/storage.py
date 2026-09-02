"""Local persistence for historical candle data.

:class:`CandleStore` wraps a SQLite database (Python's stdlib
``sqlite3`` — no extra dependency) that caches
:class:`broker.types.Candle` data per ``(provider, symbol, timeframe)``, so
:class:`data.historical.HistoricalDataService` can serve repeated
requests without re-downloading from a broker every time.

The cache database lives under ``config.settings.cache_dir`` (default
``cache/``, git-ignored — see ``.gitignore`` and
``docs/architecture.md``, "Data layer"). This is runtime state, not
source; the ``data`` *package* itself (this file, ``historical.py``,
``types.py``) is tracked normally.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

from broker.types import TIMEFRAME_SECONDS, Candle, Timeframe
from config import settings
from core.exceptions import CacheError
from core.logger import logger
from data.types import CacheValidationResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    provider TEXT NOT NULL DEFAULT 'unknown',
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    source TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (provider, symbol, timeframe, time)
);
CREATE INDEX IF NOT EXISTS idx_candles_provider_symbol_timeframe_time
    ON candles (provider, symbol, timeframe, time);
"""

#: A gap is flagged when the interval between two consecutive cached
#: candles exceeds the timeframe's expected step by more than this
#: factor — a small tolerance avoids flagging normal broker jitter
#: (e.g. a session close a few seconds later than exactly on-grid) as
#: a real gap.
_GAP_TOLERANCE = 1.5


def find_gaps(candles: list[Candle], step_seconds: int) -> list[tuple[datetime, datetime]]:
    """Finds time gaps between consecutive candles in a sorted series.

    Shared by :meth:`CandleStore.validate` (report-only) and
    :meth:`data.historical.HistoricalDataService.fill_gaps`
    (report-and-download), so gap *detection* has exactly one
    implementation regardless of what the caller does with the result.

    Args:
        candles: Candles sorted oldest to newest (not verified here —
            callers are expected to load them pre-sorted, as
            :meth:`CandleStore.load_candles` always does).
        step_seconds: Expected seconds between consecutive candles for
            this series' timeframe.

    Returns:
        A list of ``(gap_start, gap_end)`` pairs — the timestamps
        immediately bracketing each detected gap (``gap_start`` is the
        last candle before the gap, ``gap_end`` is the first candle
        after it).
    """
    threshold = step_seconds * _GAP_TOLERANCE
    gaps: list[tuple[datetime, datetime]] = []
    for previous, current in pairwise(candles):
        delta = (current.time - previous.time).total_seconds()
        if delta > threshold:
            gaps.append((previous.time, current.time))
    return gaps


class CandleStore:
    """SQLite-backed local cache of historical candle data.

    Attributes:
        db_path: Path to the SQLite database file. Created (along with
            its parent directory) on first use if it doesn't exist.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (settings.cache_dir / "candles.db")
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CacheError(f"Failed to create cache directory for {self.db_path}") from exc
        self._init_schema()

    def save_candles(self, symbol: str, timeframe: Timeframe, candles: Iterable[Candle], provider: str | None = None) -> int:
        """Upserts candles into the cache.

        Safe to call with overlapping data — existing candles at the
        same ``(symbol, timeframe, time)`` are replaced, so re-fetching
        a window that includes already-cached candles (as
        :class:`data.historical.HistoricalDataService` does when
        incrementally syncing) never creates duplicates.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.
            candles: Candles to store.

        Returns:
            Number of candles written.
        """
        candles = list(candles)
        if not candles:
            return 0
        strict_conflicts = provider is not None
        providers = {provider or candle.source for candle in candles}
        if len(providers) != 1:
            raise CacheError("Candle batch cannot mix providers")
        resolved_provider = next(iter(providers), "unknown")
        if not isinstance(resolved_provider, str) or not resolved_provider.strip():
            raise CacheError("Candle provider identity is required")
        rows = [
            (
                resolved_provider,
                symbol,
                timeframe.value,
                int(candle.time.timestamp()),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.source,
            )
            for candle in candles
        ]
        written = 0
        try:
            with closing(self._connect()) as conn, conn:
                pending = []
                seen_keys = set()
                for row in rows:
                    key = row[:4]
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    existing = conn.execute(
                        "SELECT open, high, low, close, volume FROM candles WHERE provider=? AND symbol=? AND timeframe=? AND time=?",
                        key,
                    ).fetchone()
                    if existing is not None:
                        existing_values = tuple(existing)
                        incoming_values = row[4:9]
                        if existing_values != incoming_values:
                            if strict_conflicts:
                                raise CacheError("Conflicting duplicate candle", provider=resolved_provider, symbol=symbol, timestamp=row[3])
                            conn.execute(
                                "UPDATE candles SET open=?, high=?, low=?, close=?, volume=?, source=? WHERE provider=? AND symbol=? AND timeframe=? AND time=?",
                                row[4:9] + (row[9],) + row[:4],
                            )
                            written += 1
                        continue
                    pending.append(row)
                if pending:
                    conn.executemany(
                        "INSERT INTO candles (provider, symbol, timeframe, time, open, high, low, close, volume, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        pending,
                    )
                    written += len(pending)
        except sqlite3.DatabaseError as exc:
            raise CacheError(
                "Failed to write candles to cache", symbol=symbol, timeframe=timeframe.value
            ) from exc

        logger.debug("Cached {} candle(s) for {} {}", len(rows), symbol, timeframe.value)
        return written

    def load_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
        provider: str | None = None,
    ) -> list[Candle]:
        """Loads cached candles, oldest to newest.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.
            start: If given, excludes candles before this time.
            end: If given, excludes candles after this time.

        Returns:
            Candles ordered oldest to newest. Empty if nothing is
            cached for this symbol/timeframe (and window, if given).
        """
        query = "SELECT provider, time, open, high, low, close, volume, source FROM candles WHERE symbol = ? AND timeframe = ?"
        params: list[object] = [symbol, timeframe.value]
        if provider is not None:
            query += " AND provider = ?"
            params.append(provider)
        if start is not None:
            query += " AND time >= ?"
            params.append(int(start.timestamp()))
        if end is not None:
            query += " AND time <= ?"
            params.append(int(end.timestamp()))
        query += " ORDER BY time ASC"

        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(query, params).fetchall()
        except sqlite3.DatabaseError as exc:
            raise CacheError(
                "Failed to read candles from cache", symbol=symbol, timeframe=timeframe.value
            ) from exc

        return [_row_to_candle(row) for row in rows]

    def load_latest(self, symbol: str, timeframe: Timeframe, count: int, provider: str | None = None) -> list[Candle]:
        """Loads the most recent ``count`` cached candles, oldest to newest.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.
            count: Maximum number of candles to return.

        Returns:
            Up to ``count`` candles ordered oldest to newest. Shorter
            than ``count`` if fewer are cached.
        """
        try:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    "SELECT provider, time, open, high, low, close, volume, source FROM candles "
                    "WHERE symbol = ? AND timeframe = ?" + (" AND provider = ?" if provider is not None else "") + " ORDER BY time DESC LIMIT ?",
                    (symbol, timeframe.value, provider, count) if provider is not None else (symbol, timeframe.value, count),
                ).fetchall()
        except sqlite3.DatabaseError as exc:
            raise CacheError(
                "Failed to read candles from cache", symbol=symbol, timeframe=timeframe.value
            ) from exc

        return [_row_to_candle(row) for row in reversed(rows)]

    def get_coverage(self, symbol: str, timeframe: Timeframe, provider: str | None = None) -> tuple[datetime, datetime] | None:
        """Returns the ``(earliest, latest)`` cached candle time, or ``None`` if empty."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT MIN(time) AS min_t, MAX(time) AS max_t FROM candles WHERE symbol = ? AND timeframe = ?" + (" AND provider = ?" if provider is not None else ""),
                (symbol, timeframe.value, provider) if provider is not None else (symbol, timeframe.value),
            ).fetchone()
        if row is None or row["min_t"] is None:
            return None
        return (
            datetime.fromtimestamp(row["min_t"], tz=timezone.utc),
            datetime.fromtimestamp(row["max_t"], tz=timezone.utc),
        )

    def count(self, symbol: str, timeframe: Timeframe, provider: str | None = None) -> int:
        """Returns the number of cached candles for a symbol/timeframe."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM candles WHERE symbol = ? AND timeframe = ?" + (" AND provider = ?" if provider is not None else ""),
                (symbol, timeframe.value, provider) if provider is not None else (symbol, timeframe.value),
            ).fetchone()
        return int(row["n"])

    def validate(self, symbol: str, timeframe: Timeframe, provider: str | None = None) -> CacheValidationResult:
        """Checks cached data for corruption, ordering issues, and gaps.

        Args:
            symbol: Instrument symbol.
            timeframe: Candle timeframe.

        Returns:
            A report of every issue found. An empty cache is
            considered valid (nothing to be wrong with).
        """
        candles = self.load_candles(symbol, timeframe, provider=provider)
        issues: list[str] = []

        for previous, current in pairwise(candles):
            if current.time <= previous.time:
                issues.append(f"Non-monotonic timestamps: {previous.time} -> {current.time}")

        for candle in candles:
            if candle.high < candle.low:
                issues.append(f"high < low at {candle.time}")
            if candle.open <= 0 or candle.close <= 0:
                issues.append(f"non-positive open/close at {candle.time}")

        gaps = find_gaps(candles, TIMEFRAME_SECONDS[timeframe])
        if gaps:
            issues.append(f"{len(gaps)} gap(s) detected in cached data")

        return CacheValidationResult(is_valid=not issues, issues=issues, candle_count=len(candles))

    def clear(self, symbol: str | None = None, timeframe: Timeframe | None = None, provider: str | None = None) -> int:
        """Deletes cached candles.

        Args:
            symbol: If given (with ``timeframe``), deletes only this
                symbol/timeframe's candles. If omitted, deletes
                everything.
            timeframe: See ``symbol``.

        Returns:
            Number of rows deleted.
        """
        with closing(self._connect()) as conn, conn:
            if symbol is not None and timeframe is not None:
                query = "DELETE FROM candles WHERE symbol = ? AND timeframe = ?"
                params: list[object] = [symbol, timeframe.value]
                if provider is not None:
                    query += " AND provider = ?"
                    params.append(provider)
                cursor = conn.execute(query, params)
            elif provider is not None:
                cursor = conn.execute("DELETE FROM candles WHERE provider = ?", (provider,))
            else:
                cursor = conn.execute("DELETE FROM candles")
        return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        try:
            with closing(self._connect()) as conn, conn:
                table_info = list(conn.execute("PRAGMA table_info(candles)"))
                columns = {row[1] for row in table_info}
                if not columns:
                    conn.executescript(_SCHEMA)
                elif "provider" not in columns:
                    # Preserve the old table and migrate rows using their source
                    # as provider identity. Existing local data is never deleted.
                    conn.execute("ALTER TABLE candles RENAME TO candles_legacy")
                    conn.execute("DROP INDEX IF EXISTS idx_candles_symbol_timeframe_time")
                    conn.executescript(_SCHEMA)
                    legacy_columns = {row[1] for row in conn.execute("PRAGMA table_info(candles_legacy)")}
                    source_expr = "source" if "source" in legacy_columns else "'unknown'"
                    time_expr = "time" if "time" in legacy_columns else "timestamp"
                    conn.execute(
                        f"INSERT INTO candles (provider, symbol, timeframe, time, open, high, low, close, volume, source) SELECT {source_expr}, symbol, timeframe, {time_expr}, open, high, low, close, volume, {source_expr} FROM candles_legacy"
                    )
                    conn.execute("DROP TABLE candles_legacy")
                else:
                    conn.executescript(_SCHEMA)
        except sqlite3.DatabaseError as exc:
            raise CacheError(f"Failed to initialize cache database at {self.db_path}") from exc


def _row_to_candle(row: sqlite3.Row) -> Candle:
    return Candle(
        time=datetime.fromtimestamp(row["time"], tz=timezone.utc),
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        source=row["source"],
    )
