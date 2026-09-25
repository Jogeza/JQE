"""Persisted, user-editable watchlist of instruments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Sequence

from broker.types import Timeframe


@dataclass(frozen=True, slots=True)
class WatchPair:
    symbol: str
    timeframe: Timeframe

    @property
    def scope(self) -> str:
        return f"{self.symbol}:{self.timeframe.value}"


@dataclass(frozen=True, slots=True)
class WatchlistItem:
    symbol: str
    timeframe: str
    added_at: str

    @property
    def scope(self) -> str:
        return f"{self.symbol}:{self.timeframe}"


# Weltrade synthetic scope: volatility-type instruments plus the PainX family.
# These exact names are confirmed by the Weltrade terminal catalogue. M1 and
# M5 are the entry-observation timeframes; higher-timeframe context is handled
# separately and is not part of this durable entry watchlist.
DEFAULT_SYNTHETIC_SEEDS: tuple[tuple[str, str], ...] = (
    *((symbol, timeframe) for symbol in (
        "FX Vol 20", "FX Vol 40", "FX Vol 60", "FX Vol 80", "FX Vol 99",
        "SFX Vol 20", "SFX Vol 40", "SFX Vol 60", "SFX Vol 80", "SFX Vol 99",
        "PainX 400", "PainX 600", "PainX 800", "PainX 999", "PainX 1200",
        "MAX PainX 1000", "MAX PainX 2000",
    ) for timeframe in ("M1", "M5")),
)


def _normalize_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if not clean:
        raise ValueError("Watchlist symbol must be non-empty")
    return clean


def _normalize_timeframe(timeframe: str) -> str:
    clean = timeframe.strip().upper()
    try:
        tf = Timeframe(clean)
    except ValueError as exc:
        raise ValueError(f"Invalid timeframe '{clean}': must be one of {[t.value for t in Timeframe]}") from exc
    return tf.value


class WatchlistStore:
    """Durable SQLite-backed watchlist store with WAL journal mode."""

    def __init__(
        self,
        path: str | Path,
        *,
        default_seeds: Sequence[tuple[str, str]] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        seeds = default_seeds if default_seeds is not None else DEFAULT_SYNTHETIC_SEEDS
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, timeframe)
                )"""
            )
            row = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()
            if row and row[0] == 0 and seeds:
                now_str = datetime.now(timezone.utc).isoformat()
                records = [
                    (_normalize_symbol(sym), _normalize_timeframe(tf), now_str)
                    for sym, tf in seeds
                ]
                conn.executemany(
                    "INSERT OR IGNORE INTO watchlist (symbol, timeframe, added_at) VALUES (?, ?, ?)",
                    records,
                )
                conn.commit()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WatchlistStore):
            return False
        return self.path == other.path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def get_items(self) -> list[WatchlistItem]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT symbol, timeframe, added_at FROM watchlist ORDER BY rowid ASC"
            ).fetchall()
        return [WatchlistItem(symbol=row[0], timeframe=row[1], added_at=row[2]) for row in rows]

    def add_item(self, symbol: str, timeframe: str = "H1") -> WatchlistItem:
        clean_sym = _normalize_symbol(symbol)
        clean_tf = _normalize_timeframe(timeframe)
        now_str = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO watchlist (symbol, timeframe, added_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(symbol, timeframe) DO NOTHING""",
                (clean_sym, clean_tf, now_str),
            )
            conn.commit()
            row = conn.execute(
                "SELECT symbol, timeframe, added_at FROM watchlist WHERE symbol=? AND timeframe=?",
                (clean_sym, clean_tf),
            ).fetchone()
        return WatchlistItem(symbol=row[0], timeframe=row[1], added_at=row[2])

    def remove_item(self, symbol: str, timeframe: str | None = None) -> bool:
        clean_sym = _normalize_symbol(symbol)
        with self._connect() as conn:
            if timeframe is not None and timeframe.strip():
                clean_tf = _normalize_timeframe(timeframe)
                cur = conn.execute(
                    "DELETE FROM watchlist WHERE symbol=? AND timeframe=?",
                    (clean_sym, clean_tf),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM watchlist WHERE symbol=?",
                    (clean_sym,),
                )
            conn.commit()
            return cur.rowcount > 0

    def get_watch_pairs(self) -> tuple[WatchPair, ...]:
        items = self.get_items()
        return tuple(
            WatchPair(symbol=item.symbol, timeframe=Timeframe(item.timeframe))
            for item in items
        )
