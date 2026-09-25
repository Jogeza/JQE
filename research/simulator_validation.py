"""Broker-order-free null controls and resolver validation.

This module deliberately reuses the canonical TradePlanBuilder and
shadow-outcome resolver.  It contains no gateway or execution dependency.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
import random
from statistics import mean, stdev
from typing import Any, Mapping, Sequence

import numpy as np

from broker.types import TIMEFRAME_SECONDS, Timeframe
from research import sequential_replay as replay
from research.sequential_replay import (
    PersistedCandidate,
    SeriesArrays,
    SequentialTrade,
    accepted_sequential_trades,
    build_random_specs,
    build_stratified_random_specs_from_counts,
    family_for,
    load_persisted_candidates,
    load_series_arrays,
    load_watch_pairs,
    sequential_report,
    simulate_sequential,
    _cost_and_reward,
    _trade_r,
)
from research.shadow_outcomes import (
    DEFAULT_HORIZON_BARS,
    EXIT_AT_SL,
    EXIT_CONSERVATIVE_SLIPPAGE,
    EXIT_GAP_AWARE,
    ShadowBar,
    ShadowOutcome,
    estimate_adverse_overshoot_95,
    resolve_signal,
)


def _ci(values: Sequence[float]) -> list[float] | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    return [ordered[int(0.025 * (len(ordered) - 1))], ordered[int(0.975 * (len(ordered) - 1))]]


def _se(values: Sequence[float]) -> float | None:
    return (stdev(values) / math.sqrt(len(values))) if len(values) > 1 else None


def _outcome_summary(outcomes: Sequence[ShadowOutcome]) -> dict[str, Any]:
    accepted = [item for item in outcomes if item.status in {"TP", "SL", "TIMEOUT", "AMBIGUOUS"} and item.entry_time is not None]
    neutral = [value for item in accepted if (value := _trade_r(item)) is not None]
    pessimistic = [value for item in accepted if (value := _trade_r(item, pessimistic=True)) is not None]
    costs = [value for item in accepted if (value := _cost_and_reward(item)[0]) is not None]
    decided = sum(item.status in {"TP", "SL"} for item in accepted)
    wins = sum(item.status == "TP" for item in accepted)
    return {
        "entries": len(accepted),
        "status_counts": dict(Counter(item.status for item in accepted)),
        "gross_win_rate_percent": (100.0 * wins / decided) if decided else None,
        "average_r": mean(neutral) if neutral else None,
        "average_r_pessimistic": mean(pessimistic) if pessimistic else None,
        "average_spread_cost_r": mean(costs) if costs else None,
        "sample_se_r": _se(neutral),
    }


def _series_summary(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    means = [row["average_r"] for row in runs if row.get("average_r") is not None]
    wins = [row["gross_win_rate_percent"] for row in runs if row.get("gross_win_rate_percent") is not None]
    totals = [row["total_net_r"] for row in runs if row.get("total_net_r") is not None]
    return {
        "seeds": len(runs),
        "entries_mean": mean([row["entries"] for row in runs]) if runs else None,
        "gross_win_rate_percent": mean(wins) if wins else None,
        "gross_win_rate_se": _se(wins),
        "average_r": mean(means) if means else None,
        "average_r_se": _se(means),
        "total_net_r_mean": mean(totals) if totals else None,
        "total_net_r_ci95": _ci(totals),
        "runs": list(runs),
    }


def _strata_from_strategy(trades: Sequence[SequentialTrade]) -> Counter[tuple[str, Timeframe, date]]:
    strata: Counter[tuple[str, Timeframe, date]] = Counter()
    for trade in trades:
        if trade.spec.side == "BUY" and trade.outcome.entry_time is not None:
            strata[(trade.spec.symbol, trade.spec.timeframe, trade.outcome.entry_time.date())] += 1
    return strata


def _reverse_series(item: SeriesArrays) -> SeriesArrays:
    """Reverse time while reversing each candle's open/close orientation."""
    return SeriesArrays(
        symbol=item.symbol, timeframe=item.timeframe, times=item.times.copy(),
        opens=item.closes[::-1].copy(), highs=item.highs[::-1].copy(),
        lows=item.lows[::-1].copy(), closes=item.opens[::-1].copy(),
        spreads=item.spreads[::-1].copy(), atr=item.atr[::-1].copy(),
        split_epoch=item.split_epoch,
    )


def _driftless_series(observed: SeriesArrays, *, seed: int, step_sigma_atr: float = 0.75) -> SeriesArrays:
    """Create a zero-drift OHLC path using observed ATR and spread arrays."""
    rng = random.Random(seed)
    finite_atr = [float(value) for value in observed.atr if math.isfinite(float(value)) and float(value) > 0]
    fallback_atr = float(np.median(finite_atr)) if finite_atr else 1.0
    base = 100.0
    opens = np.empty_like(observed.opens)
    highs = np.empty_like(observed.highs)
    lows = np.empty_like(observed.lows)
    closes = np.empty_like(observed.closes)
    previous = base
    for index in range(len(observed.times)):
        opens[index] = previous
        raw_atr = float(observed.atr[index])
        atr = raw_atr if math.isfinite(raw_atr) and raw_atr > 0 else fallback_atr
        # Keep the null path positive with a zero-drift log walk.  The local
        # price scale is still set by the observed ATR array, while the
        # planner and resolver remain the canonical implementations.
        log_sigma = max(atr * step_sigma_atr / max(previous, 1e-9), 1e-9)
        close = previous * math.exp(rng.gauss(0.0, min(log_sigma, 1.0)))
        closes[index] = close
        highs[index] = max(previous, close)
        lows[index] = min(previous, close)
        previous = close
    return SeriesArrays(
        symbol=observed.symbol, timeframe=observed.timeframe, times=observed.times.copy(),
        opens=opens, highs=highs, lows=lows, closes=closes,
        spreads=observed.spreads.copy(), atr=observed.atr.copy(),
        split_epoch=observed.split_epoch,
    )


def driftless_monte_carlo(
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    seeds: int = 50,
    samples_per_series: int = 500,
    horizon: int = DEFAULT_HORIZON_BARS,
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    ordered_series = sorted(series.items(), key=lambda item: (item[0][0], item[0][1].value))
    for pair_index, (pair, observed) in enumerate(ordered_series):
        finite_atr_all = [float(value) for value in observed.atr if math.isfinite(float(value)) and float(value) > 0]
        fallback_atr = float(np.median(finite_atr_all)) if finite_atr_all else 1.0
        runs: list[dict[str, Any]] = []
        for seed in range(seeds):
            candidates = build_random_specs(
                observed, count=samples_per_series, side_counts={"BUY": samples_per_series},
                seed=seed + 7001, horizon=horizon,
            )
            rng = random.Random(seed + 100003 * (1 + pair_index))
            outcomes = []
            for candidate in candidates:
                epoch = int(candidate.spec.signal_close.timestamp())
                start = int(np.searchsorted(observed.times, epoch, side="left"))
                if start >= len(observed.times):
                    continue
                raw_atr = float(observed.atr[start - 1]) if start > 0 else float("nan")
                atr = raw_atr if math.isfinite(raw_atr) and raw_atr > 0 else fallback_atr
                # Start exactly at the planner's signal-close reference price;
                # using the real next open here would leak historical gap
                # drift into the supposedly driftless null.
                previous = float(observed.closes[start - 1]) if start > 0 else float(observed.opens[start])
                bars: list[ShadowBar] = []
                detail_bars: dict[datetime, list[ShadowBar]] = {}
                substeps = 8
                for pos in range(start, min(len(observed.times), start + horizon)):
                    open_price = previous
                    spread = float(observed.spreads[pos])
                    parent_time = datetime.fromtimestamp(int(observed.times[pos]), tz=timezone.utc)
                    subbars: list[ShadowBar] = []
                    sub_previous = open_price
                    for substep in range(substeps):
                        sub_close = max(1e-9, sub_previous + rng.gauss(0.0, max(atr * 0.75 / math.sqrt(substeps), 1e-9)))
                        sub_time = parent_time + timedelta(microseconds=substep)
                        subbars.append(ShadowBar(
                            time=sub_time, open=sub_previous,
                            high=max(sub_previous, sub_close), low=min(sub_previous, sub_close),
                            close=sub_close,
                            spread_price=(spread if math.isfinite(spread) else None), source="driftless-subbar",
                        ))
                        sub_previous = sub_close
                    close_price = sub_previous
                    parent = ShadowBar(
                        time=parent_time, open=open_price, high=max(open_price, close_price),
                        low=min(open_price, close_price), close=close_price,
                        spread_price=(spread if math.isfinite(spread) else None), source="driftless",
                    )
                    bars.append(parent)
                    detail_bars[parent_time] = subbars
                    previous = close_price
                outcomes.append(resolve_signal(candidate.spec, bars, detail_bars_by_parent=detail_bars, source="driftless"))
            summary = _outcome_summary(outcomes)
            runs.append(summary)
        rows[f"{pair[0]}|{pair[1].value}"] = _series_summary(runs)
    return {"horizon_bars": horizon, "seeds": seeds, "samples_per_series": samples_per_series, "by_series": rows}


def stratified_direction_controls(
    candidates: Sequence[PersistedCandidate],
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    seeds: int = 50,
    horizon: int = DEFAULT_HORIZON_BARS,
    per_instrument_cap: int = 20,
) -> dict[str, Any]:
    strategy_trades, _ = accepted_sequential_trades(
        candidates, series, horizon=horizon, global_cap=20,
        per_instrument_cap=per_instrument_cap, use_stored_outcome=True,
    )
    strata = _strata_from_strategy(strategy_trades)
    result: dict[str, Any] = {"seeds": seeds, "horizon_bars": horizon, "strata": "symbol|timeframe|UTC entry day", "controls": {}}
    for label, control_series, side in (
        ("BUY_real_data", series, "BUY"),
        ("SELL_real_data", series, "SELL"),
        ("BUY_time_reversed", {pair: _reverse_series(item) for pair, item in series.items()}, "BUY"),
    ):
        runs = []
        for seed in range(seeds):
            random_candidates, target = build_stratified_random_specs_from_counts(
                control_series, strata, seed=seed, horizon=horizon, side=side,
            )
            report = simulate_sequential(
                random_candidates, control_series, horizon=horizon,
                global_cap=20, per_instrument_cap=per_instrument_cap,
                use_stored_outcome=False, bootstrap_iterations=0,
            )
            # The resolver cache is useful within one run but must not retain
            # hundreds of thousands of seed-specific outcomes.
            replay._FAST_OUTCOME_CACHE.clear()
            runs.append({
                "seed": seed, "target": target, "entries": report["metrics"]["entries"],
                "total_net_r": report["metrics"]["total_net_r"],
                "win_rate_percent": report["metrics"]["win_rate_percent"],
                "max_drawdown_r": report["max_drawdown_r"],
            })
        result["controls"][label] = {
            "direction": side, "summary": _series_summary([
                {"entries": row["entries"], "average_r": (row["total_net_r"] / row["entries"] if row["entries"] else None),
                 "gross_win_rate_percent": row["win_rate_percent"], "total_net_r": row["total_net_r"]}
                for row in runs
            ]),
        }
    return result


def observed_no_gate_expectancy(
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    samples_per_series: int = 5000,
    horizon: int = DEFAULT_HORIZON_BARS,
) -> dict[str, Any]:
    """Use observed bars and the canonical planner with no confidence gate."""
    from research.shadow_outcomes import resolve_signal
    rows: dict[str, Any] = {}
    for pair, item in sorted(series.items(), key=lambda entry: (entry[0][0], entry[0][1].value)):
        side_rows: dict[str, Any] = {}
        for side in ("BUY", "SELL"):
            candidates = build_random_specs(
                item, count=samples_per_series, side_counts={side: samples_per_series},
                seed=31007 + (0 if side == "BUY" else 1), horizon=horizon,
            )
            outcomes = [resolve_signal(candidate.spec, item.slice_for(candidate.spec.signal_close, horizon), source="observed-no-gate") for candidate in candidates]
            summary = _outcome_summary(outcomes)
            side_rows[side] = summary
        rows[f"{pair[0]}|{pair[1].value}"] = side_rows
    return {"horizon_bars": horizon, "samples_per_series": samples_per_series, "by_series": rows}


def _all_shadow_bars(item: SeriesArrays) -> list[ShadowBar]:
    return [
        ShadowBar(
            time=datetime.fromtimestamp(int(item.times[index]), tz=timezone.utc),
            open=float(item.opens[index]), high=float(item.highs[index]),
            low=float(item.lows[index]), close=float(item.closes[index]),
            spread_price=(None if not math.isfinite(float(item.spreads[index])) else float(item.spreads[index])),
            source="mt5-cache",
        )
        for index in range(len(item.times))
    ]


def _outcome_r(outcome: ShadowOutcome) -> float | None:
    return _trade_r(outcome)


def _mode_distribution(outcomes: Sequence[ShadowOutcome]) -> dict[str, Any]:
    accepted = [item for item in outcomes if item.entry_time is not None and item.status in {"TP", "SL", "TIMEOUT", "AMBIGUOUS"}]
    sl_losses = [_outcome_r(item) for item in accepted if item.status == "SL"]
    sl_losses = [float(value) for value in sl_losses if value is not None]
    day_totals: dict[date, float] = defaultdict(float)
    ordered = sorted(accepted, key=lambda item: (item.outcome_time or item.entry_time, item.signal_id))
    equity = peak = drawdown = 0.0
    for item in ordered:
        value = _outcome_r(item)
        if value is None:
            continue
        when = item.outcome_time or item.entry_time
        if when is not None:
            day_totals[when.date()] += value
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "sl_hit_count": len(sl_losses),
        "sl_loss_share_worse_than_minus_1_5R_percent": (100.0 * sum(value < -1.5 for value in sl_losses) / len(sl_losses)) if sl_losses else None,
        "sl_loss_share_worse_than_minus_2R_percent": (100.0 * sum(value < -2.0 for value in sl_losses) / len(sl_losses)) if sl_losses else None,
        "sl_loss_share_worse_than_minus_3R_percent": (100.0 * sum(value < -3.0 for value in sl_losses) / len(sl_losses)) if sl_losses else None,
        "worst_single_trade_r": min((_outcome_r(item) for item in accepted if _outcome_r(item) is not None), default=None),
        "worst_day_r": min(day_totals.values(), default=None),
        "max_drawdown_r": drawdown,
    }


def _four_week_blocks(outcomes: Sequence[ShadowOutcome]) -> list[dict[str, Any]]:
    resolved = [item for item in outcomes if item.entry_time is not None and item.status in {"TP", "SL", "TIMEOUT"} and _outcome_r(item) is not None]
    if not resolved:
        return []
    first_day = min((item.entry_time or item.signal_close).date() for item in resolved)
    grouped: dict[int, list[ShadowOutcome]] = defaultdict(list)
    for item in resolved:
        day = (item.entry_time or item.signal_close).date()
        grouped[(day - first_day).days // 28].append(item)
    rows: list[dict[str, Any]] = []
    last_observed_day = max((item.entry_time or item.signal_close).date() for item in resolved)
    for block, items in sorted(grouped.items()):
        start = first_day + timedelta(days=block * 28)
        scheduled_end = start + timedelta(days=27)
        observed_end = min(scheduled_end, last_observed_day)
        values = [float(_outcome_r(item)) for item in items]
        rows.append({
            "block": block + 1,
            "start_day": start.isoformat(),
            "end_day": observed_end.isoformat(),
            "full_28_calendar_days": observed_end == scheduled_end,
            "entries": len(values),
            "mean_r": mean(values),
            "mean_r_ci95_day_block_bootstrap": _day_block_bootstrap_ci(items, seed=62000 + block),
        })
    return rows


def _day_block_bootstrap_ci(
    outcomes: Sequence[ShadowOutcome], *, seed: int, block_days: int = 3,
    iterations: int = 2000,
) -> list[float] | None:
    """CI for mean trade R while keeping outcomes on a UTC day together."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for item in outcomes:
        value = _outcome_r(item)
        when = item.entry_time or item.signal_close
        if value is not None and when is not None:
            by_day[when.date()].append(float(value))
    days = sorted(by_day)
    if not days:
        return None
    width = max(1, min(block_days, len(days)))
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sampled: list[date] = []
        while len(sampled) < len(days):
            start = rng.randrange(0, len(days) - width + 1)
            sampled.extend(days[start:start + width])
        total = sum(sum(by_day[day]) for day in sampled[:len(days)])
        count = sum(len(by_day[day]) for day in sampled[:len(days)])
        estimates.append(total / count)
    return _ci(estimates)


def _summary_with_dependence_ci(outcomes: Sequence[ShadowOutcome], *, seed: int) -> dict[str, Any]:
    summary = _outcome_summary(outcomes)
    summary["mean_r_ci95_day_block_bootstrap"] = _day_block_bootstrap_ci(outcomes, seed=seed)
    summary["ci_method"] = "moving 3-UTC-day block bootstrap; all sampled outcomes on a day stay together"
    return summary


def painx_research_report(
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    *,
    samples_per_series: int = 5000,
    horizon: int = DEFAULT_HORIZON_BARS,
) -> dict[str, Any]:
    """Run PainX ungated BUY exit-mode and stability reports."""
    wanted = {pair: item for pair, item in series.items() if family_for(pair[0]) in {"PainX", "MAX PainX"}}
    modes = {
        "exit_at_sl": EXIT_AT_SL,
        "gap_aware": EXIT_GAP_AWARE,
        "conservative_slippage": EXIT_CONSERVATIVE_SLIPPAGE,
    }
    by_mode: dict[str, dict[str, Any]] = {key: {} for key in modes}
    stability: dict[str, Any] = {
        "by_series": {}, "time_reversed_by_series": {}, "time_reversed_by_family": {},
        "uncertainty_method": "moving 3-UTC-day block bootstrap (2,000 iterations)",
        "overlap_warning": "Random entries overlap heavily. Intervals cluster outcomes by day but are descriptive research intervals, not executable-portfolio uncertainty.",
        "time_reversal_definition": "Reverse candle order; for each reversed candle swap open and close while retaining high and low, reverse ATR and spread arrays in lockstep, and assign the synthetic path the original increasing UTC timestamps. Then create BUY plans and resolve them exactly as the original series. This is not an ordinary SELL control.",
    }
    for pair, item in sorted(wanted.items(), key=lambda entry: (entry[0][0], entry[0][1].value)):
        candidates = build_random_specs(
            item, count=samples_per_series, side_counts={"BUY": samples_per_series},
            seed=41007 + (0 if pair[1] is Timeframe.M1 else 1), horizon=horizon,
        )
        reference = _all_shadow_bars(item)
        overshoot = estimate_adverse_overshoot_95(reference, side="BUY")
        mode_outcomes: dict[str, list[ShadowOutcome]] = {key: [] for key in modes}
        for candidate in candidates:
            bars = item.slice_for(candidate.spec.signal_close, horizon)
            for label, exit_mode in modes.items():
                mode_outcomes[label].append(resolve_signal(
                    candidate.spec, bars, source=f"observed-no-gate-{label}",
                    exit_mode=exit_mode, overshoot_price=overshoot,
                ))
        key = f"{pair[0]}|{pair[1].value}"
        for label, outcomes in mode_outcomes.items():
            summary = _outcome_summary(outcomes)
            by_mode[label][key] = {
                "symbol": pair[0], "timeframe": pair[1].value,
                "overshoot_price_p95": overshoot,
                "summary": summary,
                "sl_loss_distribution": _mode_distribution(outcomes),
            }
        blocks = _four_week_blocks(mode_outcomes["gap_aware"])
        ordered_gap = sorted(mode_outcomes["gap_aware"], key=lambda item: item.signal_close)
        midpoint = len(ordered_gap) // 2
        stability["by_series"][key] = {
            "symbol": pair[0], "timeframe": pair[1].value,
            "exit_mode": EXIT_GAP_AWARE, "four_week_blocks": blocks,
            "first_half": _summary_with_dependence_ci(ordered_gap[:midpoint], seed=63001),
            "second_half": _summary_with_dependence_ci(ordered_gap[midpoint:], seed=63002),
            "block_mean_r": mean([row["mean_r"] for row in blocks]) if blocks else None,
        }
    # Time-reversed BUY controls are reported at family/timeframe level.
    reversed_series = {(pair[0], pair[1]): _reverse_series(item) for pair, item in wanted.items()}
    for (symbol, timeframe), item in sorted(reversed_series.items(), key=lambda entry: (entry[0][0], entry[0][1].value)):
        candidates = build_random_specs(
            item, count=samples_per_series, side_counts={"BUY": samples_per_series},
            seed=51007 + (0 if timeframe is Timeframe.M1 else 1), horizon=horizon,
        )
        outcomes = []
        overshoot = estimate_adverse_overshoot_95(_all_shadow_bars(item), side="BUY")
        for candidate in candidates:
            outcomes.append(resolve_signal(
                candidate.spec, item.slice_for(candidate.spec.signal_close, horizon),
                source="time-reversed-control", exit_mode=EXIT_GAP_AWARE,
                overshoot_price=overshoot,
            ))
        series_key = f"{symbol}|{timeframe.value}"
        reversed_summary = _summary_with_dependence_ci(outcomes, seed=64007 + len(stability["time_reversed_by_series"]))
        stability["time_reversed_by_series"][series_key] = {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "exit_mode": EXIT_GAP_AWARE,
            "overshoot_price_p95": overshoot,
            "summary": reversed_summary,
        }
        family_key = f"{family_for(symbol)}|{timeframe.value}"
        stability["time_reversed_by_family"].setdefault(family_key, []).append(reversed_summary)
    for key, values in list(stability["time_reversed_by_family"].items()):
        stability["time_reversed_by_family"][key] = {
            "series_count": len(values),
            "average_r_mean": mean([item["average_r"] for item in values if item["average_r"] is not None]) if values else None,
            "series": values,
        }
    gap_summaries = [row["summary"] for row in by_mode["gap_aware"].values()]
    positive_cells = [key for key, row in by_mode["gap_aware"].items() if (row["summary"].get("average_r") or 0.0) > 0]
    return {
        "horizon_bars": horizon,
        "samples_per_series": samples_per_series,
        "r_basis": "PLAN_GEOMETRY",
        "exit_mode_definitions": {
            "exit_at_sl": "Stop-triggered trades fill exactly at the planned SL.",
            "gap_aware": "If executable bar open crosses the stop, fill at the worse of SL and that open; otherwise apply the observed-data 95th-percentile adverse overshoot.",
            "conservative_slippage": "Gap-aware fill plus another 95th-percentile adverse overshoot and any per-bar spread widening above entry spread.",
        },
        "by_mode": by_mode,
        "stability": stability,
        "hypothesis_review": {
            "research_status": "NO_DEMONSTRATED_POSITIVE_EDGE",
            "demonstrated_positive_edge": False,
            "original_family_wide_h1_supported_by_exploratory_sample": False,
            "reason": "The equal-cell family result is negative under gap-aware exits and most instrument/timeframe cells are negative; the existing exploratory sample does not support a family-wide positive BUY effect.",
            "gap_aware_equal_cell_average_r": mean([row["average_r"] for row in gap_summaries if row.get("average_r") is not None]),
            "positive_cells": positive_cells,
            "new_exploratory_candidate_only": "PainX 1200|M1 is a post-selection candidate from this same sample. It requires a fresh untouched confirmation sample and is not confirmed here.",
            "forward_success_criteria_unchanged": {
                "minimum_resolved_non_overlapping_entries": 500,
                "minimum_distinct_entry_days": 10,
                "positive_in_both_halves": True,
                "block_bootstrap_95_ci_lower_bound_gt_zero": True,
            },
        },
    }


def resolver_audit() -> dict[str, Any]:
    return {
        "resolver_version": "shadow-resolver-v2",
        "entry_bar_high_low_scanned": True,
        "entry_bar_note": "The horizon slice starts at the next-open entry bar, so that bar can trigger a barrier.",
        "entry_spread": "BUY entry is next-open ask = open + that bar spread; SELL entry is next-open bid = open.",
        "exit_spread": "BUY exits use bid OHLC; SELL stop/timeout exits use ask approximated as bid + that bar spread; ticks override collisions when available.",
        "stop_fill_default": "At the planned SL when a stop is triggered; the production/default resolver remains at_sl.",
        "gap_aware_exit": "Research-only mode fills at the worse of the planned SL and executable bar open for an opening stop gap, otherwise uses the observed-data 95th-percentile adverse overshoot.",
        "conservative_slippage_exit": "Research-only mode adds a second 95th-percentile adverse overshoot and per-bar spread widening above entry spread.",
        "timeout": "Marked to market at the final horizon bar close with side-aware bid/ask approximation; timeout is excluded from win rate.",
        "ambiguity": "Same-bar stop/target collisions drill into ticks; without tick order they are AMBIGUOUS, neutral in the primary result and -1R pessimistically.",
        "atr_stop_lookahead": "Planner ATR is the value at the signal close, calculated with rolling indicators from rows up to that point; no future ATR is used by the planner.",
        "risk_note": "The entry-bar scan is conservative for collisions only when tick data is available; OHLC-only one-sided hits are accepted by the resolver.",
    }


def holdout_strategy_minus_control(
    candidates: Sequence[PersistedCandidate],
    series: Mapping[tuple[str, Timeframe], SeriesArrays],
    report_path: str,
    *,
    block_days: int = 3,
    iterations: int = 2000,
) -> dict[str, Any]:
    """Compare the sealed strategy holdout to stored matched-control days."""
    with open(report_path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    trades, _ = accepted_sequential_trades(
        candidates, series, horizon=DEFAULT_HORIZON_BARS,
        global_cap=20, per_instrument_cap=20, use_stored_outcome=True,
    )
    strategy_daily: dict[date, float] = defaultdict(float)
    holdout_signal_days: list[date] = []
    for trade in trades:
        if trade.split != "holdout":
            continue
        holdout_signal_days.append(trade.spec.signal_close.date())
        when = trade.outcome.outcome_time or trade.outcome.entry_time
        if when is not None:
            strategy_daily[when.date()] += trade.neutral_r
    holdout_start = min(holdout_signal_days)
    holdout_end = max(strategy_daily)
    holdout_dates = [day for day in sorted(strategy_daily) if holdout_start <= day <= holdout_end]
    controls = report["stratified_random_control"]["runs"]
    control_daily: dict[date, list[float]] = defaultdict(list)
    for run in controls:
        rows = {date.fromisoformat(row["date"]): float(row["neutral_r"]) for row in run["report"].get("daily", [])}
        for day in holdout_dates:
            control_daily[day].append(rows.get(day, 0.0))
    daily_difference = [
        strategy_daily[day] - mean(control_daily[day])
        for day in holdout_dates if control_daily[day]
    ]
    control_split_totals = [
        float(run["report"]["by_split"]["holdout"]["total_net_r"])
        for run in controls
    ]
    strategy_split_total = float(report["sequential"]["20"]["by_split"]["holdout"]["total_net_r"])
    control_split_mean = mean(control_split_totals) if control_split_totals else None
    point = strategy_split_total - control_split_mean if control_split_mean is not None else None
    rng = random.Random(90210)
    values: list[float] = []
    if daily_difference:
        length = max(1, min(block_days, len(daily_difference)))
        for _ in range(iterations):
            sampled: list[float] = []
            while len(sampled) < len(daily_difference):
                start = rng.randrange(0, len(daily_difference) - length + 1)
                sampled.extend(daily_difference[start:start + length])
            values.append(sum(sampled[:len(daily_difference)]))
    return {
        "holdout_days": len(daily_difference),
        "holdout_signal_window": [holdout_start.isoformat(), holdout_end.isoformat()],
        "strategy_holdout_net_r": strategy_split_total,
        "control_holdout_net_r_mean": control_split_mean,
        "strategy_minus_control_net_r": point,
        "aligned_daily_difference_total": sum(daily_difference),
        "block_days": block_days,
        "block_bootstrap_iterations": iterations,
        "block_bootstrap_ci95": _ci(values),
        "control_seeds": len(controls),
    }


def load_validation_inputs(settings: Any, db: str | None = None) -> tuple[list[PersistedCandidate], dict[tuple[str, Timeframe], SeriesArrays]]:
    candidates = load_persisted_candidates(db or settings.dashboard_paper_store_path.parent / "shadow_outcomes.sqlite3")
    pairs = load_watch_pairs(settings.watchlist_store_path)
    series = load_series_arrays(settings.cache_dir / "shadow_mt5_rates.sqlite3", pairs)
    return candidates, series
