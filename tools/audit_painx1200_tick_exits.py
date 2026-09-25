"""Read-only tick reconstruction for sampled PainX 1200 M1 BUY stops."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
from statistics import mean

import MetaTrader5 as mt5
import numpy as np

from broker.mt5_telemetry import verified_weltrade_demo_telemetry
from broker.types import Timeframe
from config.settings import get_settings
from research.sequential_replay import build_random_specs
from research.shadow_outcomes import DEFAULT_HORIZON_BARS, estimate_adverse_overshoot_95, resolve_signal
from research.simulator_validation import _all_shadow_bars, load_validation_inputs


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "median": None, "p95": None, "max": None, "mean": None}
    array = np.asarray(values, dtype=float)
    return {
        "min": float(np.min(array)), "median": float(np.quantile(array, 0.5)),
        "p95": float(np.quantile(array, 0.95)), "max": float(np.max(array)),
        "mean": float(np.mean(array)),
    }


async def run() -> dict:
    settings = get_settings()
    _, series = load_validation_inputs(settings)
    item = series[("PAINX 1200", Timeframe.M1)]
    bars = _all_shadow_bars(item)
    by_time = {bar.time: bar for bar in bars}
    candidates = build_random_specs(
        item, count=5000, side_counts={"BUY": 5000}, seed=41007,
        horizon=DEFAULT_HORIZON_BARS,
    )
    overshoot = estimate_adverse_overshoot_95(bars, side="BUY")
    stops = []
    needed_minutes: set[int] = set()
    for candidate in candidates:
        window = item.slice_for(candidate.spec.signal_close, DEFAULT_HORIZON_BARS)
        outcome = resolve_signal(candidate.spec, window, source="tick-audit")
        if outcome.status != "SL" or outcome.outcome_time is None or outcome.entry_price is None:
            continue
        epoch = int(outcome.outcome_time.timestamp())
        needed_minutes.add(epoch)
        stops.append((candidate.spec, outcome, by_time[outcome.outcome_time]))

    telemetry = verified_weltrade_demo_telemetry(settings)
    await telemetry.connect()
    try:
        start = min(bar.time for bar in bars)
        end = max(bar.time for bar in bars) + timedelta(minutes=1)
        raw = await asyncio.to_thread(mt5.copy_ticks_range, "PainX 1200", start, end, mt5.COPY_TICKS_ALL)
        deals = await asyncio.to_thread(mt5.history_deals_get, start, end, group="*PainX 1200*")
    finally:
        await telemetry.disconnect()
    raw = np.asarray(raw if raw is not None else [])
    minute_ticks: dict[int, list[dict]] = {minute: [] for minute in needed_minutes}
    if len(raw):
        minutes = (raw["time"] // 60) * 60
        filtered = raw[np.isin(minutes, np.fromiter(needed_minutes, dtype=np.int64))]
        for tick in filtered:
            minute = int(tick["time"] // 60 * 60)
            minute_ticks.setdefault(minute, []).append({
                "time": int(tick["time"]), "time_msc": int(tick["time_msc"]),
                "bid": float(tick["bid"]), "ask": float(tick["ask"]),
            })

    comparisons = []
    unidentified = 0
    for spec, outcome, bar in stops:
        ticks = sorted(minute_ticks.get(int(outcome.outcome_time.timestamp()), []), key=lambda row: row["time_msc"])
        crossing = next((tick for tick in ticks if tick["bid"] <= spec.stop_loss and tick["bid"] > 0 and tick["ask"] > 0), None)
        if crossing is None:
            unidentified += 1
            continue
        opening_gap = bar.open <= spec.stop_loss
        estimates = {
            "exact_stop": spec.stop_loss,
            "opening_gap": min(spec.stop_loss, bar.open) if opening_gap else spec.stop_loss,
            "p95": min(spec.stop_loss, bar.open) if opening_gap else spec.stop_loss - overshoot,
        }
        actual = crossing["bid"]
        risk = float(outcome.entry_price) - spec.stop_loss
        comparisons.append({
            "signal_id": spec.signal_id,
            "stop_minute": outcome.outcome_time.isoformat(),
            "opening_gap": opening_gap,
            "planned_stop": spec.stop_loss,
            "first_crossing_time_msc": crossing["time_msc"],
            "first_executable_bid": actual,
            "ask": crossing["ask"],
            "tick_spread": crossing["ask"] - crossing["bid"],
            "adverse_slippage_price": spec.stop_loss - actual,
            "actual_geometry_r": (actual - float(outcome.entry_price)) / risk,
            "estimates": estimates,
            "errors_estimate_minus_actual": {key: value - actual for key, value in estimates.items()},
        })

    def model(name: str) -> dict:
        errors = [row["errors_estimate_minus_actual"][name] for row in comparisons]
        absolute = [abs(value) for value in errors]
        return {"signed_error_price": _quantiles(errors), "absolute_error_price": _quantiles(absolute)}

    spreads = [row["tick_spread"] for row in comparisons]
    slippage = [row["adverse_slippage_price"] for row in comparisons]
    geometry = [row["actual_geometry_r"] for row in comparisons]
    deal_rows = list(deals or ())
    return {
        "instrument": "PAINX 1200", "timeframe": "M1", "side": "BUY",
        "tick_history": {
            "requested_start": min(bar.time for bar in bars).isoformat(),
            "requested_end": (max(bar.time for bar in bars) + timedelta(minutes=1)).isoformat(),
            "ticks_returned": len(raw), "stop_minutes_requested": len(needed_minutes),
            "stop_crossings_reconstructed": len(comparisons), "unidentified_stop_crossings": unidentified,
        },
        "broker_fills": {
            "account_deals_for_symbol_period": len(deal_rows),
            "stop_loss_deals": sum(getattr(deal, "reason", None) == getattr(mt5, "DEAL_REASON_SL", 4) for deal in deal_rows),
            "interpretation": "No broker fills exist because the sampled entries were hypothetical and no orders were submitted.",
        },
        "bar_overshoot_assumption": {
            "formula": "For each cached BUY bar: max(0, open_bid - low_bid); discard zeros; take p95.",
            "bars": len(bars), "positive_differences": sum(bar.open > bar.low for bar in bars),
            "p95_price": overshoot,
            "identification_warning": "This is a candle-range sensitivity parameter, not an observed stop fill.",
        },
        "reconstructed": {
            "opening_gap_counts": dict(Counter(row["opening_gap"] for row in comparisons)),
            "actual_stop_slippage_price": _quantiles(slippage),
            "actual_geometry_r": _quantiles(geometry),
            "tick_spread_price": _quantiles(spreads),
            "model_comparison": {name: model(name) for name in ("exact_stop", "opening_gap", "p95")},
            "representative_first_three": comparisons[:3],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("state/painx1200_tick_exit_audit.json"))
    args = parser.parse_args()
    report = asyncio.run(run())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
