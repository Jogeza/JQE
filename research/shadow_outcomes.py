"""Broker-order-free shadow outcome resolution and replay.

This module deliberately sits on the research side of the application.  It
only consumes candles, ticks, and persisted signal descriptions; it has no
gateway or order-submission dependency.  A signal is entered at the open of
the first candle whose opening time is at or after the signal candle's close.
That next-open assumption is part of the persisted outcome record so a later
report cannot silently change the measurement convention.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import stdev
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from broker.types import TIMEFRAME_SECONDS, Candle, Timeframe
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.storage import CandleStore
from data.watchlist import WatchlistStore
from strategy.pipeline import generate_trading_signal


RESOLVER_VERSION = "shadow-resolver-v2"
ENTRY_ASSUMPTION = "next_candle_open"
OUTCOME_STATUSES = frozenset({"TP", "SL", "TIMEOUT", "AMBIGUOUS", "UNRESOLVED"})
EXIT_AT_SL = "at_sl"
EXIT_GAP_AWARE = "gap_aware"
EXIT_CONSERVATIVE_SLIPPAGE = "conservative_slippage"
EXIT_MODES = frozenset({EXIT_AT_SL, EXIT_GAP_AWARE, EXIT_CONSERVATIVE_SLIPPAGE})
# Pre-declared research parameter.  The prior two-bar setting is retired; an
# explicitly supplied horizon is still honored for historical sensitivity
# reports, but new/live/replay plans default to this value.
DEFAULT_HORIZON_BARS = 20


def _utc(value: datetime | str | int | float) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        result = datetime.fromisoformat(text)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


@dataclass(frozen=True, slots=True)
class ShadowBar:
    """One OHLC bar with the MT5 spread attached in price units."""

    time: datetime
    open: float
    high: float
    low: float
    close: float
    spread_price: float | None
    source: str = "unknown"

    @property
    def close_time(self) -> datetime:
        raise AttributeError("close_time requires a timeframe; use bar_close_time")


@dataclass(frozen=True, slots=True)
class ShadowTick:
    time: datetime
    bid: float | None
    ask: float | None


@dataclass(frozen=True, slots=True)
class SignalSpec:
    signal_id: str
    symbol: str
    timeframe: Timeframe
    side: str
    signal_close: datetime
    stop_loss: float
    take_profit: float
    legacy_score: int | None = None
    institutional_score: int | None = None
    expires_at: datetime | None = None
    horizon_bars: int = DEFAULT_HORIZON_BARS

    def __post_init__(self) -> None:
        if self.side not in {"BUY", "SELL"}:
            raise ValueError("shadow resolver accepts directional signals only")
        if self.stop_loss <= 0 or self.take_profit <= 0:
            raise ValueError("stop and target must be positive")
        if self.horizon_bars <= 0:
            raise ValueError("horizon_bars must be positive")


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    source: str
    signal_id: str
    symbol: str
    timeframe: str
    side: str
    legacy_score: int | None
    institutional_score: int | None
    signal_close: datetime
    entry_time: datetime | None
    entry_price: float | None
    stop_loss: float
    take_profit: float
    status: str
    outcome_time: datetime | None
    outcome_price: float | None
    gross_r: float | None
    spread_cost_price: float | None
    net_r: float | None
    unresolved_reason: str | None
    ambiguity_detail: str | None
    resolver_version: str = RESOLVER_VERSION
    entry_assumption: str = ENTRY_ASSUMPTION
    resolved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    split: str | None = None
    exit_mode: str = EXIT_AT_SL

    def __post_init__(self) -> None:
        if self.status not in OUTCOME_STATUSES:
            raise ValueError(f"unknown shadow outcome status: {self.status}")

    def to_record(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in list(value.items()):
            if isinstance(item, datetime):
                value[key] = item.isoformat()
        return value


def bars_from_mt5_rates(
    rates: Iterable[Any], *, point: float, source: str = "mt5"
) -> list[ShadowBar]:
    """Convert raw MT5 rates, retaining each bar's ``spread`` field.

    A missing or invalid spread remains ``None``.  The resolver fails closed
    for that bar instead of silently substituting a guessed cost.
    """

    result: list[ShadowBar] = []
    for rate in rates:
        def get(name: str, default: Any = None) -> Any:
            try:
                return rate[name]
            except (KeyError, IndexError, TypeError):
                return getattr(rate, name, default)

        spread_points = _finite(get("spread"))
        spread_price = (
            spread_points * point
            if spread_points is not None and math.isfinite(point) and point > 0
            else None
        )
        values = [_finite(get(name)) for name in ("open", "high", "low", "close")]
        timestamp = _finite(get("time"))
        if timestamp is None or any(item is None for item in values):
            continue
        result.append(
            ShadowBar(
                time=_utc(timestamp),
                open=values[0],
                high=values[1],
                low=values[2],
                close=values[3],
                spread_price=spread_price,
                source=source,
            )
        )
    return sorted(result, key=lambda item: item.time)


def bars_from_candles(candles: Iterable[Candle], *, source: str = "cache") -> list[ShadowBar]:
    """Convert cache candles without inventing spread data."""

    return [
        ShadowBar(
            time=_utc(candle.time),
            open=float(candle.open),
            high=float(candle.high),
            low=float(candle.low),
            close=float(candle.close),
            spread_price=None,
            source=source,
        )
        for candle in candles
    ]


def ticks_from_mt5_rates(rates: Iterable[Any]) -> list[ShadowTick]:
    """Convert raw tick records supplied by an MT5 read-only data call."""

    result: list[ShadowTick] = []
    for rate in rates:
        def get(name: str, default: Any = None) -> Any:
            try:
                return rate[name]
            except (KeyError, IndexError, TypeError):
                return getattr(rate, name, default)

        timestamp = _finite(get("time"))
        if timestamp is None:
            continue
        result.append(
            ShadowTick(
                time=_utc(timestamp), bid=_finite(get("bid")), ask=_finite(get("ask"))
            )
        )
    return sorted(result, key=lambda item: item.time)


def _bar_close_time(bar: ShadowBar, timeframe: Timeframe) -> datetime:
    return bar.time + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])


def _price_for_exit(side: str, bar: ShadowBar, *, buy: bool) -> float:
    """Return the side-aware bid/ask approximation for OHLC data."""

    spread = bar.spread_price
    if spread is None:
        raise ValueError("bar spread unavailable")
    return (bar.close + spread) if (side == "SELL" and buy) else bar.close


def _triggered(side: str, bar: ShadowBar, stop: float, target: float) -> tuple[bool, bool]:
    """Return ``(hit_stop, hit_target)`` using bid OHLC plus bar spread."""
    if bar.spread_price is None:
        raise ValueError("bar spread unavailable")
    if side == "BUY":
        return bar.low <= stop, bar.high >= target
    return bar.high + bar.spread_price >= stop, bar.low <= target


def _tick_triggered(side: str, tick: ShadowTick, stop: float, target: float) -> tuple[bool, bool]:
    bid, ask = tick.bid, tick.ask
    if bid is None or ask is None:
        raise ValueError("tick bid/ask unavailable")
    if side == "BUY":
        return bid <= stop, bid >= target
    return ask >= stop, bid <= target


def _resolve_sequence(
    side: str,
    stop: float,
    target: float,
    bars: Sequence[ShadowBar],
    *,
    ticks_by_bar: Mapping[datetime, Sequence[ShadowTick]] | None = None,
    exit_mode: str = EXIT_AT_SL,
    entry_spread_price: float = 0.0,
    overshoot_price: float = 0.0,
) -> tuple[str, datetime | None, float | None, str | None]:
    """Resolve a post-entry sequence, drilling into M1/ticks on collisions."""
    for bar in bars:
        try:
            hit_stop, hit_target = _triggered(side, bar, stop, target)
        except ValueError as exc:
            return "UNRESOLVED", None, None, str(exc)
        if not (hit_stop or hit_target):
            continue
        if hit_stop and hit_target:
            ticks = (ticks_by_bar or {}).get(bar.time, ())
            if ticks:
                for tick in ticks:
                    try:
                        tick_stop, tick_target = _tick_triggered(side, tick, stop, target)
                    except ValueError as exc:
                        return "AMBIGUOUS", bar.time, None, str(exc)
                    if tick_stop and tick_target:
                        return "AMBIGUOUS", tick.time, None, "both barriers on one tick"
                    if tick_stop:
                        return "SL", tick.time, _stop_fill_price(
                            side, bar, stop, exit_mode=exit_mode,
                            entry_spread_price=entry_spread_price,
                            overshoot_price=overshoot_price,
                        ), None
                    if tick_target:
                        return "TP", tick.time, target, None
            return "AMBIGUOUS", bar.time, None, "both barriers hit; tick order unavailable"
        if hit_stop:
            return "SL", bar.time, _stop_fill_price(
                side, bar, stop, exit_mode=exit_mode,
                entry_spread_price=entry_spread_price,
                overshoot_price=overshoot_price,
            ), None
        return "TP", bar.time, target, None
    return "", None, None, None


def _resolve_r(side: str, entry: float, price: float, risk: float) -> float:
    return ((price - entry) if side == "BUY" else (entry - price)) / risk


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)) and float(value) >= 0)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * min(1.0, max(0.0, quantile))
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def estimate_adverse_overshoot_95(bars: Sequence[ShadowBar], *, side: str) -> float:
    """Estimate adverse overshoot from observed, positive adverse excursions.

    Zero excursions are non-events, not zero-sized stop overshoots.  Including
    them can collapse the percentile to zero for instruments whose candles are
    usually one-directional, silently disabling conservative stop accounting.
    """
    values = [
        max(0.0, float(bar.open) - float(bar.low)) if side == "BUY"
        else max(0.0, float(bar.high) - float(bar.open))
        for bar in bars
    ]
    return _percentile([value for value in values if value > 0.0], 0.95)


def _stop_fill_price(
    side: str,
    bar: ShadowBar,
    stop: float,
    *,
    exit_mode: str,
    entry_spread_price: float,
    overshoot_price: float,
) -> float:
    """Return the research stop fill under the selected accounting mode."""
    if exit_mode == EXIT_AT_SL:
        return float(stop)
    spread = float(bar.spread_price or 0.0)
    executable_open = float(bar.open) if side == "BUY" else float(bar.open) + spread
    opens_through = executable_open <= stop if side == "BUY" else executable_open >= stop
    adverse = -1.0 if side == "BUY" else 1.0
    if opens_through:
        fill = min(float(stop), executable_open) if side == "BUY" else max(float(stop), executable_open)
    else:
        fill = float(stop) + adverse * max(0.0, float(overshoot_price))
    if exit_mode == EXIT_CONSERVATIVE_SLIPPAGE:
        spread_widening = max(0.0, spread - float(entry_spread_price))
        fill += adverse * (max(0.0, float(overshoot_price)) + spread_widening)
    return fill


def plan_geometry_r(outcome: ShadowOutcome, *, pessimistic: bool = False) -> float | None:
    """Calculate R from entry, SL, TP, and the realized exit price."""
    if outcome.status == "AMBIGUOUS":
        return -1.0 if pessimistic else 0.0
    if outcome.entry_price is None:
        return None
    risk = abs(float(outcome.entry_price) - float(outcome.stop_loss))
    if risk <= 0 or not math.isfinite(risk):
        return None
    if outcome.status == "TP":
        price = float(outcome.outcome_price if outcome.outcome_price is not None else outcome.take_profit)
    elif outcome.status == "SL":
        price = float(outcome.outcome_price if outcome.outcome_price is not None else outcome.stop_loss)
    elif outcome.status == "TIMEOUT" and outcome.outcome_price is not None:
        price = float(outcome.outcome_price)
    else:
        return None
    return _resolve_r(outcome.side, float(outcome.entry_price), price, risk)


def _record_plan_geometry_r(row: Mapping[str, Any], *, pessimistic: bool = False) -> float | None:
    if row["status"] == "AMBIGUOUS":
        return -1.0 if pessimistic else 0.0
    entry = row.get("entry_price")
    if entry is None:
        return None
    risk = abs(float(entry) - float(row["stop_loss"]))
    if risk <= 0 or not math.isfinite(risk):
        return None
    if row["status"] == "TP":
        price = row.get("outcome_price") if row.get("outcome_price") is not None else row["take_profit"]
    elif row["status"] == "SL":
        price = row.get("outcome_price") if row.get("outcome_price") is not None else row["stop_loss"]
    elif row["status"] == "TIMEOUT":
        price = row.get("outcome_price")
        if price is None:
            return None
    else:
        return None
    return _resolve_r(str(row["side"]), float(entry), float(price), risk)


def resolve_signal(
    signal: SignalSpec,
    bars: Sequence[ShadowBar],
    *,
    detail_bars_by_parent: Mapping[datetime, Sequence[ShadowBar]] | None = None,
    ticks_by_parent: Mapping[datetime, Sequence[ShadowTick]] | None = None,
    source: str,
    exit_mode: str = EXIT_AT_SL,
    overshoot_price: float | None = None,
) -> ShadowOutcome:
    """Resolve one directional signal without broker mutation."""
    if exit_mode not in EXIT_MODES:
        raise ValueError(f"unknown shadow exit mode: {exit_mode}")
    overshoot = max(0.0, float(overshoot_price or 0.0))
    ordered = sorted(bars, key=lambda item: item.time)
    next_index = next((index for index, bar in enumerate(ordered) if bar.time >= signal.signal_close), None)
    if next_index is None:
        return ShadowOutcome(
            source=source, signal_id=signal.signal_id, symbol=signal.symbol,
            timeframe=signal.timeframe.value, side=signal.side,
            legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
            signal_close=signal.signal_close, entry_time=None, entry_price=None,
            stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            status="UNRESOLVED", outcome_time=None, outcome_price=None,
            gross_r=None, spread_cost_price=None, net_r=None,
            unresolved_reason="next candle open unavailable", ambiguity_detail=None,
            exit_mode=exit_mode,
        )
    entry_bar = ordered[next_index]
    if entry_bar.spread_price is None:
        return ShadowOutcome(
            source=source, signal_id=signal.signal_id, symbol=signal.symbol,
            timeframe=signal.timeframe.value, side=signal.side,
            legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
            signal_close=signal.signal_close, entry_time=entry_bar.time,
            entry_price=None, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            status="UNRESOLVED", outcome_time=None, outcome_price=None,
            gross_r=None, spread_cost_price=None, net_r=None,
            unresolved_reason="next-open spread unavailable", ambiguity_detail=None,
            exit_mode=exit_mode,
        )
    entry = entry_bar.open + entry_bar.spread_price if signal.side == "BUY" else entry_bar.open
    risk = (entry - signal.stop_loss) if signal.side == "BUY" else (signal.stop_loss - entry)
    if risk <= 0 or not math.isfinite(risk):
        return ShadowOutcome(
            source=source, signal_id=signal.signal_id, symbol=signal.symbol,
            timeframe=signal.timeframe.value, side=signal.side,
            legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
            signal_close=signal.signal_close, entry_time=entry_bar.time,
            entry_price=entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            status="UNRESOLVED", outcome_time=None, outcome_price=None,
            gross_r=None, spread_cost_price=entry_bar.spread_price,
            net_r=None, unresolved_reason="stop is not valid for next-open entry",
            ambiguity_detail=None,
            exit_mode=exit_mode,
        )

    end_index = min(len(ordered), next_index + signal.horizon_bars)
    horizon = ordered[next_index:end_index]
    parent_map = detail_bars_by_parent or {}
    tick_map = ticks_by_parent or {}
    for parent in horizon:
        detail = parent_map.get(parent.time)
        if detail:
            detail_ticks = {
                detail_bar.time: tick_map.get(parent.time, ())
                for detail_bar in detail
            }
            status, when, price, detail_reason = _resolve_sequence(
                signal.side, signal.stop_loss, signal.take_profit, sorted(detail, key=lambda item: item.time),
                ticks_by_bar=detail_ticks, exit_mode=exit_mode,
                entry_spread_price=entry_bar.spread_price, overshoot_price=overshoot,
            )
        else:
            status, when, price, detail_reason = _resolve_sequence(
                signal.side, signal.stop_loss, signal.take_profit, [parent],
                ticks_by_bar={parent.time: tick_map.get(parent.time, ())}, exit_mode=exit_mode,
                entry_spread_price=entry_bar.spread_price, overshoot_price=overshoot,
            )
        if not status:
            continue
        if status == "UNRESOLVED":
            return ShadowOutcome(
                source=source, signal_id=signal.signal_id, symbol=signal.symbol,
                timeframe=signal.timeframe.value, side=signal.side,
                legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
                signal_close=signal.signal_close, entry_time=entry_bar.time,
                entry_price=entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                status=status, outcome_time=when, outcome_price=None,
                gross_r=None, spread_cost_price=entry_bar.spread_price,
                net_r=None, unresolved_reason=detail_reason,
                ambiguity_detail=None,
                exit_mode=exit_mode,
            )
        if status == "AMBIGUOUS":
            return ShadowOutcome(
                source=source, signal_id=signal.signal_id, symbol=signal.symbol,
                timeframe=signal.timeframe.value, side=signal.side,
                legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
                signal_close=signal.signal_close, entry_time=entry_bar.time,
                entry_price=entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
                status=status, outcome_time=when, outcome_price=None,
                gross_r=None, spread_cost_price=entry_bar.spread_price,
                net_r=None, unresolved_reason=None,
                ambiguity_detail=detail_reason,
                exit_mode=exit_mode,
            )
        resolved_price = price if price is not None else (signal.take_profit if status == "TP" else signal.stop_loss)
        net_r = _resolve_r(signal.side, entry, resolved_price, risk)
        return ShadowOutcome(
            source=source, signal_id=signal.signal_id, symbol=signal.symbol,
            timeframe=signal.timeframe.value, side=signal.side,
            legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
            signal_close=signal.signal_close, entry_time=entry_bar.time,
            entry_price=entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            status=status, outcome_time=when, outcome_price=price,
            gross_r=net_r, spread_cost_price=entry_bar.spread_price,
            net_r=net_r, unresolved_reason=None, ambiguity_detail=None,
            exit_mode=exit_mode,
        )

    last = horizon[-1] if horizon else entry_bar
    if last.spread_price is None:
        return ShadowOutcome(
            source=source, signal_id=signal.signal_id, symbol=signal.symbol,
            timeframe=signal.timeframe.value, side=signal.side,
            legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
            signal_close=signal.signal_close, entry_time=entry_bar.time,
            entry_price=entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            status="UNRESOLVED", outcome_time=None, outcome_price=None,
            gross_r=None, spread_cost_price=entry_bar.spread_price,
            net_r=None, unresolved_reason="timeout mark-to-market spread unavailable",
            ambiguity_detail=None,
            exit_mode=exit_mode,
        )
    mark = last.close if signal.side == "BUY" else last.close + last.spread_price
    net_r = _resolve_r(signal.side, entry, mark, risk)
    return ShadowOutcome(
        source=source, signal_id=signal.signal_id, symbol=signal.symbol,
        timeframe=signal.timeframe.value, side=signal.side,
        legacy_score=signal.legacy_score, institutional_score=signal.institutional_score,
        signal_close=signal.signal_close, entry_time=entry_bar.time,
        entry_price=entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
        status="TIMEOUT", outcome_time=_bar_close_time(last, signal.timeframe),
        outcome_price=mark, gross_r=net_r, spread_cost_price=entry_bar.spread_price,
        net_r=net_r, unresolved_reason=None, ambiguity_detail=None,
        exit_mode=exit_mode,
    )


class ShadowOutcomeStore:
    """Durable, source-separated store for shadow outcomes."""

    def __init__(self, path: str | Path = "state/shadow_outcomes.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS shadow_outcomes (
                    source TEXT NOT NULL,
                    signal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    side TEXT NOT NULL,
                    legacy_score INTEGER,
                    institutional_score INTEGER,
                    signal_close TEXT NOT NULL,
                    entry_time TEXT,
                    entry_price REAL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    status TEXT NOT NULL,
                    outcome_time TEXT,
                    outcome_price REAL,
                    gross_r REAL,
                    spread_cost_price REAL,
                    net_r REAL,
                    unresolved_reason TEXT,
                    ambiguity_detail TEXT,
                    resolver_version TEXT NOT NULL,
                    entry_assumption TEXT NOT NULL,
                    resolved_at TEXT NOT NULL,
                    split TEXT,
                    exit_mode TEXT NOT NULL DEFAULT 'at_sl',
                    PRIMARY KEY (source, signal_id)
                )"""
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(shadow_outcomes)")}
            if "split" not in columns:
                conn.execute("ALTER TABLE shadow_outcomes ADD COLUMN split TEXT")
            if "exit_mode" not in columns:
                conn.execute("ALTER TABLE shadow_outcomes ADD COLUMN exit_mode TEXT NOT NULL DEFAULT 'at_sl'")

    def upsert(self, outcomes: Iterable[ShadowOutcome]) -> int:
        rows = [item.to_record() for item in outcomes]
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ",".join("?" for _ in columns)
        update = ",".join(f"{column}=excluded.{column}" for column in columns if column not in {"source", "signal_id"})
        with sqlite3.connect(self.path) as conn:
            conn.executemany(
                f"INSERT INTO shadow_outcomes ({','.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(source,signal_id) DO UPDATE SET {update}",
                [[row[column] for column in columns] for row in rows],
            )
        return len(rows)

    def report(self, *, source: str | None = None) -> dict[str, Any]:
        query = "SELECT * FROM shadow_outcomes"
        args: tuple[Any, ...] = ()
        if source:
            query += " WHERE source=?"
            args = (source,)
        query += " ORDER BY signal_close, signal_id"
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute(query, args).fetchall()]

        groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = (
                row["side"], row["timeframe"], row["symbol"],
                row.get("split") or ("live" if row["source"] == "live" else "unassigned"),
                "UNAVAILABLE" if row["legacy_score"] is None else str(row["legacy_score"]),
            )
            groups[key].append(row)

        def rate_ci(successes: int, trials: int) -> list[float] | None:
            if trials <= 0:
                return None
            z = 1.96
            p = successes / trials
            denominator = 1 + z * z / trials
            centre = (p + z * z / (2 * trials)) / denominator
            radius = z * ((p * (1 - p) / trials + z * z / (4 * trials * trials)) ** 0.5) / denominator
            return [max(0.0, centre - radius) * 100, min(1.0, centre + radius) * 100]

        def mean_ci(values: list[float]) -> list[float] | None:
            if len(values) < 2:
                return None
            mean = sum(values) / len(values)
            margin = 1.96 * (stdev(values) / (len(values) ** 0.5))
            return [mean - margin, mean + margin]

        def metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
            counts = {status: sum(row["status"] == status for row in items) for status in sorted(OUTCOME_STATUSES)}
            wins_losses = counts["TP"] + counts["SL"]
            decided = [
                row for row in items
                if row["status"] in {"TP", "SL", "TIMEOUT"}
                and _record_plan_geometry_r(row) is not None
            ]
            r_values = [float(_record_plan_geometry_r(row)) for row in decided]
            pessimistic_denominator = counts["TP"] + counts["SL"] + counts["AMBIGUOUS"]
            pessimistic_r_values = r_values + ([-1.0] * counts["AMBIGUOUS"])
            timestamps = sorted(_utc(row["signal_close"]) for row in items)
            span_days = ((timestamps[-1] - timestamps[0]).total_seconds() / 86400 + 1) if timestamps else None
            return {
                "count": len(items),
                "signal_count": len(items),
                "resolved_trade_count": len(decided),
                "signals_per_day": (len(items) / span_days) if span_days else None,
                "status_counts": counts,
                "win_rate_percent": (100.0 * counts["TP"] / wins_losses) if wins_losses else None,
                "win_rate_ci95_percent": rate_ci(counts["TP"], wins_losses),
                "pessimistic_win_rate_percent": (100.0 * counts["TP"] / pessimistic_denominator) if pessimistic_denominator else None,
                "pessimistic_win_rate_ci95_percent": rate_ci(counts["TP"], pessimistic_denominator),
                "average_r_including_timeouts": (sum(r_values) / len(r_values)) if r_values else None,
                "average_r_neutral": (sum(r_values) / len(r_values)) if r_values else None,
                "average_r_neutral_ci95": mean_ci(r_values),
                "average_r_pessimistic": (sum(pessimistic_r_values) / len(pessimistic_r_values)) if pessimistic_r_values else None,
                "average_r_pessimistic_ci95": mean_ci(pessimistic_r_values),
                "sample_status": "sufficient sample" if len(decided) >= 30 else "insufficient sample",
                "r_basis": "PLAN_GEOMETRY",
            }

        grouped = []
        for key in sorted(groups):
            side, timeframe, symbol, split, legacy_score = key
            grouped.append({"side": side, "timeframe": timeframe, "symbol": symbol, "split": split, "legacy_score": legacy_score, **metrics(groups[key])})
        instrument_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            instrument_groups[row["symbol"]].append(row)
        signals_per_day_by_instrument = {}
        for symbol, items in instrument_groups.items():
            dates = sorted(_utc(row["signal_close"]) for row in items)
            days = ((dates[-1] - dates[0]).total_seconds() / 86400 + 1) if dates else 0
            signals_per_day_by_instrument[symbol] = len(items) / days if days else None
        return {
            "resolver_version": RESOLVER_VERSION,
            "entry_assumption": ENTRY_ASSUMPTION,
            "r_basis": "PLAN_GEOMETRY",
            "source": source or "all",
            "total": len(rows),
            "status_counts": {status: sum(row["status"] == status for row in rows) for status in sorted(OUTCOME_STATUSES)},
            "unresolved_count": sum(row["status"] == "UNRESOLVED" for row in rows),
            "ambiguous_count": sum(row["status"] == "AMBIGUOUS" for row in rows),
            "timeout_count": sum(row["status"] == "TIMEOUT" for row in rows),
            "signals_per_day_by_instrument": signals_per_day_by_instrument,
            "groups": grouped,
        }


def signal_spec_from_setup(setup_id: str, payload: Mapping[str, Any]) -> SignalSpec | None:
    """Build a resolver input from a persisted dashboard setup."""
    side = str(payload.get("direction", "")).upper()
    if side not in {"BUY", "SELL"}:
        return None
    try:
        timeframe = Timeframe(str(payload["timeframe"]).upper())
        close = _utc(payload["candle_close_time"])
        stop = float(payload["stop_loss"])
        target = float(payload["targets"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    expires = payload.get("expires_at")
    expires_at = _utc(expires) if expires else None
    # ``expires_at`` is retained as provenance from the dashboard event, but
    # the old one-candle expiry must not silently turn into the resolver
    # horizon.  Future persisted plans may opt into an explicit horizon.
    nested_plan = payload.get("trade_plan")
    nested_horizon = nested_plan.get("horizon_bars") if isinstance(nested_plan, Mapping) else None
    horizon_raw = payload.get("horizon_bars", nested_horizon if nested_horizon is not None else DEFAULT_HORIZON_BARS)
    try:
        horizon = int(horizon_raw)
    except (TypeError, ValueError):
        horizon = DEFAULT_HORIZON_BARS
    if horizon <= 0:
        horizon = DEFAULT_HORIZON_BARS
    legacy = payload.get("legacy_score", payload.get("legacy_confidence"))
    institutional = payload.get("confidence_score")
    return SignalSpec(
        signal_id=setup_id, symbol=str(payload.get("symbol", "UNKNOWN")), timeframe=timeframe,
        side=side, signal_close=close, stop_loss=stop, take_profit=target,
        legacy_score=int(legacy) if legacy is not None else None,
        institutional_score=int(institutional) if institutional is not None else None,
        expires_at=expires_at, horizon_bars=horizon,
    )


def load_live_setup_specs(path: str | Path = "state/dashboard_paper.sqlite3") -> list[SignalSpec]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT setup_id,payload FROM market_setups ORDER BY rowid ASC").fetchall()
    result: list[SignalSpec] = []
    for setup_id, raw_payload in rows:
        try:
            spec = signal_spec_from_setup(setup_id, json.loads(raw_payload))
        except (TypeError, json.JSONDecodeError):
            spec = None
        if spec is not None:
            result.append(spec)
    return result


def replay_cached_series(
    *,
    store: CandleStore,
    symbol: str,
    timeframe: Timeframe,
    provider: str | None = None,
    minimum_history: int = 220,
) -> tuple[list[SignalSpec], list[ShadowBar], str | None]:
    """Replay the canonical live-fidelity signal generator on cached bars."""
    candles = store.load_candles(symbol, timeframe, provider=provider)
    return replay_shadow_bars(
        symbol=symbol, timeframe=timeframe, bars=bars_from_candles(candles),
        minimum_history=minimum_history,
    )


def replay_shadow_bars(
    *,
    symbol: str,
    timeframe: Timeframe,
    bars: Sequence[ShadowBar],
    minimum_history: int = 220,
    as_of: datetime | None = None,
) -> tuple[list[SignalSpec], list[ShadowBar], str | None]:
    """Replay on a spread-preserving cache using closed bars only."""
    cutoff = as_of or datetime.now(timezone.utc)
    closed_bars = [
        bar for bar in sorted(bars, key=lambda item: item.time)
        if _bar_close_time(bar, timeframe) <= cutoff
    ]
    if len(closed_bars) < minimum_history:
        return [], closed_bars, f"insufficient cached history ({len(closed_bars)} < {minimum_history})"
    frame = pd.DataFrame([
        {"time": bar.time, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}
        for bar in closed_bars
    ])
    enriched = calculate_indicators(frame)
    specs: list[SignalSpec] = []
    # Directional eligibility is decided by the legacy signal branch before
    # structure/liquidity metadata is computed.  This exact, vectorized
    # prefilter lets us invoke the canonical generator on every possible
    # directional candidate while avoiding millions of known WAIT calls.
    atr = enriched["ATR"]
    atr_average = atr.rolling(500, min_periods=15).mean()
    bullish_regime = (
        (enriched["close"] > enriched["EMA50"])
        & (enriched["EMA50"] > enriched["EMA200"])
        & (enriched["RSI"] > 50)
    )
    bearish_regime = (
        (enriched["close"] < enriched["EMA50"])
        & (enriched["EMA50"] < enriched["EMA200"])
        & (enriched["RSI"] < 50)
    )
    candidate_mask = (
        (bullish_regime | bearish_regime)
        & (enriched["RSI"] > 60)
        & (atr > atr_average)
        & (atr <= atr_average * 1.5)
    )
    candidate_indices = [
        index for index in range(minimum_history - 1, len(closed_bars))
        if bool(candidate_mask.iloc[index])
    ]
    for index in candidate_indices:
        # The live paper path evaluates the latest 500 closed observations;
        # retaining that same rolling boundary avoids cumulative-history
        # lookahead and keeps replay cost bounded per candle.
        history = calculate_indicators(
            frame.iloc[max(0, index - 499) : index + 1].copy()
        )
        regime = detect_regime(history)
        signal = generate_trading_signal(history, symbol, regime=regime, include_details=True)
        side = str(signal.get("signal", "")).upper()
        if side not in {"BUY", "SELL"}:
            continue
        last = closed_bars[index]
        plan = signal.get("trade_plan")
        if plan is None or not plan.is_valid():
            continue
        signal_close = last.time + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
        specs.append(
            SignalSpec(
                signal_id=hashlib.sha256(f"replay:{symbol}:{timeframe.value}:{signal_close.isoformat()}".encode()).hexdigest()[:32],
                symbol=symbol, timeframe=timeframe, side=side, signal_close=signal_close,
                stop_loss=float(plan.stop_loss), take_profit=float(plan.take_profit),
                legacy_score=int(signal.get("confidence", 0)),
                institutional_score=(
                    int(signal["confidence_breakdown"].total)
                    if hasattr(signal.get("confidence_breakdown"), "total")
                    else (
                        int(signal["confidence_breakdown"].get("total"))
                        if isinstance(signal.get("confidence_breakdown"), Mapping)
                        and signal["confidence_breakdown"].get("total") is not None
                        else None
                    )
                ),
            )
        )
    return specs, closed_bars, None


def structural_broker_order_free(source_path: str | Path | None = None) -> bool:
    """AST check used by tests to keep this module data-only."""
    path = Path(source_path) if source_path else Path(__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            if any(name == "execution" or name.startswith("execution.") for name in names):
                return False
        if isinstance(node, ast.Attribute) and node.attr == "submit_order":
            return False
    return True
