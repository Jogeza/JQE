"""Compare Baseline, SELL-only, and Confirmed-Entry variants over frozen windows."""
from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backtesting.models import BacktestExecutionAssumptions, BacktestResult
from broker.types import Timeframe
from data.dataset import canonical_dataset_hash
from data.storage import CandleStore
from research.regime_diagnostics import (
    compute_metrics_for_trades,
    run_variant_backtest,
    validate_risk_compliance,
)
from tools.acquire_diagnostic_windows import WINDOWS

ALL_WINDOWS = (
    ("BASELINE", datetime(2026, 8, 24, tzinfo=timezone.utc), datetime(2026, 8, 31, tzinfo=timezone.utc)),
    *WINDOWS,
)

SCENARIOS = {
    "IDEALIZED_ZERO_COST": BacktestExecutionAssumptions(),
    "CONSERVATIVE_SIMULATION_COST": BacktestExecutionAssumptions(spread=0.50, slippage=0.25, fee_per_trade=0.0),
}

VARIANTS = {
    "BASELINE_BILATERAL": {"sell_only": False, "require_confirmation": False},
    "BASELINE_SELL_ONLY": {"sell_only": True, "require_confirmation": False},
    "CONFIRMED_BILATERAL": {"sell_only": False, "require_confirmation": True},
    "CONFIRMED_SELL_ONLY": {"sell_only": True, "require_confirmation": True},
}


def _trade_metrics(trades: list[Any]) -> dict[str, Any]:
    metrics = compute_metrics_for_trades(trades)
    return {
        "trades": metrics.trades,
        "buy_count": metrics.buy_count,
        "sell_count": metrics.sell_count,
        "wins": metrics.wins,
        "losses": metrics.losses,
        "win_rate_percent": round(metrics.win_rate_percent, 2),
        "gross_profit": round(metrics.gross_profit, 2),
        "gross_loss": round(metrics.gross_loss, 2),
        "net_pnl": round(metrics.net_pnl, 2),
        "expectancy": round(metrics.expectancy, 4),
        "profit_factor": (
            round(metrics.profit_factor, 2)
            if metrics.profit_factor is not None
            else None
        ),
        "maximum_drawdown": round(metrics.maximum_drawdown, 2),
        "maximum_drawdown_percent": round(metrics.maximum_drawdown_percent, 2),
    }


def _decision_counts(result: BacktestResult) -> dict[str, int]:
    decisions = list(result.decisions)
    return {
        "confirmation_passed": sum(
            1 for decision in decisions if decision.state == "CONFIRMATION_PASSED"
        ),
        "confirmation_rejected": sum(
            1 for decision in decisions if decision.state == "CONFIRMATION_REJECTED"
        ),
        "risk_blocked": sum(
            1 for decision in decisions if decision.state == "RISK_BLOCKED"
        ),
        "execution_rejected": sum(
            1 for decision in decisions if decision.state == "EXECUTION_REJECTED"
        ),
        "position_or_pending_suppressed": sum(
            1 for decision in decisions if decision.state == "REJECTED_CANDIDATE"
        ),
    }


def _exit_counts(result: BacktestResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for trade in result.trades:
        counts[trade.exit_reason.value] = counts.get(trade.exit_reason.value, 0) + 1
    return counts


def _directional_metrics(result: BacktestResult) -> dict[str, dict[str, Any]]:
    trades = list(result.trades)
    return {
        direction: _trade_metrics([trade for trade in trades if trade.direction == direction])
        for direction in ("BUY", "SELL")
    }


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Keep the reproducibility fields and decision metrics used in review."""
    windows: dict[str, Any] = {}
    for window_name, window in report["windows"].items():
        variants = {}
        for variant_name, metrics in window["variants"].items():
            variants[variant_name] = {
                key: metrics[key]
                for key in (
                    "trades", "buy_count", "sell_count", "win_rate_percent",
                    "net_pnl_zero_cost", "net_pnl_conservative_cost",
                    "expectancy_zero_cost", "expectancy_conservative_cost",
                    "profit_factor_zero_cost", "profit_factor_conservative_cost",
                    "maximum_drawdown_percent_zero_cost",
                    "maximum_drawdown_percent_conservative_cost",
                    "rejected_entries", "risk_compliance",
                    "result_hash_zero_cost", "result_hash_conservative_cost",
                )
            }
        windows[window_name] = {
            "candle_count": window["candle_count"],
            "dataset_hash": window["dataset_hash"],
            "variants": variants,
        }
    return {
        "metadata": report["metadata"],
        "aggregate": report["aggregate"],
        "windows": windows,
    }


def _extract_variant_metrics(
    result_zero: BacktestResult,
    result_cost: BacktestResult,
) -> dict[str, Any]:
    z_trades = list(result_zero.trades)
    c_trades = list(result_cost.trades)
    base_m = compute_metrics_for_trades(z_trades, cost_trades=c_trades)
    risk_z = validate_risk_compliance(result_zero)
    risk_c = validate_risk_compliance(result_cost)

    return {
        "trades": base_m.trades,
        "buy_count": base_m.buy_count,
        "sell_count": base_m.sell_count,
        "wins": base_m.wins,
        "losses": base_m.losses,
        "win_rate_percent": round(base_m.win_rate_percent, 2),
        "gross_profit": round(base_m.gross_profit, 2),
        "gross_loss": round(base_m.gross_loss, 2),
        "net_pnl_zero_cost": round(base_m.net_pnl, 2),
        "net_pnl_conservative_cost": round(base_m.conservative_cost_net_pnl or 0.0, 2),
        "cost_impact": round(base_m.conservative_cost_impact or 0.0, 2),
        "cost_flips_sign": base_m.cost_flips_sign,
        "expectancy_zero_cost": round(base_m.expectancy, 4),
        "expectancy_conservative_cost": round(
            (base_m.conservative_cost_net_pnl or 0.0) / len(c_trades) if c_trades else 0.0, 4
        ),
        "profit_factor_zero_cost": (
            round(base_m.profit_factor, 2) if base_m.profit_factor is not None else None
        ),
        "profit_factor_conservative_cost": _trade_metrics(c_trades)["profit_factor"],
        "maximum_drawdown_zero_cost": round(base_m.maximum_drawdown, 2),
        "maximum_drawdown_percent_zero_cost": round(base_m.maximum_drawdown_percent, 2),
        "maximum_drawdown_conservative_cost": _trade_metrics(c_trades)["maximum_drawdown"],
        "maximum_drawdown_percent_conservative_cost": _trade_metrics(c_trades)["maximum_drawdown_percent"],
        "directional": {
            "zero_cost": _directional_metrics(result_zero),
            "conservative_cost": _directional_metrics(result_cost),
        },
        "exit_reasons": {
            "zero_cost": _exit_counts(result_zero),
            "conservative_cost": _exit_counts(result_cost),
        },
        "rejected_entries": {
            "zero_cost": _decision_counts(result_zero),
            "conservative_cost": _decision_counts(result_cost),
        },
        "risk_compliance": {
            "zero_cost": risk_z,
            "conservative_cost": risk_c,
        },
        "result_hash_zero_cost": result_zero.result_hash,
        "result_hash_conservative_cost": result_cost.result_hash,
    }


async def main(*, verify_determinism: bool = True, compact: bool = False) -> None:
    store = CandleStore(read_only=True)
    report: dict[str, Any] = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "starting_balance": 50.0,
            "confirmation_timing": (
                "signal_i_close__confirm_i_plus_1_close__enter_i_plus_2_open"
            ),
            "raw_candle_total": 0,
        },
        "windows": {},
        "aggregate": {},
    }

    raw_results: dict[str, dict[str, dict[str, BacktestResult]]] = {}

    for window_name, start, end in ALL_WINDOWS:
        candles = store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
        ds_hash = canonical_dataset_hash(candles, symbol="XAUUSD", timeframe=Timeframe.M15)
        raw_results[window_name] = {}
        report["windows"][window_name] = {
            "candle_count": len(candles),
            "dataset_hash": ds_hash,
            "variants": {},
        }
        report["metadata"]["raw_candle_total"] += len(candles)

        for var_name, var_cfg in VARIANTS.items():
            raw_results[window_name][var_name] = {}
            # Run both scenarios twice to verify determinism
            for scen_name, execution in SCENARIOS.items():
                runs = [
                    await run_variant_backtest(
                        symbol="XAUUSD",
                        timeframe=Timeframe.M15,
                        dataset=candles,
                        provider="deriv",
                        starting_balance=50.0,
                        execution_assumptions=execution,
                        sell_only=var_cfg["sell_only"],
                        require_confirmation=var_cfg["require_confirmation"],
                    )
                    for _ in range(2 if verify_determinism else 1)
                ]
                first = runs[0]
                if verify_determinism:
                    second = runs[1]
                    if first.result_hash != second.result_hash or first.to_dict() != second.to_dict():
                        raise RuntimeError(f"Nondeterministic run: {window_name} {var_name} {scen_name}")
                raw_results[window_name][var_name][scen_name] = first

            metrics = _extract_variant_metrics(
                raw_results[window_name][var_name]["IDEALIZED_ZERO_COST"],
                raw_results[window_name][var_name]["CONSERVATIVE_SIMULATION_COST"],
            )
            report["windows"][window_name]["variants"][var_name] = metrics

    # Aggregate across all 4 windows
    report["aggregate"] = {}
    for var_name in VARIANTS:
        agg_zero_trades = []
        agg_cost_trades = []
        total_conf_rejections = 0
        for window_name in ALL_WINDOWS:
            w_name = window_name[0]
            z_res = raw_results[w_name][var_name]["IDEALIZED_ZERO_COST"]
            c_res = raw_results[w_name][var_name]["CONSERVATIVE_SIMULATION_COST"]
            agg_zero_trades.extend(z_res.trades)
            agg_cost_trades.extend(c_res.trades)
            total_conf_rejections += sum(1 for d in z_res.decisions if d.state == "CONFIRMATION_REJECTED")

        zm = compute_metrics_for_trades(agg_zero_trades, cost_trades=agg_cost_trades)
        cm = compute_metrics_for_trades(agg_cost_trades)
        zero_results = [
            raw_results[item[0]][var_name]["IDEALIZED_ZERO_COST"]
            for item in ALL_WINDOWS
        ]
        cost_results = [
            raw_results[item[0]][var_name]["CONSERVATIVE_SIMULATION_COST"]
            for item in ALL_WINDOWS
        ]

        aggregate_zero_exits: dict[str, int] = {}
        aggregate_cost_exits: dict[str, int] = {}
        for result, target in (
            *((result, aggregate_zero_exits) for result in zero_results),
            *((result, aggregate_cost_exits) for result in cost_results),
        ):
            for reason, count in _exit_counts(result).items():
                target[reason] = target.get(reason, 0) + count

        aggregate_decisions = {
            "zero_cost": {
                key: sum(_decision_counts(result)[key] for result in zero_results)
                for key in _decision_counts(zero_results[0])
            },
            "conservative_cost": {
                key: sum(_decision_counts(result)[key] for result in cost_results)
                for key in _decision_counts(cost_results[0])
            },
        }

        report["aggregate"][var_name] = {
            "trades": zm.trades,
            "buy_count": zm.buy_count,
            "sell_count": zm.sell_count,
            "wins": zm.wins,
            "losses": zm.losses,
            "win_rate_percent": round(zm.win_rate_percent, 2),
            "gross_profit": round(zm.gross_profit, 2),
            "gross_loss": round(zm.gross_loss, 2),
            "net_pnl_zero_cost": round(zm.net_pnl, 2),
            "net_pnl_conservative_cost": round(zm.conservative_cost_net_pnl or 0.0, 2),
            "cost_impact": round(zm.conservative_cost_impact or 0.0, 2),
            "cost_flips_sign": zm.cost_flips_sign,
            "expectancy_zero_cost": round(zm.expectancy, 4),
            "expectancy_conservative_cost": round(
                (zm.conservative_cost_net_pnl or 0.0) / len(agg_cost_trades) if agg_cost_trades else 0.0, 4
            ),
            "profit_factor_zero_cost": round(zm.profit_factor, 2) if zm.profit_factor is not None else None,
            "profit_factor_conservative_cost": round(cm.profit_factor, 2) if cm.profit_factor is not None else None,
            "maximum_drawdown_zero_cost": round(zm.maximum_drawdown, 2),
            "maximum_drawdown_percent_zero_cost": round(zm.maximum_drawdown_percent, 2),
            "maximum_drawdown_conservative_cost": round(cm.maximum_drawdown, 2),
            "maximum_drawdown_percent_conservative_cost": round(cm.maximum_drawdown_percent, 2),
            "total_confirmation_rejections": total_conf_rejections,
            "directional": {
                "zero_cost": {
                    direction: _trade_metrics([
                        trade for trade in agg_zero_trades if trade.direction == direction
                    ])
                    for direction in ("BUY", "SELL")
                },
                "conservative_cost": {
                    direction: _trade_metrics([
                        trade for trade in agg_cost_trades if trade.direction == direction
                    ])
                    for direction in ("BUY", "SELL")
                },
            },
            "exit_reasons": {
                "zero_cost": aggregate_zero_exits,
                "conservative_cost": aggregate_cost_exits,
            },
            "decision_counts": aggregate_decisions,
            "risk_compliance": {
                "zero_cost": all(
                    validate_risk_compliance(result)["status"] == "PASS"
                    for result in zero_results
                ),
                "conservative_cost": all(
                    validate_risk_compliance(result)["status"] == "PASS"
                    for result in cost_results
                ),
                "lowest_balance": min(
                    validate_risk_compliance(result)["lowest_balance"]
                    for result in (*zero_results, *cost_results)
                ),
            },
            "determinism_verified": verify_determinism,
        }

    print(json.dumps(_compact_report(report) if compact else report, indent=2, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--single-pass",
        action="store_true",
        help="Run once per case; intended only after a repeated determinism run",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print a review-oriented report without detailed trade slices",
    )
    arguments = parser.parse_args()
    asyncio.run(main(
        verify_determinism=not arguments.single_pass,
        compact=arguments.compact,
    ))
