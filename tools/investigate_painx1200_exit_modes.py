"""Reproducible, broker-free audit of PainX 1200 M1 stop accounting."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from broker.types import Timeframe
from research.sequential_replay import build_random_specs, _trade_r
from research.shadow_outcomes import (
    DEFAULT_HORIZON_BARS,
    EXIT_AT_SL,
    EXIT_CONSERVATIVE_SLIPPAGE,
    EXIT_GAP_AWARE,
    estimate_adverse_overshoot_95,
    resolve_signal,
)
from research.simulator_validation import _all_shadow_bars, load_validation_inputs
from config.settings import get_settings


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("state/painx1200_m1_exit_investigation.json"))
    args = parser.parse_args()
    _, series = load_validation_inputs(get_settings())
    item = series[("PAINX 1200", Timeframe.M1)]
    candidates = build_random_specs(
        item, count=5000, side_counts={"BUY": 5000}, seed=41007,
        horizon=DEFAULT_HORIZON_BARS,
    )
    all_bars = _all_shadow_bars(item)
    by_time = {bar.time: bar for bar in all_bars}
    overshoot = estimate_adverse_overshoot_95(all_bars, side="BUY")
    mode_names = {
        "exact_stop": EXIT_AT_SL,
        "gap_aware": EXIT_GAP_AWARE,
        "conservative": EXIT_CONSERVATIVE_SLIPPAGE,
    }
    outcomes = {name: [] for name in mode_names}
    opening_gaps = 0
    intrabar_crossings = 0
    widening: list[float] = []
    representatives: dict[str, dict] = {}
    for candidate in candidates:
        bars = item.slice_for(candidate.spec.signal_close, DEFAULT_HORIZON_BARS)
        resolved = {
            name: resolve_signal(
                candidate.spec, bars, source=f"exit-audit-{name}",
                exit_mode=mode, overshoot_price=overshoot,
            )
            for name, mode in mode_names.items()
        }
        for name, outcome in resolved.items():
            outcomes[name].append(outcome)
        audited = resolved["gap_aware"]
        if audited.status == "SL" and audited.outcome_time is not None:
            stop_bar = by_time[audited.outcome_time]
            entry_bar = next(bar for bar in bars if bar.time >= candidate.spec.signal_close)
            opens_through = stop_bar.open <= candidate.spec.stop_loss
            opening_gaps += int(opens_through)
            intrabar_crossings += int(not opens_through)
            widening.append(max(0.0, float(stop_bar.spread_price or 0.0) - float(entry_bar.spread_price or 0.0)))
            kind = "opening_gap" if opens_through else "intrabar_crossing"
            if kind not in representatives:
                representatives[kind] = {
                    "signal_id": candidate.spec.signal_id,
                    "signal_close": candidate.spec.signal_close.isoformat(),
                    "entry_bar_open": entry_bar.open,
                    "entry_spread": entry_bar.spread_price,
                    "entry_price": audited.entry_price,
                    "stop_loss": candidate.spec.stop_loss,
                    "take_profit": candidate.spec.take_profit,
                    "stop_bar_time": stop_bar.time.isoformat(),
                    "stop_bar_open": stop_bar.open,
                    "stop_bar_low": stop_bar.low,
                    "stop_bar_spread": stop_bar.spread_price,
                    "spread_widening": widening[-1],
                    "modes": {
                        name: {"status": out.status, "exit_price": out.outcome_price, "net_r": _trade_r(out)}
                        for name, out in resolved.items()
                    },
                }
        elif audited.status == "TIMEOUT" and "timeout" not in representatives:
            representatives["timeout"] = {
                "signal_id": candidate.spec.signal_id,
                "signal_close": candidate.spec.signal_close.isoformat(),
                "entry_price": audited.entry_price,
                "stop_loss": candidate.spec.stop_loss,
                "take_profit": candidate.spec.take_profit,
                "modes": {
                    name: {"status": out.status, "exit_price": out.outcome_price, "net_r": _trade_r(out)}
                    for name, out in resolved.items()
                },
            }
    report = {
        "instrument": "PAINX 1200", "timeframe": "M1", "side": "BUY",
        "samples": len(candidates), "horizon_bars": DEFAULT_HORIZON_BARS,
        "adverse_overshoot_price_p95_positive_excursions": overshoot,
        "adverse_excursion_population": {
            "all_bars": len(all_bars),
            "positive_excursion_bars": sum(bar.open > bar.low for bar in all_bars),
        },
        "by_mode": {
            name: {
                "status_counts": dict(Counter(out.status for out in rows)),
                "average_plan_geometry_r": mean(value for out in rows if (value := _trade_r(out)) is not None),
            }
            for name, rows in outcomes.items()
        },
        "stop_path": {
            "sl_hits": opening_gaps + intrabar_crossings,
            "opens_beyond_sl": opening_gaps,
            "intrabar_sl_crossings": intrabar_crossings,
            "spread_widening_price": {
                "nonzero_count": sum(value > 0 for value in widening),
                "minimum": min(widening) if widening else None,
                "median": _quantile(widening, 0.5),
                "p95": _quantile(widening, 0.95),
                "maximum": max(widening) if widening else None,
            },
        },
        "representative_trades": representatives,
        "routing": "All three modes use the same candidates, bars, planner geometry, horizon, and resolve_signal call; only exit_mode differs.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
