"""Run capped sequential strategy replay and random-entry controls."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from config.settings import get_settings
from research.sequential_replay import (
    DEFAULT_HORIZON_BARS,
    GLOBAL_DAILY_CAP,
    accepted_sequential_trades,
    build_random_specs,
    build_stratified_random_specs,
    build_stratified_random_specs_from_counts,
    load_persisted_candidates,
    load_series_arrays,
    load_watch_pairs,
    no_gate_planner_baseline,
    sequential_report,
    simulate_sequential,
)


_WORKER_SERIES = None
_WORKER_CONTEXT = None


def _stratified_seed_worker(args):
    """Evaluate one independent seed in a long-lived read-only worker."""
    global _WORKER_SERIES, _WORKER_CONTEXT
    cache_path, pairs, strata_items, seed, horizon, per_cap = args
    context = (str(cache_path), tuple(pairs), tuple(strata_items))
    if _WORKER_SERIES is None or _WORKER_CONTEXT != context:
        typed_pairs = tuple((symbol, __import__("broker.types", fromlist=["Timeframe"]).Timeframe(timeframe)) for symbol, timeframe in pairs)
        _WORKER_SERIES = load_series_arrays(cache_path, typed_pairs)
        _WORKER_CONTEXT = context
    from datetime import date
    from broker.types import Timeframe
    strata = {(symbol, Timeframe(timeframe), date.fromisoformat(day)): int(count) for symbol, timeframe, day, count in strata_items}
    random_candidates, target = build_stratified_random_specs_from_counts(
        _WORKER_SERIES, strata, seed=seed, horizon=horizon,
    )
    result = simulate_sequential(
        random_candidates, _WORKER_SERIES, horizon=horizon,
        global_cap=GLOBAL_DAILY_CAP, per_instrument_cap=per_cap,
        use_stored_outcome=False, bootstrap_iterations=0,
    )
    return {"seed": seed, "target": target, "report": result}


def _random_summary(runs: list[dict]) -> dict:
    totals = [float(item["total_net_r"]) for item in runs]
    wins = [float(item["win_rate_percent"]) for item in runs if item["win_rate_percent"] is not None]
    drawdowns = [float(item["max_drawdown_r"]) for item in runs]

    def ci(values: list[float]) -> list[float] | None:
        if not values:
            return None
        values = sorted(values)
        return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]

    return {
        "seeds": len(runs),
        "runs": runs,
        "total_net_r_distribution": {"mean": mean(totals) if totals else None, "ci95": ci(totals), "min": min(totals) if totals else None, "max": max(totals) if totals else None},
        "win_rate_distribution": {"mean": mean(wins) if wins else None, "ci95": ci(wins), "min": min(wins) if wins else None, "max": max(wins) if wins else None},
        "max_drawdown_distribution": {"mean": mean(drawdowns) if drawdowns else None, "ci95": ci(drawdowns), "min": min(drawdowns) if drawdowns else None, "max": max(drawdowns) if drawdowns else None},
    }


def _distribution(runs: list[dict], field: str) -> dict:
    values = [float(row[field]) for row in runs if row.get(field) is not None]
    return {
        "mean": mean(values) if values else None,
        "ci95": _ci(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def _ci(values: list[float]) -> list[float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return [ordered[int(0.025 * (len(ordered) - 1))], ordered[int(0.975 * (len(ordered) - 1))]]


def _comparison(strategy: dict, runs: list[dict], keys: list[str]) -> dict:
    result: dict[str, dict] = {}
    for key in keys:
        if key == "full":
            strategy_metrics = strategy["metrics"]
        elif "|" in key and key in strategy.get("by_timeframe_family", {}):
            strategy_metrics = strategy["by_timeframe_family"][key]
        else:
            strategy_metrics = strategy.get("by_split", {}).get(key, {})
        control_metrics = [row["report"]["metrics"] if key == "full" else (
            row["report"].get("by_timeframe_family", {}).get(key, {}) if "|" in key else row["report"].get("by_split", {}).get(key, {})
        ) for row in runs]
        result[key] = {
            "strategy": strategy_metrics,
            "stratified_control": {
                "seeds": len(runs),
                "total_net_r": _distribution(control_metrics, "total_net_r"),
                "win_rate_percent": _distribution(control_metrics, "win_rate_percent"),
                "max_drawdown_r": _distribution(control_metrics, "max_drawdown_r") if control_metrics and "max_drawdown_r" in control_metrics[0] else None,
                "accepted": _distribution(control_metrics, "entries"),
            },
        }
    return result


def _min_lot_dollar_conversion(settings, pairs, reports: dict[str, dict]) -> dict:
    survey_path = Path("state/weltrade_cost_survey.json")
    if not survey_path.exists():
        return {"source": "UNAVAILABLE", "rows": {}}
    try:
        survey = json.loads(survey_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"source": "UNAVAILABLE", "rows": {}}
    survey_rows = {str(row.get("symbol", "")).upper(): row for row in survey.get("rows", [])}
    unique_symbols = sorted({symbol for symbol, _ in pairs})
    rows = {}
    for symbol in unique_symbols:
        row = survey_rows.get(symbol.upper())
        if row is None:
            rows[symbol] = {"status": "NO_SAVED_SURVEY_ROW"}
            continue
        by_tf = {}
        for tf in ("M1", "M5"):
            cell = row.get("timeframes", {}).get(tf, {})
            stop_risk = cell.get("min_lot_loss_usd")
            by_tf[tf] = {
                "min_lot": row.get("volume_min"),
                "min_lot_stop_risk_usd": stop_risk,
                "authorized_risk_usd_at_configured_balance": float(settings.account_balance) * float(settings.risk_percent) / 100.0,
                "min_lot_fits_authorized_risk": (stop_risk is not None and float(stop_risk) <= float(settings.account_balance) * float(settings.risk_percent) / 100.0),
            }
        rows[symbol] = {"by_timeframe": by_tf}
    variant_dollars = {}
    for variant, report in reports.items():
        converted = {}
        for key, metrics in report.get("by_instrument_timeframe", {}).items():
            symbol, timeframe = key.rsplit("|", 1)
            survey_row = survey_rows.get(symbol.upper(), {})
            cell = survey_row.get("timeframes", {}).get(timeframe, {})
            min_risk = cell.get("min_lot_loss_usd")
            converted[key] = {
                "entries": metrics.get("entries"),
                "net_r": metrics.get("total_net_r"),
                "net_dollars_at_min_lot": (float(metrics["total_net_r"]) * float(min_risk) if min_risk is not None else None),
                "min_lot_stop_risk_usd": min_risk,
            }
        variant_dollars[variant] = converted
    return {
        "source": str(survey_path),
        "configured_balance_usd": float(settings.account_balance),
        "configured_risk_percent": float(settings.risk_percent),
        "rows": rows,
        "variant_net_r_to_dollars": variant_dollars,
        "note": "R-to-dollar conversion uses the saved Weltrade minimum-lot stop-risk survey; no order or sizing gate was changed.",
    }


def run(*, db: Path, report_path: Path, random_seeds: int, include_unstratified: bool = False) -> dict:
    settings = get_settings()
    if settings.broker_execution_enabled:
        raise RuntimeError("sequential research refuses to run with broker execution enabled")
    candidates = load_persisted_candidates(db)
    pairs = load_watch_pairs(settings.watchlist_store_path)
    series = load_series_arrays(settings.cache_dir / "shadow_mt5_rates.sqlite3", pairs)
    per_cap = int(settings.max_daily_trades_per_instrument)

    by_pair: dict[tuple[str, object], list] = defaultdict(list)
    side_counts: dict[tuple[str, object], Counter] = defaultdict(Counter)
    for item in candidates:
        key = (item.spec.symbol, item.spec.timeframe)
        by_pair[key].append(item)
        side_counts[key][item.spec.side] += 1

    sequential = {}
    for horizon in (2, 12, 20, 48):
        sequential[str(horizon)] = simulate_sequential(
            candidates, series, horizon=horizon, global_cap=GLOBAL_DAILY_CAP,
            per_instrument_cap=per_cap, use_stored_outcome=(horizon == 20),
        )

    strategy_trades, _ = accepted_sequential_trades(
        candidates, series, horizon=DEFAULT_HORIZON_BARS,
        global_cap=GLOBAL_DAILY_CAP, per_instrument_cap=per_cap,
        use_stored_outcome=True,
    )

    sequential_variants = {}
    for label, kwargs in {
        "daily_loss_stop_minus_3R": {"daily_loss_stop": -3.0},
        "consecutive_loss_breaker_5": {"consecutive_loss_breaker": 5},
    }.items():
        sequential_variants[label] = simulate_sequential(
            candidates, series, horizon=DEFAULT_HORIZON_BARS,
            global_cap=GLOBAL_DAILY_CAP, per_instrument_cap=per_cap,
            use_stored_outcome=True, **kwargs,
        )

    random_runs: list[dict] = []
    base_horizon = DEFAULT_HORIZON_BARS
    if include_unstratified:
        for seed in range(random_seeds):
            random_candidates = []
            for ordinal, pair in enumerate(pairs):
                series_item = series.get(pair)
                if series_item is None:
                    continue
                random_candidates.extend(build_random_specs(
                    series_item,
                    count=len(by_pair.get(pair, ())),
                    side_counts=side_counts.get(pair, {}),
                    seed=seed * 1000003 + ordinal * 7919,
                    horizon=base_horizon,
                ))
            result = simulate_sequential(
                random_candidates, series, horizon=base_horizon,
                global_cap=GLOBAL_DAILY_CAP, per_instrument_cap=per_cap,
                use_stored_outcome=False, bootstrap_iterations=0,
            )
            random_runs.append({
                "seed": seed,
                "accepted": result["accepted"],
                "total_net_r": result["metrics"]["total_net_r"],
                "win_rate_percent": result["metrics"]["win_rate_percent"],
                "max_drawdown_r": result["max_drawdown_r"],
                "skipped": result["skipped"],
            })

    stratified_runs: list[dict] = []
    stratified_targets: list[dict] = []
    strata = Counter()
    for trade in strategy_trades:
        if trade.spec.side == "BUY" and trade.outcome.entry_time is not None:
            strata[(trade.spec.symbol, trade.spec.timeframe.value, trade.outcome.entry_time.date().isoformat())] += 1
    worker_pairs = tuple((symbol, timeframe.value) for symbol, timeframe in pairs)
    worker_args = [
        (str(settings.cache_dir / "shadow_mt5_rates.sqlite3"), worker_pairs,
         tuple((symbol, timeframe, day, count) for (symbol, timeframe, day), count in strata.items()),
         seed, base_horizon, per_cap)
        for seed in range(random_seeds)
    ]
    # Seeds are independent. Two workers keep memory bounded while avoiding a
    # 50-seed serial wall-clock run; each worker loads the same cache read-only.
    with ProcessPoolExecutor(max_workers=2) as pool:
        for item in pool.map(_stratified_seed_worker, worker_args, chunksize=1):
            stratified_targets.append({"seed": item["seed"], **item["target"]})
            stratified_runs.append(item)
    stratified_runs.sort(key=lambda item: item["seed"])
    stratified_targets.sort(key=lambda item: item["seed"])

    comparison_keys = ["full", "exploration", "holdout"] + [
        f"{tf}|{family}" for tf in ("M1", "M5") for family in ("FX Vol", "SFX Vol", "PainX", "MAX PainX")
    ]

    strategy_total = sequential[str(base_horizon)]["metrics"]["total_net_r"]
    random_totals = [item["total_net_r"] for item in random_runs]
    comparison = {
        "strategy_total_net_r": strategy_total,
        "random_mean_total_net_r": mean(random_totals) if random_totals else None,
        "random_runs_at_or_below_strategy": sum(value <= strategy_total for value in random_totals),
        "random_runs": len(random_totals),
        "empirical_percentile": (100.0 * sum(value <= strategy_total for value in random_totals) / len(random_totals)) if random_totals else None,
    }

    result = {
        "source": "replay",
        "execution_enabled": False,
        "watchlist_entries": len(pairs),
        "persisted_candidates": len(candidates),
        "global_daily_cap": GLOBAL_DAILY_CAP,
        "per_instrument_daily_cap": per_cap,
        "sequential": sequential,
        "sequential_variants": sequential_variants,
        "dollar_conversion": _min_lot_dollar_conversion(settings, pairs, sequential_variants),
        "no_gate_planner_baseline": no_gate_planner_baseline(series, horizon=base_horizon),
        "random_control": _random_summary(random_runs),
        "stratified_random_control": {
            "direction": "BUY_ONLY",
            "strata": "symbol|timeframe|UTC entry day",
            "entry_count_source": "accepted sequential strategy entries at horizon20",
            "seeds": random_seeds,
            "target_summary": {
                "requested_mean": mean([row["requested"] for row in stratified_targets]) if stratified_targets else None,
                "generated_mean": mean([row["generated"] for row in stratified_targets]) if stratified_targets else None,
                "shortfall_mean": mean([row["shortfall"] for row in stratified_targets]) if stratified_targets else None,
            },
            "runs": stratified_runs,
            "comparison": _comparison(sequential[str(base_horizon)], stratified_runs, comparison_keys),
        },
        "comparison": comparison,
        "random_control_explanation": (
            "The earlier unstratified control did not preserve the strategy's symbol/timeframe/day composition. "
            "Its global cap and one-open-position filter therefore selected a different mix of planner paths. "
            "Win rate alone is not sufficient when realized winner multiples, timeout mark-to-market returns, "
            "spread costs, and family composition differ; a run can have win rate below the strategy's aggregate "
            "breakeven while still having positive mean net R. The matched control above is the required comparison."
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("state/shadow_outcomes.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("state/sequential_replay_report.json"))
    parser.add_argument("--random-seeds", type=int, default=50)
    parser.add_argument("--include-unstratified", action="store_true")
    args = parser.parse_args()
    result = run(db=args.db, report_path=args.report, random_seeds=args.random_seeds, include_unstratified=args.include_unstratified)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
