"""Replay the fixed 5,000 PainX 1200 M1 BUY plans from historical quotes."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import random
from statistics import mean

import MetaTrader5 as mt5
import numpy as np

from broker.mt5_telemetry import verified_weltrade_demo_telemetry
from broker.types import Timeframe
from config.settings import get_settings
from research.sequential_replay import _trade_r, build_random_specs
from research.shadow_outcomes import (
    DEFAULT_HORIZON_BARS, EXIT_GAP_AWARE, resolve_signal,
)
from research.simulator_validation import load_validation_inputs
from research.tick_quote_replay import TickReplayOutcome


def _replay_numpy(spec, raw) -> TickReplayOutcome:
    """Vectorized equivalent of replay_buy_plan for the multi-million-tick audit."""
    valid = raw[(raw["bid"] > 0) & (raw["ask"] >= raw["bid"])]
    boundary = int(spec.signal_close.timestamp() * 1000)
    horizon = boundary + spec.horizon_bars * 60_000
    if not len(valid):
        return TickReplayOutcome(spec.signal_id, "UNRESOLVED", None, None, None, None, None,
                                 "entry quote unavailable", None, None, None, True)
    entry_row = valid[0]
    entry = float(entry_row["ask"])
    entry_ms = int(entry_row["time_msc"])
    risk = entry - spec.stop_loss
    if risk <= 0:
        return TickReplayOutcome(spec.signal_id, "UNRESOLVED", spec.signal_close, entry, None, None, None,
                                 "stop invalid for executable ask entry", entry_ms-boundary, None, None, True)
    path = valid[valid["time_msc"] <= horizon]
    gaps = np.diff(path["time_msc"]) if len(path) > 1 else np.asarray([], dtype=np.int64)
    max_gap = int(np.max(gaps)) if len(gaps) else 0
    hits = np.flatnonzero((path["bid"] <= spec.stop_loss) | (path["bid"] >= spec.take_profit))
    if len(hits):
        quote = path[int(hits[0])]
        price = float(quote["bid"])
        status = "SL" if price <= spec.stop_loss else "TP"
        when = datetime.fromtimestamp(int(quote["time_msc"])/1000, tz=timezone.utc)
        entry_time = datetime.fromtimestamp(entry_ms/1000, tz=timezone.utc)
        return TickReplayOutcome(spec.signal_id, status, entry_time, entry, when, price,
                                 (price-entry)/risk, None, entry_ms-boundary, None, max_gap,
                                 entry_ms-boundary > 2000 or max_gap > 2000)
    timeout_rows = valid[valid["time_msc"] >= horizon]
    if not len(timeout_rows):
        return TickReplayOutcome(spec.signal_id, "UNRESOLVED", spec.signal_close, entry, None, None, None,
                                 "timeout quote unavailable", entry_ms-boundary, None, max_gap, True)
    quote = timeout_rows[0]
    price = float(quote["bid"])
    timeout_ms = int(quote["time_msc"])-horizon
    return TickReplayOutcome(
        spec.signal_id, "TIMEOUT", datetime.fromtimestamp(entry_ms/1000, tz=timezone.utc), entry,
        datetime.fromtimestamp(int(quote["time_msc"])/1000, tz=timezone.utc), price,
        (price-entry)/risk, None, entry_ms-boundary, timeout_ms, max_gap,
        entry_ms-boundary > 2000 or timeout_ms > 2000 or max_gap > 2000,
    )


def _distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "min": None, "p05": None, "median": None, "p95": None, "max": None}
    a = np.asarray(values, dtype=float)
    return {"count": len(values), "mean": float(np.mean(a)), "min": float(np.min(a)),
            "p05": float(np.quantile(a, .05)), "median": float(np.quantile(a, .5)),
            "p95": float(np.quantile(a, .95)), "max": float(np.max(a))}


def _day_block_ci(rows: list[tuple[date, float]], *, iterations: int = 2000) -> list[float] | None:
    by_day: dict[date, list[float]] = defaultdict(list)
    for day, value in rows:
        by_day[day].append(value)
    days = sorted(by_day)
    if not days:
        return None
    width = min(3, len(days))
    rng = random.Random(1200)
    estimates = []
    for _ in range(iterations):
        sample = []
        while len(sample) < len(days):
            start = rng.randrange(0, len(days)-width+1)
            sample.extend(days[start:start+width])
        values = [r for day in sample[:len(days)] for r in by_day[day]]
        estimates.append(mean(values))
    return [float(np.quantile(estimates, .025)), float(np.quantile(estimates, .975))]


async def run() -> dict:
    settings = get_settings()
    _, series = load_validation_inputs(settings)
    item = series[("PAINX 1200", Timeframe.M1)]
    candidates = build_random_specs(item, count=5000, side_counts={"BUY": 5000}, seed=41007,
                                    horizon=DEFAULT_HORIZON_BARS)
    start = min(c.spec.signal_close for c in candidates) - timedelta(minutes=1)
    end = max(c.spec.signal_close for c in candidates) + timedelta(minutes=DEFAULT_HORIZON_BARS + 1)
    by_day = defaultdict(list)
    for candidate in candidates:
        by_day[candidate.spec.signal_close.date()].append(candidate)
    tick_outcomes = []
    comparison = {"exact_stop": [], "opening_gap": [], "stress_40_634": []}
    classification = Counter()
    tick_count = 0
    telemetry = verified_weltrade_demo_telemetry(settings)
    await telemetry.connect()
    try:
        for day_candidates in by_day.values():
            chunk_start = min(c.spec.signal_close for c in day_candidates)
            chunk_end = max(c.spec.signal_close for c in day_candidates) + timedelta(minutes=DEFAULT_HORIZON_BARS + 1)
            raw = await asyncio.to_thread(mt5.copy_ticks_range, "PainX 1200", chunk_start, chunk_end, mt5.COPY_TICKS_ALL)
            raw = np.asarray(raw if raw is not None else [])
            tick_count += len(raw)
            for candidate in day_candidates:
                spec = candidate.spec
                left = int(np.searchsorted(raw["time_msc"], int(spec.signal_close.timestamp()*1000), side="left")) if len(raw) else 0
                right_boundary = int((spec.signal_close + timedelta(minutes=spec.horizon_bars)).timestamp()*1000)
                right = int(np.searchsorted(raw["time_msc"], right_boundary+60_000, side="right")) if len(raw) else 0
                tick = _replay_numpy(spec, raw[left:right])
                tick_outcomes.append(tick)
                bars = item.slice_for(spec.signal_close, spec.horizon_bars)
                exact = resolve_signal(spec, bars, source="tick-compare-exact")
                opening = resolve_signal(spec, bars, source="tick-compare-opening", exit_mode=EXIT_GAP_AWARE, overshoot_price=0.0)
                stress = resolve_signal(spec, bars, source="tick-compare-stress", exit_mode=EXIT_GAP_AWARE, overshoot_price=40.63399999999966)
                for name, outcome in (("exact_stop", exact), ("opening_gap", opening), ("stress_40_634", stress)):
                    value = _trade_r(outcome)
                    if value is not None:
                        comparison[name].append(value)
                classification[(exact.status, tick.status)] += 1
    finally:
        await telemetry.disconnect()

    resolved = [out for out in tick_outcomes if out.net_r is not None]
    daily: dict[str, list[float]] = defaultdict(list)
    for out in resolved:
        daily[out.entry_time.date().isoformat()].append(float(out.net_r))
    stop_r = [float(out.net_r) for out in resolved if out.status == "SL"]
    result = {
        "diagnostic_id": "painx1200-m1-buy-tick-quote-replay-v1",
        "separate_from_locked_forward_test": True,
        "plans": len(candidates), "horizon_bars": DEFAULT_HORIZON_BARS,
        "entry_rule": "first valid timestamped ask at or after next-bar boundary",
        "exit_rule": "first subsequent bid satisfying TP or SL; timeout uses first valid bid at/after 20-bar boundary",
        "fill_warning": "First observed executable quotes are not actual broker fills; the hypothetical plans generated no broker orders.",
        "tick_coverage": {"start": start.isoformat(), "end": end.isoformat(), "ticks_loaded_across_day_chunks": tick_count},
        "outcome_counts": dict(Counter(out.status for out in tick_outcomes)),
        "quote_quality": {
            "plans_flagged_with_gap_over_2s": sum(out.has_quote_gap for out in tick_outcomes),
            "unresolved_reasons": dict(Counter(out.unresolved_reason for out in tick_outcomes if out.unresolved_reason)),
            "maximum_quote_gap_ms": _distribution([float(out.maximum_quote_gap_ms) for out in tick_outcomes if out.maximum_quote_gap_ms is not None]),
            "entry_delay_ms": _distribution([float(out.entry_delay_ms) for out in tick_outcomes if out.entry_delay_ms is not None]),
        },
        "tick_net_plan_geometry_r": _distribution([float(out.net_r) for out in resolved]),
        "stop_loss_tail_r": {
            **_distribution(stop_r),
            "share_below_minus_1_5": sum(v < -1.5 for v in stop_r)/len(stop_r) if stop_r else None,
            "share_below_minus_2": sum(v < -2 for v in stop_r)/len(stop_r) if stop_r else None,
            "share_below_minus_3": sum(v < -3 for v in stop_r)/len(stop_r) if stop_r else None,
        },
        "three_utc_day_block_bootstrap_ci95_mean_r": _day_block_ci([(out.entry_time.date(), float(out.net_r)) for out in resolved]),
        "daily": [{"date": day, "count": len(values), "net_r": sum(values), "mean_r": mean(values)} for day, values in sorted(daily.items())],
        "comparators": {name: _distribution(values) for name, values in comparison.items()},
        "exact_candle_status_to_tick_status": [
            {"candle_status": old, "tick_status": new, "count": count}
            for (old, new), count in sorted(classification.items())
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("state/painx1200_m1_tick_replay.json"))
    args = parser.parse_args()
    result = asyncio.run(run())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(args.report), "plans": result["plans"],
        "outcome_counts": result["outcome_counts"],
        "mean_r": result["tick_net_plan_geometry_r"]["mean"],
        "ci95": result["three_utc_day_block_bootstrap_ci95_mean_r"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
