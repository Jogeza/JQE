"""Read-only ungated forward shadow sampler.

This module creates hypothetical BUY and SELL plans only.  It has no broker
gateway or execution import.  Plans are later resolved by the existing
broker-order-free shadow resolver.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from broker.types import TIMEFRAME_SECONDS, Timeframe
from broker.types import ClosedMarketObservation
from intelligence.trade_plan import TradePlanBuilder
from research.shadow_outcomes import (
    DEFAULT_HORIZON_BARS,
    EXIT_GAP_AWARE,
    ShadowBar,
    SignalSpec,
    estimate_adverse_overshoot_95,
)


SAMPLER_VERSION = "forward-ungated-shadow-v1"
SAMPLE_EVERY_CLOSED_BARS = 20


def gap_aware_resolver_kwargs(spec: SignalSpec, bars: list[ShadowBar]) -> dict[str, Any]:
    """Return forward-safe gap-aware options using only pre-signal history."""
    prior = [bar for bar in bars if bar.time < spec.signal_close]
    return {
        "exit_mode": EXIT_GAP_AWARE,
        "overshoot_price": estimate_adverse_overshoot_95(prior, side=spec.side),
    }


@dataclass(frozen=True, slots=True)
class SamplerResult:
    plans_created: int
    skipped_overlap: int
    skipped_invalid_plan: int


class ForwardShadowSamplerStore:
    """Durable queue and closed-bar counters for hypothetical plans."""

    def __init__(self, path: str | Path = "state/forward_shadow.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """CREATE TABLE IF NOT EXISTS sampler_cursor (
                    scope TEXT PRIMARY KEY,
                    closed_count INTEGER NOT NULL,
                    last_closed_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS plans (
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    side TEXT NOT NULL,
                    signal_close TEXT NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    legacy_score INTEGER,
                    institutional_score INTEGER,
                    horizon_bars INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PLANNED',
                    sampler_version TEXT NOT NULL
                )"""
            )

    def _scope(self, symbol: str, timeframe: Timeframe) -> str:
        return f"{symbol.upper()}|{timeframe.value}"

    def _cursor(self, scope: str) -> tuple[int, datetime] | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT closed_count,last_closed_at FROM sampler_cursor WHERE scope=?", (scope,)).fetchone()
        if row is None:
            return None
        return int(row[0]), datetime.fromisoformat(row[1])

    def _latest_plan_time(self, symbol: str, timeframe: Timeframe, side: str) -> datetime | None:
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT signal_close FROM plans WHERE symbol=? AND timeframe=? AND side=? ORDER BY signal_close DESC LIMIT 1",
                (symbol.upper(), timeframe.value, side),
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def _advance_cursor(self, scope: str, closed_count: int, closed_at: datetime) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                "INSERT INTO sampler_cursor VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET closed_count=excluded.closed_count,last_closed_at=excluded.last_closed_at",
                (scope, closed_count, closed_at.isoformat()),
            )

    def append_for_closed_bar(
        self,
        *,
        observation: ClosedMarketObservation,
        signal: Mapping[str, Any],
    ) -> SamplerResult:
        """Count one closed bar and sample both sides every 20 bars."""
        symbol = observation.canonical_symbol.upper()
        timeframe = observation.timeframe
        scope = self._scope(symbol, timeframe)
        prior = self._cursor(scope)
        if prior is not None and observation.closed_at <= prior[1]:
            return SamplerResult(0, 0, 0)
        closed_count = (prior[0] if prior else 0) + 1
        self._advance_cursor(scope, closed_count, observation.closed_at)
        if closed_count % SAMPLE_EVERY_CLOSED_BARS:
            return SamplerResult(0, 0, 0)

        intelligence = dict(signal.get("intelligence") or {})
        plan_base = {
            "confidence": 0,
            "quality": "FORWARD_UNGATED_SHADOW",
            "score": 0,
            "reasons": ["READ_ONLY_UNGATED_FORWARD_SHADOW"],
        }
        price = float(observation.close)
        created = 0
        skipped_overlap = 0
        skipped_invalid = 0
        interval = TIMEFRAME_SECONDS[timeframe]
        for side in ("BUY", "SELL"):
            plan = TradePlanBuilder().build(
                symbol=symbol,
                intelligence=intelligence,
                signal_dict={**plan_base, "signal": side},
                price=price,
            )
            if not plan.is_valid():
                skipped_invalid += 1
                continue
            previous = self._latest_plan_time(symbol, timeframe, side)
            if previous is not None and observation.closed_at < previous + timedelta(seconds=interval * DEFAULT_HORIZON_BARS):
                skipped_overlap += 1
                continue
            signal_id = f"forward-ungated:{symbol}:{timeframe.value}:{side}:{observation.closed_at.isoformat()}"
            spec = SignalSpec(
                signal_id=signal_id, symbol=symbol, timeframe=timeframe, side=side,
                signal_close=observation.closed_at,
                stop_loss=float(plan.stop_loss), take_profit=float(plan.take_profit),
                legacy_score=None, institutional_score=None,
                horizon_bars=DEFAULT_HORIZON_BARS,
            )
            with sqlite3.connect(self.path) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO plans
                    (signal_id,symbol,timeframe,side,signal_close,stop_loss,take_profit,
                     legacy_score,institutional_score,horizon_bars,status,sampler_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        spec.signal_id, spec.symbol, spec.timeframe.value, spec.side,
                        spec.signal_close.isoformat(), spec.stop_loss, spec.take_profit,
                        None, None, spec.horizon_bars, "PLANNED", SAMPLER_VERSION,
                    ),
                )
                created += int(conn.total_changes > 0)
        return SamplerResult(created, skipped_overlap, skipped_invalid)

    def load_specs(self) -> list[SignalSpec]:
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT signal_id,symbol,timeframe,side,signal_close,stop_loss,take_profit,legacy_score,institutional_score,horizon_bars FROM plans WHERE status IN ('PLANNED','RESOLVED') ORDER BY signal_close,signal_id"
            ).fetchall()
        result: list[SignalSpec] = []
        for row in rows:
            try:
                result.append(SignalSpec(
                    signal_id=str(row[0]), symbol=str(row[1]), timeframe=Timeframe(str(row[2])),
                    side=str(row[3]), signal_close=datetime.fromisoformat(str(row[4])),
                    stop_loss=float(row[5]), take_profit=float(row[6]),
                    legacy_score=None if row[7] is None else int(row[7]),
                    institutional_score=None if row[8] is None else int(row[8]),
                    horizon_bars=int(row[9]),
                ))
            except (TypeError, ValueError):
                continue
        return result
