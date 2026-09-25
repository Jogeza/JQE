"""Broker-order-free sequential replay and random-entry controls.

This module consumes persisted replay plans and the local MT5 rate cache.  It
does not import execution or broker gateways.  Entry, stop, target, spread,
and horizon semantics remain those of :mod:`research.shadow_outcomes`.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from broker.types import TIMEFRAME_SECONDS, Timeframe
from core.indicators import calculate_indicators
from data.watchlist import WatchlistStore
from intelligence.trade_plan import TradePlanBuilder
from research.shadow_history import ShadowHistoryStore
from research.shadow_outcomes import (
    DEFAULT_HORIZON_BARS,
    ShadowBar,
    ShadowOutcome,
    SignalSpec,
    plan_geometry_r,
    resolve_signal,
)


GLOBAL_DAILY_CAP = 20
DEFAULT_BLOCK_DAYS = 3
FAMILIES = ("FX Vol", "SFX Vol", "PainX", "MAX PainX")
_FAST_OUTCOME_CACHE: dict[tuple[Any, ...], ShadowOutcome] = {}
_STRATIFIED_ELIGIBLE_CACHE: dict[tuple[Any, ...], dict[date, list[int]]] = {}


def family_for(symbol: str) -> str:
    upper = symbol.upper()
    if upper.startswith("FX VOL"):
        return "FX Vol"
    if upper.startswith("SFX VOL"):
        return "SFX Vol"
    if upper.startswith("MAX PAINX"):
        return "MAX PainX"
    if upper.startswith("PAINX"):
        return "PainX"
    return "Other"


@dataclass(frozen=True, slots=True)
class PersistedCandidate:
    spec: SignalSpec
    split: str
    stored_outcome: ShadowOutcome


@dataclass(frozen=True, slots=True)
class SeriesArrays:
    symbol: str
    timeframe: Timeframe
    times: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    spreads: np.ndarray
    atr: np.ndarray
    split_epoch: int

    def slice_for(self, signal_close: datetime, horizon: int) -> list[ShadowBar]:
        epoch = int(signal_close.astimezone(timezone.utc).timestamp())
        index = int(np.searchsorted(self.times, epoch, side="left"))
        end = min(len(self.times), index + max(1, horizon))
        return [
            ShadowBar(
                time=datetime.fromtimestamp(int(self.times[pos]), tz=timezone.utc),
                open=float(self.opens[pos]), high=float(self.highs[pos]),
                low=float(self.lows[pos]), close=float(self.closes[pos]),
                spread_price=(None if not math.isfinite(float(self.spreads[pos])) else float(self.spreads[pos])),
                source="mt5-cache",
            )
            for pos in range(index, end)
        ]

    def random_indices(self, count: int, horizon: int, rng: random.Random) -> list[int]:
        last = len(self.times) - max(1, horizon) - 1
        valid = np.flatnonzero(
            (np.arange(len(self.times)) >= 220)
            & (np.arange(len(self.times)) <= last)
            & np.isfinite(self.atr)
            & np.isfinite(self.spreads)
        )
        if len(valid) == 0 or count <= 0:
            return []
        take = min(count, len(valid))
        return rng.sample(valid.tolist(), take)


@dataclass(frozen=True, slots=True)
class SequentialTrade:
    spec: SignalSpec
    outcome: ShadowOutcome
    split: str
    family: str
    neutral_r: float
    pessimistic_r: float
    spread_cost_r: float | None
    reward_r: float | None


def _utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _row_outcome(row: sqlite3.Row) -> ShadowOutcome:
    def dt(name: str) -> datetime | None:
        return _utc(row[name])

    return ShadowOutcome(
        source=str(row["source"]), signal_id=str(row["signal_id"]),
        symbol=str(row["symbol"]), timeframe=str(row["timeframe"]),
        side=str(row["side"]), legacy_score=row["legacy_score"],
        institutional_score=row["institutional_score"], signal_close=dt("signal_close"),
        entry_time=dt("entry_time"), entry_price=row["entry_price"],
        stop_loss=float(row["stop_loss"]), take_profit=float(row["take_profit"]),
        status=str(row["status"]), outcome_time=dt("outcome_time"),
        outcome_price=row["outcome_price"], gross_r=row["gross_r"],
        spread_cost_price=row["spread_cost_price"], net_r=row["net_r"],
        unresolved_reason=row["unresolved_reason"], ambiguity_detail=row["ambiguity_detail"],
        resolver_version=str(row["resolver_version"]),
        entry_assumption=str(row["entry_assumption"]), resolved_at=dt("resolved_at") or datetime.now(timezone.utc),
        split=row["split"],
    )


def load_persisted_candidates(path: str | Path) -> list[PersistedCandidate]:
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM shadow_outcomes WHERE source='replay' ORDER BY signal_close, signal_id"
        ).fetchall()
    result: list[PersistedCandidate] = []
    for row in rows:
        try:
            close = _utc(row["signal_close"])
            timeframe = Timeframe(str(row["timeframe"]))
            spec = SignalSpec(
                signal_id=str(row["signal_id"]), symbol=str(row["symbol"]),
                timeframe=timeframe, side=str(row["side"]), signal_close=close,
                stop_loss=float(row["stop_loss"]), take_profit=float(row["take_profit"]),
                legacy_score=None if row["legacy_score"] is None else int(row["legacy_score"]),
                institutional_score=None if row["institutional_score"] is None else int(row["institutional_score"]),
                horizon_bars=20,
            )
            outcome = _row_outcome(row)
        except (TypeError, ValueError, KeyError):
            continue
        result.append(PersistedCandidate(spec, str(row["split"] or "unassigned"), outcome))
    return result


def load_series_arrays(history_path: str | Path, pairs: Iterable[tuple[str, Timeframe]]) -> dict[tuple[str, Timeframe], SeriesArrays]:
    store = ShadowHistoryStore(history_path)
    result: dict[tuple[str, Timeframe], SeriesArrays] = {}
    for symbol, timeframe in pairs:
        bars = store.load_bars(symbol, timeframe)
        if not bars:
            continue
        frame = pd.DataFrame([
            {"time": bar.time, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}
            for bar in bars
        ])
        enriched = calculate_indicators(frame)
        split_index = max(1, int(len(bars) * 0.60))
        result[(symbol, timeframe)] = SeriesArrays(
            symbol=symbol, timeframe=timeframe,
            times=np.array([int(bar.time.timestamp()) for bar in bars], dtype=np.int64),
            opens=np.array([bar.open for bar in bars], dtype=np.float64),
            highs=np.array([bar.high for bar in bars], dtype=np.float64),
            lows=np.array([bar.low for bar in bars], dtype=np.float64),
            closes=np.array([bar.close for bar in bars], dtype=np.float64),
            spreads=np.array([
                np.nan if bar.spread_price is None else bar.spread_price for bar in bars
            ], dtype=np.float64),
            atr=np.array(enriched["ATR"].astype(float), dtype=np.float64),
            split_epoch=int(bars[split_index - 1].time.timestamp()) + TIMEFRAME_SECONDS[timeframe],
        )
    return result


def _resolve_fast(spec: SignalSpec, series: SeriesArrays, horizon: int, *, source: str) -> ShadowOutcome:
    cache_key = (
        series.symbol, series.timeframe.value, int(spec.signal_close.timestamp()),
        spec.side, round(float(spec.stop_loss), 12), round(float(spec.take_profit), 12), horizon,
    )
    cached = _FAST_OUTCOME_CACHE.get(cache_key)
    if cached is not None:
        return cached
    bars = series.slice_for(spec.signal_close, horizon)
    adjusted = SignalSpec(
        signal_id=spec.signal_id, symbol=spec.symbol, timeframe=spec.timeframe,
        side=spec.side, signal_close=spec.signal_close, stop_loss=spec.stop_loss,
        take_profit=spec.take_profit, legacy_score=spec.legacy_score,
        institutional_score=spec.institutional_score, horizon_bars=horizon,
    )
    outcome = resolve_signal(adjusted, bars, source=source)
    _FAST_OUTCOME_CACHE[cache_key] = outcome
    return outcome


def _trade_r(outcome: ShadowOutcome, *, pessimistic: bool = False) -> float | None:
    return plan_geometry_r(outcome, pessimistic=pessimistic)


def _cost_and_reward(outcome: ShadowOutcome) -> tuple[float | None, float | None]:
    if outcome.entry_price is None:
        return None, None
    risk = abs(float(outcome.entry_price) - float(outcome.stop_loss))
    if risk <= 0:
        return None, None
    cost = None if outcome.spread_cost_price is None else float(outcome.spread_cost_price) / risk
    reward = float(outcome.take_profit) - float(outcome.entry_price)
    if outcome.side == "SELL":
        reward = -reward
    return cost, reward / risk


def _accepted(outcome: ShadowOutcome) -> bool:
    return outcome.status in {"TP", "SL", "TIMEOUT", "AMBIGUOUS"} and outcome.entry_time is not None


def _simulate_trades(
    candidates: Sequence[PersistedCandidate],
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    horizon: int,
    global_cap: int = GLOBAL_DAILY_CAP,
    per_instrument_cap: int = 20,
    use_stored_outcome: bool = False,
    daily_loss_stop: float | None = None,
    consecutive_loss_breaker: int | None = None,
) -> tuple[list[SequentialTrade], Counter[str]]:
    ordered = sorted(candidates, key=lambda item: (item.spec.signal_close, item.spec.signal_id))
    open_until: dict[str, datetime | None] = {}
    global_counts: Counter[date] = Counter()
    instrument_counts: Counter[tuple[str, date]] = Counter()
    trades: list[SequentialTrade] = []
    skipped = Counter()
    daily_realized_r: Counter[date] = Counter()
    consecutive_losses = 0
    breaker_open = False
    breaker_day: date | None = None

    for candidate in ordered:
        spec = candidate.spec
        prior_release = open_until.get(spec.symbol)
        if prior_release is None and spec.symbol in open_until:
            skipped["open_unresolved"] += 1
            continue
        if prior_release is not None and spec.signal_close < prior_release:
            skipped["open_position"] += 1
            continue
        series_item = series.get((spec.symbol, spec.timeframe))
        if series_item is None:
            skipped["missing_series"] += 1
            continue
        outcome = candidate.stored_outcome if use_stored_outcome and horizon == 20 else _resolve_fast(
            spec, series_item, horizon, source="sequential"
        )
        if not _accepted(outcome):
            skipped["not_entered_or_unresolved"] += 1
            continue
        entry_day = outcome.entry_time.date()
        # A consecutive-loss breaker is a same-day safety variant here.  It
        # must not carry a prior day's losses into the next session.
        if breaker_day != entry_day:
            breaker_day = entry_day
            consecutive_losses = 0
            breaker_open = False
        if breaker_open:
            skipped["consecutive_loss_breaker"] += 1
            continue
        if daily_loss_stop is not None and daily_realized_r[entry_day] <= float(daily_loss_stop):
            skipped["daily_loss_stop"] += 1
            continue
        if global_counts[entry_day] >= global_cap:
            skipped["global_daily_cap"] += 1
            continue
        instrument_day = (spec.symbol, entry_day)
        if instrument_counts[instrument_day] >= per_instrument_cap:
            skipped["instrument_daily_cap"] += 1
            continue
        global_counts[entry_day] += 1
        instrument_counts[instrument_day] += 1
        release = outcome.outcome_time
        open_until[spec.symbol] = release
        neutral = _trade_r(outcome)
        pessimistic = _trade_r(outcome, pessimistic=True)
        cost, reward = _cost_and_reward(outcome)
        if neutral is None or pessimistic is None:
            skipped["invalid_r"] += 1
            continue
        trade = SequentialTrade(
            spec=spec, outcome=outcome, split=(candidate.split if candidate.split in {"exploration", "holdout"} else (
                "exploration" if int(outcome.signal_close.timestamp()) < series_item.split_epoch else "holdout"
            )), family=family_for(spec.symbol), neutral_r=neutral,
            pessimistic_r=pessimistic, spread_cost_r=cost, reward_r=reward,
        )
        trades.append(trade)
        daily_realized_r[entry_day] += neutral
        if consecutive_loss_breaker is not None:
            if pessimistic < 0:
                consecutive_losses += 1
                if consecutive_losses >= int(consecutive_loss_breaker):
                    breaker_open = True
            else:
                consecutive_losses = 0

    return trades, skipped


def simulate_sequential(
    candidates: Sequence[PersistedCandidate],
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    horizon: int,
    global_cap: int = GLOBAL_DAILY_CAP,
    per_instrument_cap: int = 20,
    use_stored_outcome: bool = False,
    daily_loss_stop: float | None = None,
    consecutive_loss_breaker: int | None = None,
    bootstrap_iterations: int = 2000,
) -> dict[str, Any]:
    trades, skipped = _simulate_trades(
        candidates, series, horizon=horizon, global_cap=global_cap,
        per_instrument_cap=per_instrument_cap, use_stored_outcome=use_stored_outcome,
        daily_loss_stop=daily_loss_stop,
        consecutive_loss_breaker=consecutive_loss_breaker,
    )
    report = sequential_report(
        trades, skipped=skipped, global_cap=global_cap,
        per_instrument_cap=per_instrument_cap, horizon=horizon,
        bootstrap_iterations=bootstrap_iterations,
    )
    report["sequential_variants"] = {
        "daily_loss_stop_r": daily_loss_stop,
        "consecutive_loss_breaker": consecutive_loss_breaker,
        "loss_definition": "pessimistic_r < 0; AMBIGUOUS counts as a loss for breaker only",
    }
    return report


def accepted_sequential_trades(
    candidates: Sequence[PersistedCandidate],
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    horizon: int = DEFAULT_HORIZON_BARS,
    global_cap: int = GLOBAL_DAILY_CAP,
    per_instrument_cap: int = 20,
    use_stored_outcome: bool = True,
) -> tuple[list[SequentialTrade], Counter[str]]:
    """Return the exact sequential strategy entries used as control strata."""
    return _simulate_trades(
        candidates, series, horizon=horizon, global_cap=global_cap,
        per_instrument_cap=per_instrument_cap, use_stored_outcome=use_stored_outcome,
    )


def _ci(values: Sequence[float]) -> list[float] | None:
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    return [ordered[int(0.025 * (len(ordered) - 1))], ordered[int(0.975 * (len(ordered) - 1))]]


def _daily_rows(trades: Sequence[SequentialTrade]) -> list[dict[str, Any]]:
    grouped: dict[date, list[SequentialTrade]] = defaultdict(list)
    for trade in trades:
        when = trade.outcome.outcome_time or trade.outcome.entry_time
        if when is not None:
            grouped[when.date()].append(trade)
    return [
        {
            "date": day.isoformat(),
            "trades": len(items),
            "wins": sum(item.outcome.status == "TP" for item in items),
            "decided": sum(item.outcome.status in {"TP", "SL"} for item in items),
            "neutral_r": sum(item.neutral_r for item in items),
            "pessimistic_r": sum(item.pessimistic_r for item in items),
        }
        for day, items in sorted(grouped.items())
    ]


def block_bootstrap_win_ci(trades: Sequence[SequentialTrade], *, seed: int = 90210, block_days: int = DEFAULT_BLOCK_DAYS, iterations: int = 2000) -> list[float] | None:
    rows = _daily_rows(trades)
    if not rows:
        return None
    rng = random.Random(seed)
    if len(rows) == 1:
        decided = rows[0]["decided"]
        return [100.0 * rows[0]["wins"] / decided, 100.0 * rows[0]["wins"] / decided] if decided else None
    values: list[float] = []
    length = max(1, min(block_days, len(rows)))
    for _ in range(iterations):
        sampled: list[dict[str, Any]] = []
        while len(sampled) < len(rows):
            start = rng.randrange(0, len(rows) - length + 1)
            sampled.extend(rows[start:start + length])
        sampled = sampled[:len(rows)]
        decided = sum(item["decided"] for item in sampled)
        if decided:
            values.append(100.0 * sum(item["wins"] for item in sampled) / decided)
    return _ci(values)


def _metrics(trades: Sequence[SequentialTrade], *, bootstrap_iterations: int = 2000) -> dict[str, Any]:
    tp = sum(item.outcome.status == "TP" for item in trades)
    sl = sum(item.outcome.status == "SL" for item in trades)
    decided = tp + sl
    neutral = [item.neutral_r for item in trades]
    pessimistic = [item.pessimistic_r for item in trades]
    costs = [item.spread_cost_r for item in trades if item.spread_cost_r is not None]
    rewards = [item.reward_r for item in trades if item.reward_r is not None]
    return {
        "entries": len(trades), "status_counts": dict(Counter(item.outcome.status for item in trades)),
        "win_rate_percent": (100.0 * tp / decided) if decided else None,
        "win_rate_ci95_by_day_block_bootstrap": (block_bootstrap_win_ci(trades, iterations=bootstrap_iterations) if bootstrap_iterations > 0 else None),
        "total_net_r": sum(neutral), "total_net_r_pessimistic": sum(pessimistic),
        "average_r": mean(neutral) if neutral else None,
        "average_r_pessimistic": mean(pessimistic) if pessimistic else None,
        "average_spread_cost_r": mean(costs) if costs else None,
        "breakeven_win_rate_percent": ((1.0 + mean(costs)) / (1.0 + mean(rewards)) * 100.0) if costs and rewards and (1.0 + mean(rewards)) > 0 else None,
        "sample_status": "sufficient" if len(trades) >= 30 else "insufficient",
    }


def _equity(trades: Sequence[SequentialTrade], *, pessimistic: bool = False) -> tuple[list[dict[str, Any]], float]:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    curve = []
    for trade in sorted(trades, key=lambda item: ((item.outcome.outcome_time or item.outcome.entry_time), item.spec.signal_id)):
        equity += trade.pessimistic_r if pessimistic else trade.neutral_r
        peak = max(peak, equity)
        drawdown = peak - equity
        max_drawdown = max(max_drawdown, drawdown)
        curve.append({
            "time": (trade.outcome.outcome_time or trade.outcome.entry_time).isoformat(),
            "equity_r": equity, "drawdown_r": drawdown,
        })
    return curve, max_drawdown


def sequential_report(trades: Sequence[SequentialTrade], *, skipped: Mapping[str, int], global_cap: int, per_instrument_cap: int, horizon: int, bootstrap_iterations: int = 2000) -> dict[str, Any]:
    curve, drawdown = _equity(trades)
    pessimistic_curve, pessimistic_drawdown = _equity(trades, pessimistic=True)
    report: dict[str, Any] = {
        "horizon_bars": horizon, "global_daily_cap": global_cap,
        "per_instrument_daily_cap": per_instrument_cap,
        "accepted": len(trades), "skipped": dict(skipped), "metrics": _metrics(trades, bootstrap_iterations=bootstrap_iterations),
        "max_drawdown_r": drawdown, "max_drawdown_r_pessimistic": pessimistic_drawdown,
        "equity_curve": curve, "equity_curve_pessimistic": pessimistic_curve,
        "daily": _daily_rows(trades),
        "by_split": {}, "by_timeframe_family": {}, "by_instrument_timeframe": {}, "by_bucket": {},
    }
    for split in ("exploration", "holdout"):
        report["by_split"][split] = _metrics([item for item in trades if item.split == split], bootstrap_iterations=bootstrap_iterations)
    for timeframe in ("M1", "M5"):
        for family in FAMILIES:
            items = [item for item in trades if item.spec.timeframe.value == timeframe and item.family == family]
            report["by_timeframe_family"][f"{timeframe}|{family}"] = _metrics(items, bootstrap_iterations=bootstrap_iterations)
    instrument_groups: dict[tuple[str, str], list[SequentialTrade]] = defaultdict(list)
    for item in trades:
        instrument_groups[(item.spec.symbol, item.spec.timeframe.value)].append(item)
    for (symbol, timeframe), items in sorted(instrument_groups.items()):
        report["by_instrument_timeframe"][f"{symbol}|{timeframe}"] = _metrics(items, bootstrap_iterations=bootstrap_iterations)
    bucket_groups: dict[tuple[str, str, str, str], list[SequentialTrade]] = defaultdict(list)
    for item in trades:
        score = "UNAVAILABLE" if item.spec.legacy_score is None else str(item.spec.legacy_score)
        bucket_groups[(item.spec.timeframe.value, item.spec.symbol, item.split, score)].append(item)
    for (timeframe, symbol, split, score), items in sorted(bucket_groups.items()):
        report["by_bucket"][f"{timeframe}|{symbol}|{split}|{score}"] = _metrics(items, bootstrap_iterations=bootstrap_iterations)
    return report


def build_random_specs(
    series: SeriesArrays,
    *,
    count: int,
    side_counts: Mapping[str, int],
    seed: int,
    horizon: int,
) -> list[PersistedCandidate]:
    rng = random.Random(seed)
    indices = series.random_indices(count, horizon, rng)
    if not indices:
        return []
    side_pool = [side for side, amount in side_counts.items() for _ in range(max(0, amount))]
    if not side_pool:
        side_pool = ["BUY", "SELL"]
    builder = TradePlanBuilder()
    result: list[PersistedCandidate] = []
    total_sides = sum(side_counts.values()) or 1
    buy_weight = side_counts.get("BUY", 0) / total_sides
    step = TIMEFRAME_SECONDS[series.timeframe]
    for ordinal, index in enumerate(indices):
        side = "BUY" if rng.random() < buy_weight else "SELL"
        atr = float(series.atr[index])
        plan = builder.build(
            series.symbol,
            {"atr": atr, "trend": "UNKNOWN", "momentum": "UNKNOWN", "volatility": "UNKNOWN", "liquidity": "UNKNOWN", "regime": "UNKNOWN"},
            {"signal": side, "confidence": 0, "quality": "CONTROL", "score": 0, "reasons": []},
            float(series.closes[index]),
        )
        if not plan.is_valid():
            continue
        signal_close = datetime.fromtimestamp(int(series.times[index]) + step, tz=timezone.utc)
        split = "exploration" if int(series.times[index]) + step < series.split_epoch else "holdout"
        spec = SignalSpec(
            signal_id=hashlib.sha256(f"random:{seed}:{series.symbol}:{series.timeframe.value}:{signal_close.isoformat()}:{ordinal}".encode()).hexdigest()[:32],
            symbol=series.symbol, timeframe=series.timeframe, side=side,
            signal_close=signal_close, stop_loss=float(plan.stop_loss), take_profit=float(plan.take_profit),
            legacy_score=None, institutional_score=None, horizon_bars=horizon,
        )
        # The stored outcome is unused for random controls; it is a typed placeholder.
        placeholder = ShadowOutcome(
            source="random", signal_id=spec.signal_id, symbol=spec.symbol,
            timeframe=spec.timeframe.value, side=spec.side, legacy_score=None,
            institutional_score=None, signal_close=spec.signal_close, entry_time=None,
            entry_price=None, stop_loss=spec.stop_loss, take_profit=spec.take_profit,
            status="UNRESOLVED", outcome_time=None, outcome_price=None, gross_r=None,
            spread_cost_price=None, net_r=None, unresolved_reason="control placeholder",
            ambiguity_detail=None,
        )
        result.append(PersistedCandidate(spec, split, placeholder))
    return result


def _spec_from_index(
    series: SeriesArrays,
    index: int,
    *,
    side: str,
    seed: int,
    ordinal: int,
    horizon: int,
    label: str,
) -> PersistedCandidate | None:
    """Build a BUY/SELL control spec using the canonical planner geometry."""
    if index < 220 or index + max(1, horizon) + 1 >= len(series.times):
        return None
    atr = float(series.atr[index])
    spread = float(series.spreads[index])
    if not math.isfinite(atr) or not math.isfinite(spread):
        return None
    builder = TradePlanBuilder()
    plan = builder.build(
        series.symbol,
        {"atr": atr, "trend": "UNKNOWN", "momentum": "UNKNOWN", "volatility": "UNKNOWN", "liquidity": "UNKNOWN", "regime": "UNKNOWN"},
        {"signal": side, "confidence": 0, "quality": "CONTROL", "score": 0, "reasons": []},
        float(series.closes[index]),
    )
    if not plan.is_valid():
        return None
    step = TIMEFRAME_SECONDS[series.timeframe]
    signal_close = datetime.fromtimestamp(int(series.times[index]) + step, tz=timezone.utc)
    split = "exploration" if int(series.times[index]) + step < series.split_epoch else "holdout"
    spec = SignalSpec(
        signal_id=hashlib.sha256(f"{label}:{seed}:{series.symbol}:{series.timeframe.value}:{signal_close.isoformat()}:{ordinal}".encode()).hexdigest()[:32],
        symbol=series.symbol, timeframe=series.timeframe, side=side,
        signal_close=signal_close, stop_loss=float(plan.stop_loss), take_profit=float(plan.take_profit),
        legacy_score=None, institutional_score=None, horizon_bars=horizon,
    )
    placeholder = ShadowOutcome(
        source=label, signal_id=spec.signal_id, symbol=spec.symbol,
        timeframe=spec.timeframe.value, side=spec.side, legacy_score=None,
        institutional_score=None, signal_close=spec.signal_close, entry_time=None,
        entry_price=None, stop_loss=spec.stop_loss, take_profit=spec.take_profit,
        status="UNRESOLVED", outcome_time=None, outcome_price=None, gross_r=None,
        spread_cost_price=None, net_r=None, unresolved_reason="control placeholder",
        ambiguity_detail=None,
    )
    return PersistedCandidate(spec, split, placeholder)


def build_stratified_random_specs_from_counts(
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    strata: Mapping[tuple[str, Timeframe, date], int],
    *,
    seed: int,
    horizon: int = DEFAULT_HORIZON_BARS,
    side: str = "BUY",
) -> tuple[list[PersistedCandidate], dict[str, int]]:
    """Match strategy counts in each symbol/timeframe/UTC-day stratum.

    Random bars are drawn without replacement from the same series and UTC
    entry day.  ``requested`` and ``shortfall`` are returned so a missing
    cache day is visible instead of being silently backfilled.  ``side`` is
    explicit so the BUY and SELL mirror controls share identical strata.
    """
    if side not in {"BUY", "SELL"}:
        raise ValueError("stratified controls support BUY or SELL only")
    rng = random.Random(seed)
    result: list[PersistedCandidate] = []
    requested = 0
    shortfall = 0
    ordinal = 0
    eligible_by_pair_day: dict[tuple[str, Timeframe, date], list[int]] = {}
    pair_keys = {(symbol, timeframe) for symbol, timeframe, _ in strata}
    for symbol, timeframe in pair_keys:
        item = series.get((symbol, timeframe))
        if item is None:
            continue
        cache_key = (
            symbol, timeframe.value, int(horizon), len(item.times),
            int(item.times[0]) if len(item.times) else None,
            int(item.times[-1]) if len(item.times) else None,
        )
        grouped = _STRATIFIED_ELIGIBLE_CACHE.get(cache_key)
        if grouped is None:
            step = TIMEFRAME_SECONDS[timeframe]
            grouped = defaultdict(list)
            for index, epoch in enumerate(item.times):
                if (
                    index >= 220
                    and index + max(1, horizon) + 1 < len(item.times)
                    and math.isfinite(float(item.atr[index]))
                    and math.isfinite(float(item.spreads[index]))
                ):
                    grouped[datetime.fromtimestamp(int(epoch) + step, tz=timezone.utc).date()].append(index)
            _STRATIFIED_ELIGIBLE_CACHE[cache_key] = grouped
        for day, indexes in grouped.items():
            eligible_by_pair_day[(symbol, timeframe, day)] = indexes
    for (symbol, timeframe, day), count in sorted(strata.items(), key=lambda item: (item[0][0], item[0][1].value, item[0][2])):
        requested += count
        item = series.get((symbol, timeframe))
        if item is None:
            shortfall += count
            continue
        eligible = eligible_by_pair_day.get((symbol, timeframe, day), [])
        take = min(count, len(eligible))
        if take < count:
            shortfall += count - take
        for index in rng.sample(eligible, take):
            candidate = _spec_from_index(item, index, side=side, seed=seed, ordinal=ordinal, horizon=horizon, label=f"stratified-random-{side.lower()}")
            ordinal += 1
            if candidate is not None:
                result.append(candidate)
            else:
                shortfall += 1
    return result, {"requested": requested, "generated": len(result), "shortfall": shortfall}


def build_stratified_random_specs(
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    strategy_trades: Sequence[SequentialTrade],
    *,
    seed: int,
    horizon: int = DEFAULT_HORIZON_BARS,
    side: str = "BUY",
) -> tuple[list[PersistedCandidate], dict[str, int]]:
    strata: Counter[tuple[str, Timeframe, date]] = Counter()
    for trade in strategy_trades:
        if trade.spec.side == "BUY" and trade.outcome.entry_time is not None:
            strata[(trade.spec.symbol, trade.spec.timeframe, trade.outcome.entry_time.date())] += 1
    return build_stratified_random_specs_from_counts(series, strata, seed=seed, horizon=horizon, side=side)


def no_gate_planner_baseline(
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    horizon: int = DEFAULT_HORIZON_BARS,
) -> dict[str, Any]:
    """Compute the geometry-only null expectation for every cached instrument.

    This is not a backtest and does not inspect signal/gate outcomes.  It
    assumes an uninformative 50/50 TP/SL direction and uses the planner's
    actual reward geometry and observed spread costs from each cached series.
    """
    rows: dict[str, dict[str, Any]] = defaultdict(lambda: {"samples": 0, "costs": [], "rewards": [], "by_timeframe": {}})
    for (symbol, timeframe), item in sorted(series.items(), key=lambda entry: (entry[0][0], entry[0][1].value)):
        costs: list[float] = []
        rewards: list[float] = []
        builder = TradePlanBuilder()
        last = len(item.times) - max(1, horizon) - 2
        for index in range(220, max(220, last + 1)):
            atr = float(item.atr[index])
            spread = float(item.spreads[index])
            if not math.isfinite(atr) or not math.isfinite(spread):
                continue
            plan = builder.build(
                symbol,
                {"atr": atr, "trend": "UNKNOWN", "momentum": "UNKNOWN", "volatility": "UNKNOWN", "liquidity": "UNKNOWN", "regime": "UNKNOWN"},
                {"signal": "BUY", "confidence": 0, "quality": "CONTROL", "score": 0, "reasons": []},
                float(item.closes[index]),
            )
            if not plan.is_valid():
                continue
            risk = abs(float(plan.entry) - float(plan.stop_loss))
            if risk <= 0 or not math.isfinite(risk):
                continue
            costs.append(spread / risk)
            rewards.append(abs(float(plan.take_profit) - float(plan.entry)) / risk)
        rows[symbol]["samples"] += len(costs)
        rows[symbol]["costs"].extend(costs)
        rows[symbol]["rewards"].extend(rewards)
        rows[symbol]["by_timeframe"][timeframe.value] = {
            "samples": len(costs),
            "average_spread_cost_r": mean(costs) if costs else None,
            "planner_reward_r": mean(rewards) if rewards else None,
            "expected_gross_r_at_50pct": ((0.5 * mean(rewards) - 0.5) if rewards else None),
            "expected_net_r_at_50pct": ((0.5 * mean(rewards) - 0.5 - mean(costs)) if costs and rewards else None),
        }
    output: dict[str, Any] = {}
    for symbol, row in sorted(rows.items()):
        costs = row["costs"]
        rewards = row["rewards"]
        output[symbol] = {
            "samples": row["samples"],
            "planner_reward_r": mean(rewards) if rewards else None,
            "average_spread_cost_r": mean(costs) if costs else None,
            "expected_gross_r_at_50pct": ((0.5 * mean(rewards) - 0.5) if rewards else None),
            "expected_net_r_at_50pct": ((0.5 * mean(rewards) - 0.5 - mean(costs)) if costs and rewards else None),
            "by_timeframe": row["by_timeframe"],
        }
    return output


def summarize_random_control(
    candidates_by_seed: Mapping[int, Sequence[PersistedCandidate]],
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    horizon: int,
    global_cap: int,
    per_instrument_cap: int,
) -> dict[str, Any]:
    runs = []
    for seed, candidates in sorted(candidates_by_seed.items()):
        report = simulate_sequential(
            candidates, series, horizon=horizon, global_cap=global_cap,
            per_instrument_cap=per_instrument_cap, use_stored_outcome=False,
        )
        runs.append({"seed": seed, "accepted": report["accepted"], "total_net_r": report["metrics"]["total_net_r"], "win_rate_percent": report["metrics"]["win_rate_percent"], "max_drawdown_r": report["max_drawdown_r"]})
    values = [run["total_net_r"] for run in runs]
    wins = [run["win_rate_percent"] for run in runs if run["win_rate_percent"] is not None]
    return {
        "seeds": len(runs), "runs": runs,
        "total_net_r_distribution": {"mean": mean(values) if values else None, "ci95": _ci(values), "min": min(values) if values else None, "max": max(values) if values else None},
        "win_rate_distribution": {"mean": mean(wins) if wins else None, "ci95": _ci(wins), "min": min(wins) if wins else None, "max": max(wins) if wins else None},
    }


def load_watch_pairs(path: str | Path) -> tuple[tuple[str, Timeframe], ...]:
    return tuple((item.symbol, item.timeframe) for item in WatchlistStore(path).get_watch_pairs())
