"""Small, immutable Strategy V2 research framework.

This module is research-only. It uses the existing chronological
``BacktestEngine`` for risk, sizing, position lifecycle, and realized P&L.
Holdout windows are registry metadata here, but are never loaded by the
development evaluator.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Sequence

import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExecutionAssumptions, BacktestResult
from broker.types import Candle, Timeframe
from core.indicators import calculate_indicators
from data.dataset import canonical_dataset_hash


DEVELOPMENT_WINDOWS = (
    ("BASELINE", datetime(2026, 8, 24, tzinfo=timezone.utc), datetime(2026, 8, 31, tzinfo=timezone.utc)),
    ("OOS_1", datetime(2026, 4, 6, tzinfo=timezone.utc), datetime(2026, 5, 5, tzinfo=timezone.utc)),
    ("OOS_2", datetime(2026, 5, 26, tzinfo=timezone.utc), datetime(2026, 6, 18, tzinfo=timezone.utc)),
    ("OOS_3", datetime(2026, 7, 6, tzinfo=timezone.utc), datetime(2026, 8, 3, tzinfo=timezone.utc)),
)

HOLDOUT_WINDOWS = (
    ("OOS_4", datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc),
     "sha256:1ad975faf60289fd13d3942eb27b50a8bde659a737961464aa77e3e5319479b"),
    ("OOS_5", datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2025, 12, 15, tzinfo=timezone.utc),
     "sha256:d2d0cb44881376e2166bd4c05bae95d2c70b53820d5d9ad00edcded7f5bc4219"),
)

ZERO_COST = BacktestExecutionAssumptions()
CONSERVATIVE_COST = BacktestExecutionAssumptions(spread=0.50, slippage=0.25, fee_per_trade=0.0)


def _canonical(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, datetime):
            return item.astimezone(timezone.utc).isoformat()
        if isinstance(item, dict):
            return {str(k): normalize(v) for k, v in sorted(item.items())}
        if isinstance(item, (list, tuple)):
            return [normalize(v) for v in item]
        return item
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def deterministic_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class HypothesisSpec:
    hypothesis_id: str
    version: int
    description: str
    market_behavior_assumption: str
    entry_features: tuple[str, ...]
    entry_rule: str
    direction_rule: str
    exit_rule: str
    stop_rule: str
    target_rule: str
    max_holding_period: int
    expected_failure_mode: str
    invalidation_criteria: str

    @property
    def hypothesis_hash(self) -> str:
        return deterministic_hash(asdict(self))

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "hypothesis_hash": self.hypothesis_hash}


HYPOTHESES = (
    HypothesisSpec(
        "V2_TREND_PULLBACK", 1,
        "Trend entries require a counter-trend pullback followed by close-based continuation.",
        "Established EMA direction resumes after a temporary counter-trend move.",
        ("EMA50", "EMA200", "previous_3_bar_return", "close"),
        "At candle close, prior three-bar return is counter-trend and close is back beyond EMA50.",
        "BUY when EMA50 > EMA200; SELL when EMA50 < EMA200.",
        "Stop/target are canonical ATR multiples; close at stop, target, or timeout.",
        "Canonical engine stop at 1.5 ATR from next-open entry.",
        "Canonical engine target at 3.0 ATR from next-open entry.",
        19,
        "Pullbacks persist or trend regime changes before continuation.",
        "Reject if conservative expectancy is non-positive in at least three development windows.",
    ),
    HypothesisSpec(
        "V2_VOLATILITY_BREAKOUT", 1,
        "Compression resolves through a close beyond the prior twenty-bar range.",
        "Low recent range relative to ATR precedes directional expansion.",
        ("ATR", "recent_20_bar_range", "close", "EMA50", "EMA200"),
        "At candle close, current close breaks the prior twenty-bar high/low after range compression.",
        "BUY above prior high; SELL below prior low, with EMA context only as a direction tie-breaker.",
        "Stop/target are canonical ATR multiples; close at stop, target, or timeout.",
        "Canonical engine stop at 1.5 ATR from next-open entry.",
        "Canonical engine target at 3.0 ATR from next-open entry.",
        19,
        "Breakout is false or expansion is already exhausted at entry.",
        "Reject if positive gross expectancy does not survive conservative friction.",
    ),
    HypothesisSpec(
        "V2_MEAN_REVERSION", 1,
        "Extreme ATR-normalized displacement reverts when EMA trend separation is small.",
        "Non-trending markets mean-revert after sufficiently stretched closes.",
        ("RSI", "EMA50", "EMA200", "ATR", "close"),
        "At candle close, RSI is extreme and price displacement from EMA50 exceeds one ATR while EMA separation is modest.",
        "BUY oversold downside displacement; SELL overbought upside displacement.",
        "Stop/target are canonical ATR multiples; close at stop, target, or timeout.",
        "Canonical engine stop at 1.5 ATR from next-open entry.",
        "Canonical engine target at 3.0 ATR from next-open entry.",
        19,
        "Trend persistence overwhelms reversion or extremes are too rare.",
        "Reject if fewer than ten total development trades or if any window breaches risk validation.",
    ),
)


def holdout_registry() -> tuple[dict[str, Any], ...]:
    return tuple({"window_id": n, "start": s.isoformat(), "end": e.isoformat(),
                  "dataset_hash": h, "status": "LOCKED_HOLDOUT"}
                 for n, s, e, h in HOLDOUT_WINDOWS)


def development_registry(candles_by_window: dict[str, Sequence[Candle]]) -> tuple[dict[str, Any], ...]:
    unknown = set(candles_by_window) - {item[0] for item in DEVELOPMENT_WINDOWS}
    if unknown:
        raise ValueError(f"Development evaluator received non-development windows: {sorted(unknown)}")
    output = []
    for name, start, end in DEVELOPMENT_WINDOWS:
        candles = candles_by_window.get(name)
        if not candles:
            raise ValueError(f"Missing development dataset: {name}")
        output.append({"window_id": name, "start": start.isoformat(), "end": end.isoformat(),
                       "candles": len(candles), "dataset_hash": canonical_dataset_hash(
                           candles, symbol="XAUUSD", timeframe=Timeframe.M15,
                       )})
    return tuple(output)


def assert_holdout_closed(window_ids: Sequence[str], *, final_validation: bool = False) -> None:
    if not final_validation and set(window_ids) & {item[0] for item in HOLDOUT_WINDOWS}:
        raise PermissionError("OOS_4/OOS_5 are LOCKED_HOLDOUT and unavailable during V2 development")


def _signal_for(hypothesis_id: str, frame: pd.DataFrame, index: int) -> tuple[str, str] | None:
    row = frame.iloc[index]
    if not all(math.isfinite(float(row.get(field, float("nan")))) for field in ("EMA50", "EMA200", "RSI", "ATR")):
        return None
    close, ema50, ema200, atr, rsi = map(float, (row["close"], row["EMA50"], row["EMA200"], row["ATR"], row["RSI"]))
    if atr <= 0:
        return None
    if hypothesis_id == "V2_TREND_PULLBACK":
        if index < 3:
            return None
        prior_return = close / float(frame.iloc[index - 3]["close"]) - 1.0
        if ema50 > ema200 and prior_return < -0.001 and close > ema50:
            return "BUY", "trend pullback recovered above EMA50"
        if ema50 < ema200 and prior_return > 0.001 and close < ema50:
            return "SELL", "trend pullback recovered below EMA50"
    elif hypothesis_id == "V2_VOLATILITY_BREAKOUT":
        if index < 20:
            return None
        prior = frame.iloc[index - 20:index]
        prior_range = float(prior["high"].max() - prior["low"].min())
        if prior_range / atr > 12.0:
            return None
        if close > float(prior["high"].max()):
            return "BUY", "compressed range broke upward"
        if close < float(prior["low"].min()):
            return "SELL", "compressed range broke downward"
    elif hypothesis_id == "V2_MEAN_REVERSION":
        separation = abs(ema50 - ema200) / close
        displacement = abs(close - ema50) / atr
        if separation < 0.002 and displacement > 1.0 and rsi < 25:
            return "BUY", "oversold non-trending displacement"
        if separation < 0.002 and displacement > 1.0 and rsi > 75:
            return "SELL", "overbought non-trending displacement"
    return None


async def evaluate_hypothesis(
    hypothesis: HypothesisSpec, candles: Sequence[Candle], *, execution: BacktestExecutionAssumptions,
    starting_balance: float = 50.0,
) -> BacktestResult:
    """Evaluate one fixed hypothesis through the canonical simulation engine."""
    frame = calculate_indicators(pd.DataFrame([c.model_dump() for c in candles]))
    engine = BacktestEngine(starting_balance=starting_balance, symbol="XAUUSD",
                            timeframe=Timeframe.M15, execution=execution)
    for index in range(200, len(frame)):
        engine.process_candle(index, frame)
        signal = _signal_for(hypothesis.hypothesis_id, frame, index)
        if signal is not None:
            direction, reason = signal
            engine.queue_signal({"signal": direction, "confidence": 100, "reasons": [reason]}, index, frame)
    engine.finish(len(frame) - 1, frame)
    from backtesting.backtest import build_backtest_result
    from backtesting.models import BacktestIndicatorObservation, CandleDatasetSnapshot
    observations = tuple(BacktestIndicatorObservation(i, frame.iloc[i]["time"], float(frame.iloc[i]["EMA50"]),
        float(frame.iloc[i]["EMA200"]), float(frame.iloc[i]["RSI"]), float(frame.iloc[i]["ATR"]))
        for i in range(len(frame)) if all(math.isfinite(float(frame.iloc[i].get(x, float("nan")))) for x in ("EMA50", "EMA200", "RSI", "ATR")))
    return build_backtest_result(
        CandleDatasetSnapshot(provider="deriv", symbol="XAUUSD", timeframe=Timeframe.M15, candles=tuple(candles)),
        engine, {"strategy_id": hypothesis.hypothesis_id, "hypothesis_hash": hypothesis.hypothesis_hash}, observations,
    )


def result_metrics(result: BacktestResult) -> dict[str, Any]:
    trades = list(result.trades)
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl < 0]
    profits = sorted((t.net_pnl for t in trades if t.net_pnl > 0), reverse=True)
    total_profit = sum(profits)
    durations = [t.holding_candles for t in trades]
    by_direction = {d: [t for t in trades if t.direction == d] for d in ("BUY", "SELL")}
    gross = sum(t.gross_pnl for t in trades)
    modeled_friction = sum((result.execution.spread + result.execution.slippage) * t.quantity.value + result.execution.fee_per_trade for t in trades)
    risk_checks = []
    chronology = []
    for trade in trades:
        authorized = abs(trade.entry_price - trade.stop_price) * trade.quantity.value
        realized_loss = max(0.0, -trade.net_pnl)
        risk_checks.append(realized_loss <= authorized + 1e-9)
        feature_timestamp = trade.signal_timestamp.astimezone(timezone.utc)
        signal_timestamp = trade.signal_timestamp.astimezone(timezone.utc)
        entry_timestamp = trade.entry_timestamp.astimezone(timezone.utc)
        chronology.append({
            "feature_max_timestamp": feature_timestamp.isoformat(),
            "signal_timestamp": signal_timestamp.isoformat(),
            "confirmation_timestamp": None,
            "entry_timestamp": entry_timestamp.isoformat(),
            "valid": feature_timestamp <= signal_timestamp < entry_timestamp,
        })
    return {
        "signals": sum(d.signal in ("BUY", "SELL") for d in result.decisions), "executed_trades": len(trades),
        "starting_balance": result.initial_capital, "final_balance": result.ending_capital, "net_pnl": result.absolute_pnl,
        "return_percent": result.return_percent, "win_rate": result.win_rate_percent, "profit_factor": result.profit_factor,
        "gross_expectancy": gross / len(trades) if trades else 0.0, "modeled_friction": modeled_friction,
        "net_expectancy": result.expectancy, "max_drawdown": result.maximum_drawdown, "average_trade_duration": sum(durations) / len(durations) if durations else 0.0,
        "median_trade_duration": median(durations) if durations else 0.0,
        "stop_loss_count": sum(t.exit_reason.value == "STOP_LOSS" for t in trades),
        "take_profit_count": sum(t.exit_reason.value == "TAKE_PROFIT" for t in trades),
        "timeout_count": sum(t.exit_reason.value == "TIMEOUT" for t in trades),
        "buy_trades": len(by_direction["BUY"]), "sell_trades": len(by_direction["SELL"]),
        "buy_pnl": sum(t.net_pnl for t in by_direction["BUY"]), "sell_pnl": sum(t.net_pnl for t in by_direction["SELL"]),
        "top_1_trade_profit_contribution": profits[0] / total_profit if profits and total_profit else 0.0,
        "top_5_trade_profit_contribution": sum(profits[:5]) / total_profit if profits and total_profit else 0.0,
        "profit_with_best_trade_removed": sum(t.net_pnl for t in trades) - (profits[0] if profits else 0.0),
        "profit_with_best_5_trades_removed": sum(t.net_pnl for t in trades) - sum(profits[:5]),
        "risk_validation": "PASS" if validate_trade_risk(trades) and all(risk_checks) else "FAIL",
        "chronology_validation": "PASS" if validate_trade_chronology(trades) and all(item["valid"] for item in chronology) else "FAIL",
        "trade_chronology": chronology,
        "result_hash": result.result_hash,
    }


def validate_trade_chronology(trades: Sequence[Any]) -> bool:
    return all(
        trade.signal_timestamp.astimezone(timezone.utc) < trade.entry_timestamp.astimezone(timezone.utc)
        for trade in trades
    )


def validate_trade_risk(trades: Sequence[Any]) -> bool:
    return all(
        max(0.0, -trade.net_pnl) <= abs(trade.entry_price - trade.stop_price) * trade.quantity.value + 1e-9
        for trade in trades
    )


def bootstrap_expectancy(trades: Sequence[Any], *, seed: int = 62028, repetitions: int = 2000) -> dict[str, float | int | None]:
    values = [float(t.net_pnl) for t in trades]
    if not values:
        return {"repetitions": repetitions, "point_estimate": None, "ci_low": None, "ci_high": None}
    rng = random.Random(seed)
    samples = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(repetitions)]
    samples.sort()
    return {"repetitions": repetitions, "point_estimate": sum(values) / len(values),
            "ci_low": samples[int(repetitions * 0.025)], "ci_high": samples[int(repetitions * 0.975) - 1]}


def monte_carlo_sequence(trades: Sequence[Any], *, seed: int = 62029, repetitions: int = 2000) -> dict[str, float | int]:
    values = [float(t.net_pnl) for t in trades]
    rng = random.Random(seed); terminals=[]; drawdowns=[]
    below50=below40=below25=0
    for _ in range(repetitions):
        shuffled=list(values); rng.shuffle(shuffled); balance=50.0; peak=50.0; max_dd=0.0; hit40=hit25=False
        for pnl in shuffled:
            balance += pnl; peak=max(peak,balance); max_dd=max(max_dd,peak-balance); hit40 |= balance < 40; hit25 |= balance < 25
        terminals.append(balance); drawdowns.append(max_dd); below50 += balance < 50; below40 += hit40; below25 += hit25
    terminals.sort(); drawdowns.sort()
    return {"repetitions": repetitions, "median_terminal_balance": terminals[len(terminals)//2], "p05_terminal_balance": terminals[int(repetitions*.05)], "p95_terminal_balance": terminals[int(repetitions*.95)-1], "median_max_drawdown": drawdowns[len(drawdowns)//2], "p95_max_drawdown": drawdowns[int(repetitions*.95)-1], "probability_ending_below_50": below50/repetitions, "probability_falling_below_40": below40/repetitions, "probability_falling_below_25": below25/repetitions}


def classify_development(window_metrics: Sequence[dict[str, Any]]) -> str:
    profitable = sum(item["conservative"]["net_expectancy"] > 0 for item in window_metrics)
    total = sum(item["conservative"]["executed_trades"] for item in window_metrics)
    risk_ok = all(item["conservative"]["risk_validation"] == "PASS" for item in window_metrics)
    if total < 10:
        return "INSUFFICIENT_SAMPLE"
    # A single losing development window is a meaningful independent failure
    # at this checkpoint; do not average it away with aggregate P&L.
    if profitable == len(window_metrics) and risk_ok and all(item["conservative"]["max_drawdown"] < 50 for item in window_metrics):
        return "PROMISING_DEVELOPMENT_RESULT"
    if profitable == 0:
        return "REJECTED_NO_EDGE"
    if any(item["zero_cost"]["net_expectancy"] > 0 and item["conservative"]["net_expectancy"] <= 0 for item in window_metrics):
        return "REJECTED_COST_SENSITIVE"
    return "REJECTED_INCONSISTENT"


def development_report(results: dict[str, dict[str, BacktestResult]]) -> dict[str, Any]:
    report: dict[str, Any] = {"metadata": {"development_only": True, "windows": [x[0] for x in DEVELOPMENT_WINDOWS]}, "hypotheses": {}}
    for hypothesis in HYPOTHESES:
        windows=[]
        for window_id, scenario_results in results[hypothesis.hypothesis_id].items():
            zero = scenario_results["IDEALIZED_ZERO_COST"]; conservative = scenario_results["CONSERVATIVE_SIMULATION_COST"]
            windows.append({"window_id": window_id, "zero_cost": result_metrics(zero), "conservative": result_metrics(conservative),
                            "bootstrap": bootstrap_expectancy(conservative.trades), "monte_carlo": monte_carlo_sequence(conservative.trades)})
        positive=[x for x in windows if x["conservative"]["net_expectancy"] > 0]
        report["hypotheses"][hypothesis.hypothesis_id] = {"hypothesis_hash": hypothesis.hypothesis_hash, "windows": windows,
            "profitable_development_windows": len(positive), "losing_development_windows": len(windows)-len(positive),
            "median_net_expectancy": median([x["conservative"]["net_expectancy"] for x in windows]),
            "worst_window_net_expectancy": min(x["conservative"]["net_expectancy"] for x in windows),
            "median_profit_factor": median([x["conservative"]["profit_factor"] or 0.0 for x in windows]),
            "worst_max_drawdown": max(x["conservative"]["max_drawdown"] for x in windows),
            "total_trades": sum(x["conservative"]["executed_trades"] for x in windows),
            "cost_robustness": {
                "zero_cost_expectancy": median(x["zero_cost"]["net_expectancy"] for x in windows),
                "conservative_cost_expectancy": median(x["conservative"]["net_expectancy"] for x in windows),
                "friction_per_trade": sum(x["conservative"]["modeled_friction"] for x in windows) / max(1, sum(x["conservative"]["executed_trades"] for x in windows)),
                "edge_retained_after_cost_percent": (
                    median(x["conservative"]["net_expectancy"] for x in windows)
                    / median(x["zero_cost"]["net_expectancy"] for x in windows) * 100
                    if median(x["zero_cost"]["net_expectancy"] for x in windows) > 0 else 0.0
                ),
                "classification": (
                    "ROBUST_TO_COSTS" if all(x["conservative"]["net_expectancy"] > 0 for x in windows)
                    else "COST_SENSITIVE" if all(x["zero_cost"]["net_expectancy"] > 0 for x in windows)
                    else "NO_GROSS_EDGE"
                ),
            },
            "classification": classify_development(windows)}
    return report