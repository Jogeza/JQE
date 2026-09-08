"""Development-only diagnosis for failed V2 hypotheses.

This module intentionally has no holdout loader. It computes outcome-only
excursions from post-entry candles and keeps them separate from entry state.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any, Sequence

import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExecutionAssumptions, BacktestResult
from broker.types import Candle, Timeframe
from core.indicators import calculate_indicators
from data.dataset import canonical_dataset_hash
from research.strategy_v2 import (
    CONSERVATIVE_COST, DEVELOPMENT_WINDOWS, HYPOTHESES, ZERO_COST,
    assert_holdout_closed, deterministic_hash, evaluate_hypothesis,
)


EXCURSION_THRESHOLDS_R = (0.25, 0.50, 0.75, 1.00, 1.50, 2.00)
PATH_HORIZONS = (1, 2, 4, 8, 16)
BOOTSTRAP_SEED = 62030
RANDOM_CONTROL_SEED = 62031


@dataclass(frozen=True, slots=True)
class Excursion:
    mfe_price: float
    mae_price: float
    mfe_atr: float
    mae_atr: float
    mfe_r: float
    mae_r: float
    time_to_mfe_candles: int
    time_to_mae_candles: int
    favorable_thresholds_reached: tuple[float, ...]
    adverse_thresholds_reached: tuple[float, ...]


def calculate_excursion(trade: Any, candles: Sequence[Candle], atr: float) -> Excursion:
    """Calculate MFE/MAE from the entry candle through the exit candle.

    Backtest timestamps identify candle-opening buckets.  The engine evaluates
    the complete exit candle for an intrabar stop/target, or its close for a
    timeout/end-of-data exit, so that candle is included.  Later candles are
    never part of the realized trade path.
    """
    entry_index, exit_index = _trade_path_bounds(trade, candles)
    path = candles[entry_index:exit_index + 1]
    entry = float(trade.entry_price)
    favorable: list[float] = []
    adverse: list[float] = []
    for candle in path:
        if trade.direction == "BUY":
            favorable.append(max(0.0, float(candle.high) - entry))
            adverse.append(max(0.0, entry - float(candle.low)))
        else:
            favorable.append(max(0.0, entry - float(candle.low)))
            adverse.append(max(0.0, float(candle.high) - entry))
    mfe = max(favorable, default=0.0)
    mae = max(adverse, default=0.0)
    risk = abs(float(trade.entry_price) - float(trade.stop_price))
    safe_atr = atr if atr > 0 else 1.0
    safe_r = risk if risk > 0 else 1.0
    return Excursion(
        mfe, mae, mfe / safe_atr, mae / safe_atr, mfe / safe_r, mae / safe_r,
        favorable.index(mfe), adverse.index(mae),
        tuple(threshold for threshold in EXCURSION_THRESHOLDS_R if mfe / safe_r >= threshold),
        tuple(threshold for threshold in EXCURSION_THRESHOLDS_R if mae / safe_r >= threshold),
    )


def state_bucket_definitions(frames: Sequence[pd.DataFrame]) -> dict[str, tuple[float, float]]:
    values: dict[str, list[float]] = defaultdict(list)
    for frame in frames:
        valid = frame.dropna(subset=["EMA50", "EMA200", "ATR", "RSI"])
        values["trend_strength"].extend((abs(valid["EMA50"] - valid["EMA200"]) / valid["ATR"]).tolist())
        values["volatility"].extend((valid["ATR"] / valid["close"]).tolist())
    return {
        name: (float(pd.Series(items).quantile(1 / 3)), float(pd.Series(items).quantile(2 / 3)))
        for name, items in values.items()
    }


def state_labels(frame: pd.DataFrame, index: int, buckets: dict[str, tuple[float, float]]) -> dict[str, str]:
    row = frame.iloc[index]
    trend = abs(float(row["EMA50"]) - float(row["EMA200"])) / float(row["ATR"])
    volatility = float(row["ATR"]) / float(row["close"])
    trend_low, trend_high = buckets["trend_strength"]
    vol_low, vol_high = buckets["volatility"]
    recent = float(row["close"]) / float(frame.iloc[max(0, index - 4)]["close"]) - 1.0
    return {
        "trend_strength": "weak" if trend <= trend_low else "moderate" if trend <= trend_high else "strong",
        "volatility": "low" if volatility <= vol_low else "medium" if volatility <= vol_high else "high",
        "recent_direction": "bullish" if recent > 0 else "bearish" if recent < 0 else "neutral",
        "ema_structure": "bullish" if row["EMA50"] > row["EMA200"] else "bearish" if row["EMA50"] < row["EMA200"] else "compressed",
    }


def _trade_path_bounds(trade: Any, candles: Sequence[Candle]) -> tuple[int, int]:
    entry_index = next(i for i, candle in enumerate(candles) if candle.time == trade.entry_timestamp)
    exit_index = next(i for i, candle in enumerate(candles) if candle.time == trade.exit_timestamp)
    if exit_index < entry_index:
        raise ValueError("Trade exit precedes entry")
    return entry_index, exit_index


def path_excursion(trade: Any, candles: Sequence[Candle], horizons: Sequence[int] = PATH_HORIZONS) -> dict[int, tuple[float, float]]:
    entry_index, exit_index = _trade_path_bounds(trade, candles)
    entry = float(trade.entry_price)
    output = {}
    for horizon in horizons:
        path = candles[entry_index:min(entry_index + horizon, exit_index + 1)]
        if trade.direction == "BUY":
            favorable = [float(c.high) - entry for c in path]
            adverse = [entry - float(c.low) for c in path]
        else:
            favorable = [entry - float(c.low) for c in path]
            adverse = [float(c.high) - entry for c in path]
        output[horizon] = (max(favorable, default=0.0), max(adverse, default=0.0))
    return output


def excursion_record(trade: Any, candles: Sequence[Candle], frame: pd.DataFrame, state_buckets: dict[str, tuple[float, float]]) -> dict[str, Any]:
    entry_index, _ = _trade_path_bounds(trade, candles)
    feature_index = entry_index - 1
    if feature_index < 0:
        raise ValueError("Trade has no fully closed pre-entry candle")
    excursion = calculate_excursion(trade, candles, float(frame.iloc[feature_index]["ATR"]))
    return {
        "trade_id": trade.trade_id, "direction": trade.direction,
        "signal_timestamp": trade.signal_timestamp.astimezone(timezone.utc).isoformat(),
        "entry_timestamp": trade.entry_timestamp.astimezone(timezone.utc).isoformat(),
        "exit_timestamp": trade.exit_timestamp.astimezone(timezone.utc).isoformat(),
        "outcome": "WIN" if trade.net_pnl > 0 else "LOSS" if trade.net_pnl < 0 else "FLAT",
        "net_pnl": trade.net_pnl, "holding_candles": trade.holding_candles,
        "planned_stop_distance": abs(trade.entry_price - trade.stop_price),
        "planned_target_distance": abs(trade.target_price - trade.entry_price),
        "mfe_price": excursion.mfe_price, "mae_price": excursion.mae_price,
        "mfe_atr": excursion.mfe_atr, "mae_atr": excursion.mae_atr,
        "mfe_r": excursion.mfe_r, "mae_r": excursion.mae_r,
        "time_to_mfe_candles": excursion.time_to_mfe_candles,
        "time_to_mae_candles": excursion.time_to_mae_candles,
        "favorable_thresholds_reached": excursion.favorable_thresholds_reached,
        "adverse_thresholds_reached": excursion.adverse_thresholds_reached,
        "state": state_labels(frame, feature_index, state_buckets),
        "feature_timestamp": frame.iloc[feature_index]["time"].astimezone(timezone.utc).isoformat(),
        "path": {str(k): v for k, v in path_excursion(trade, candles).items()},
    }


def aggregate_records(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"trades": 0, "warning": "INSUFFICIENT_SAMPLE"}
    def avg(key: str) -> float:
        return sum(float(item[key]) for item in records) / len(records)
    return {
        "trades": len(records), "buy_trades": sum(x["direction"] == "BUY" for x in records),
        "sell_trades": sum(x["direction"] == "SELL" for x in records),
        "win_rate": sum(x["outcome"] == "WIN" for x in records) / len(records),
        "net_expectancy": avg("net_pnl"), "mfe_price": avg("mfe_price"), "mae_price": avg("mae_price"),
        "mfe_r": avg("mfe_r"), "mae_r": avg("mae_r"),
        "median_holding_candles": median(x["holding_candles"] for x in records),
        "stop_rate": sum(x["outcome"] == "LOSS" for x in records) / len(records),
        "target_rate": sum(x["holding_candles"] < 19 and x["outcome"] == "WIN" for x in records) / len(records),
        "timeout_rate": sum(x["holding_candles"] >= 19 for x in records) / len(records),
        "mfe_threshold_rates": {str(t): sum(t in x["favorable_thresholds_reached"] for x in records) / len(records) for t in EXCURSION_THRESHOLDS_R},
        "mae_threshold_rates": {str(t): sum(t in x["adverse_thresholds_reached"] for x in records) / len(records) for t in EXCURSION_THRESHOLDS_R},
    }


def time_to_edge(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    bins = (("1", 1, 1), ("2", 2, 2), ("3_4", 3, 4), ("5_8", 5, 8), ("9_16", 9, 16), (">16", 17, 10**9))
    output = {}
    for name, low, high in bins:
        group = [x for x in records if low <= x["time_to_mfe_candles"] <= high]
        output[name] = {"trades": len(group), "eventual_winner_rate": sum(x["outcome"] == "WIN" for x in group) / len(group) if group else None,
                        "median_mfe": median(x["mfe_r"] for x in group) if group else None,
                        "median_mae": median(x["mae_r"] for x in group) if group else None,
                        "net_outcome": sum(x["net_pnl"] for x in group)}
    return output


def random_control(records: Sequence[dict[str, Any]], candles: Sequence[Candle], *, seed: int = RANDOM_CONTROL_SEED, repetitions: int = 200, target_expectancy: float | None = None) -> dict[str, Any]:
    """Random timing control using the observed count and direction mix."""
    rng = random.Random(seed); desired = len(records)
    directions = [x["direction"] for x in records]
    indices = list(range(200, max(201, len(candles) - 1)))
    frame = calculate_indicators(pd.DataFrame([c.model_dump() for c in candles]))
    expectancies = []
    counts = []
    for _ in range(repetitions):
        chosen = sorted(rng.sample(indices, min(desired, len(indices))))
        direction_order = directions[:len(chosen)]
        engine = BacktestEngine(starting_balance=50.0, symbol="XAUUSD", timeframe=Timeframe.M15, execution=CONSERVATIVE_COST)
        for index, direction in zip(chosen, direction_order):
            engine.process_candle(index, frame)
            engine.queue_signal({"signal": direction, "confidence": 100}, index, frame)
        engine.finish(len(frame) - 1, frame)
        pnls = [trade.net_pnl for trade in engine.trades]
        expectancies.append(sum(pnls) / len(pnls) if pnls else 0.0)
        counts.append(len(pnls))
    expectancies.sort()
    point = sum(expectancies) / len(expectancies) if expectancies else 0.0
    percentile = (sum(value <= target_expectancy for value in expectancies) / len(expectancies)
                  if expectancies and target_expectancy is not None else None)
    return {"trades": int(median(counts)) if counts else 0, "expectancy": point,
            "median_expectancy": expectancies[len(expectancies) // 2] if expectancies else 0.0,
            "p05": expectancies[int(repetitions * .05)] if expectancies else 0.0,
            "p95": expectancies[int(repetitions * .95) - 1] if expectancies else 0.0,
            "percentile_of_hypothesis": percentile, "direction_ratio": sum(x == "BUY" for x in directions) / len(directions) if directions else 0.0,
            "seed": seed, "repetitions": repetitions}


def holdout_refusal_check() -> bool:
    try:
        assert_holdout_closed(("OOS_4", "OOS_5"))
    except PermissionError:
        return True
    return False


def diagnosis_gate(structural_findings: Sequence[dict[str, Any]]) -> tuple[str, tuple[dict[str, Any], ...]]:
    stable = [item for item in structural_findings if item.get("supporting_windows", 0) >= 3 and item.get("supports_v3", False)]
    if not stable:
        return "NO_CLEAR_EDGE_STRUCTURE", ()
    return "STRUCTURAL_FAILURE_IDENTIFIED", tuple(stable[:2])
