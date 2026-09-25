"""Local, lossless-enough MT5 rate cache for broker-order-free replay."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from broker.types import TIMEFRAME_SECONDS, Timeframe
from research.shadow_outcomes import ShadowBar, bars_from_mt5_rates


@dataclass(frozen=True, slots=True)
class HistorySeriesReport:
    symbol: str
    provider_symbol: str | None
    timeframe: str
    bars: int
    first_open: str | None
    last_open: str | None
    first_close: str | None
    last_close: str | None
    gap_count: int
    gaps: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "provider_symbol": self.provider_symbol,
            "timeframe": self.timeframe,
            "bars": self.bars,
            "first_open": self.first_open,
            "last_open": self.last_open,
            "first_close": self.first_close,
            "last_close": self.last_close,
            "gap_count": self.gap_count,
            "gaps": list(self.gaps),
        }


class ShadowHistoryStore:
    """SQLite cache retaining MT5 bar spread and provenance fields."""

    def __init__(self, path: str | Path = "cache/shadow_mt5_rates.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS mt5_rates (
                    symbol TEXT NOT NULL,
                    provider_symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    time INTEGER NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    tick_volume REAL,
                    real_volume REAL,
                    spread_points REAL,
                    point REAL NOT NULL,
                    retrieved_at TEXT NOT NULL,
                    PRIMARY KEY(symbol,timeframe,time)
                )"""
            )

    @staticmethod
    def _value(rate: Any, name: str, default: Any = None) -> Any:
        try:
            return rate[name]
        except (KeyError, IndexError, TypeError):
            return getattr(rate, name, default)

    def save_rates(
        self,
        *,
        symbol: str,
        provider_symbol: str,
        timeframe: Timeframe,
        rates: Iterable[Any],
        point: float,
        retrieved_at: datetime | None = None,
    ) -> int:
        retrieved = (retrieved_at or datetime.now(timezone.utc)).isoformat()
        rows = []
        for rate in rates:
            timestamp = self._value(rate, "time")
            values = [self._value(rate, field) for field in ("open", "high", "low", "close")]
            if timestamp is None or any(value is None for value in values) or point <= 0:
                continue
            rows.append(
                (
                    symbol, provider_symbol, timeframe.value, int(timestamp),
                    *[float(value) for value in values],
                    float(self._value(rate, "tick_volume", 0) or 0),
                    float(self._value(rate, "real_volume", 0) or 0),
                    None if self._value(rate, "spread") is None else float(self._value(rate, "spread")),
                    float(point), retrieved,
                )
            )
        if not rows:
            return 0
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                """INSERT INTO mt5_rates(
                    symbol,provider_symbol,timeframe,time,open,high,low,close,
                    tick_volume,real_volume,spread_points,point,retrieved_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(symbol,timeframe,time) DO UPDATE SET
                    provider_symbol=excluded.provider_symbol, open=excluded.open,
                    high=excluded.high, low=excluded.low, close=excluded.close,
                    tick_volume=excluded.tick_volume, real_volume=excluded.real_volume,
                    spread_points=excluded.spread_points, point=excluded.point,
                    retrieved_at=excluded.retrieved_at""",
                rows,
            )
        return len(rows)

    def load_bars(self, symbol: str, timeframe: Timeframe) -> list[ShadowBar]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """SELECT time,open,high,low,close,spread_points,point
                   FROM mt5_rates WHERE symbol=? AND timeframe=? ORDER BY time""",
                (symbol, timeframe.value),
            ).fetchall()
        result = []
        for timestamp, open_, high, low, close, spread_points, point in rows:
            spread = None if spread_points is None else float(spread_points) * float(point)
            result.append(
                ShadowBar(
                    time=datetime.fromtimestamp(timestamp, tz=timezone.utc),
                    open=float(open_), high=float(high), low=float(low), close=float(close),
                    spread_price=spread, source="mt5-cache",
                )
            )
        return result

    def report_series(self, symbol: str, timeframe: Timeframe) -> HistorySeriesReport:
        bars = self.load_bars(symbol, timeframe)
        provider_symbol = None
        if bars:
            with sqlite3.connect(self.path) as conn:
                row = conn.execute(
                    "SELECT provider_symbol FROM mt5_rates WHERE symbol=? AND timeframe=? LIMIT 1",
                    (symbol, timeframe.value),
                ).fetchone()
            provider_symbol = row[0] if row else None
        step = TIMEFRAME_SECONDS[timeframe]
        gaps: list[dict[str, Any]] = []
        for previous, current in zip(bars, bars[1:]):
            delta = (current.time - previous.time).total_seconds()
            if delta > step:
                missing = max(0, int(delta // step) - 1)
                gaps.append({
                    "from_open": previous.time.isoformat(),
                    "to_open": current.time.isoformat(),
                    "missing_intervals": missing,
                })
        first = bars[0].time if bars else None
        last = bars[-1].time if bars else None
        return HistorySeriesReport(
            symbol=symbol, provider_symbol=provider_symbol, timeframe=timeframe.value,
            bars=len(bars), first_open=first.isoformat() if first else None,
            last_open=last.isoformat() if last else None,
            first_close=(first + timedelta(seconds=step)).isoformat() if first else None,
            last_close=(last + timedelta(seconds=step)).isoformat() if last else None,
            gap_count=len(gaps), gaps=tuple(gaps[:20]),
        )

