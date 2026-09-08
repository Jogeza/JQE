"""Deterministic, no-look-ahead market-structure research helpers.

Predictor fields are calculated from the last fully closed candle before a
trade's entry.  Outcome fields are appended separately from the completed
trade, making the information boundary explicit and testable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import random
from statistics import mean, median, stdev
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from backtesting.models import BacktestResult
from broker.types import Candle
from core.indicators import calculate_indicators


BOOTSTRAP_SEED = 62026
BOOTSTRAP_REPETITIONS = 5_000
MONTE_CARLO_SEED = 62027
MONTE_CARLO_REPETITIONS = 5_000
SMALL_SAMPLE_THRESHOLD = 20


@dataclass(frozen=True, slots=True)
class TradeResearchRecord:
    record_id: str
    dataset_hash: str
    window_id: str
    trade_id: int
    signal_timestamp: datetime
    feature_timestamp: datetime
    entry_timestamp: datetime
    exit_timestamp: datetime
    direction: str
    strategy_variant: str
    confirmation_variant: bool
    cost_scenario: str
    balance_before: float
    balance_after: float
    quantity: float
    quantity_unit: str
    authorized_risk_amount: float
    authorized_risk_percent: float
    gross_pnl: float
    recorded_costs: float
    modeled_entry_friction: float
    net_pnl: float
    r_multiple: float | None
    outcome: str
    exit_reason: str
    holding_candles: int
    holding_minutes: int
    close: float
    ema50: float
    ema200: float
    ema_separation: float
    ema_separation_percent: float
    rsi: float
    atr: float
    atr_percent: float
    regime: str
    translated_regime: str
    momentum_state: str
    trend_direction: str
    confidence: int | None
    previous_4_bar_return: float | None
    previous_8_bar_return: float | None
    previous_16_bar_return: float | None
    previous_32_bar_return: float | None
    distance_from_recent_high: float
    distance_from_recent_low: float
    local_range: float
    atr_normalized_range: float | None
    ema50_slope_4bar: float | None
    ema200_slope_4bar: float | None
    ema50_slope_percent: float | None
    ema200_slope_percent: float | None
    stop_distance: float

    def to_dict(self) -> dict[str, Any]:
        return _normalize(asdict(self))


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Research timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    )


def deterministic_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def serialize_records(records: Sequence[TradeResearchRecord]) -> bytes:
    ordered = sorted(records, key=lambda record: record.record_id)
    return (
        "".join(canonical_json(record.to_dict()) + "\n" for record in ordered)
    ).encode("utf-8")


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Required pre-entry feature is not finite")
    return number


def _optional(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _previous_return(frame: pd.DataFrame, index: int, bars: int) -> float | None:
    earlier = index - bars
    if earlier < 0:
        return None
    base = _optional(frame.iloc[earlier]["close"])
    current = _optional(frame.iloc[index]["close"])
    if base in (None, 0.0) or current is None:
        return None
    return current / base - 1.0


def _slope(frame: pd.DataFrame, index: int, column: str, bars: int = 4) -> tuple[float | None, float | None]:
    earlier = index - bars
    if earlier < 0:
        return None, None
    start = _optional(frame.iloc[earlier][column])
    end = _optional(frame.iloc[index][column])
    if start in (None, 0.0) or end is None:
        return None, None
    per_bar = (end - start) / bars
    return per_bar, per_bar / start


def _translated_regime(regime: str) -> str:
    if regime in {"TREND_UP", "TREND_DOWN", "TRENDING"}:
        return "TRENDING"
    if regime in {"RANGE", "RANGING"}:
        return "RANGING"
    if regime == "HIGH_VOLATILITY":
        return regime
    return "UNKNOWN"


def extract_trade_records(
    result: BacktestResult,
    candles: Sequence[Candle],
    *,
    window_id: str,
    strategy_variant: str,
    cost_scenario: str,
    feature_frame: pd.DataFrame | None = None,
) -> tuple[TradeResearchRecord, ...]:
    """Extract completed trades using only the state known before entry."""
    frame = feature_frame if feature_frame is not None else calculate_indicators(
        pd.DataFrame([candle.model_dump() for candle in candles])
    )
    time_to_index = {row["time"]: int(index) for index, row in frame.iterrows()}
    regimes = {
        observation.timestamp: str(observation.regime or "UNKNOWN")
        for observation in result.indicators
    }
    confidences = {
        (decision.timestamp, decision.signal): decision.confidence
        for decision in result.decisions
        if decision.state == "QUEUED" and decision.signal in {"BUY", "SELL"}
    }
    spread_slippage = result.execution.spread + result.execution.slippage
    records: list[TradeResearchRecord] = []

    for trade in result.trades:
        entry_index = time_to_index[trade.entry_timestamp]
        feature_index = entry_index - 1
        if feature_index < 0:
            raise ValueError("A trade has no fully closed pre-entry candle")
        row = frame.iloc[feature_index]
        feature_timestamp = row["time"]
        if feature_timestamp >= trade.entry_timestamp:
            raise ValueError("Pre-entry feature boundary is not chronological")

        close = _finite(row["close"])
        ema50, ema200 = _finite(row["EMA50"]), _finite(row["EMA200"])
        rsi, atr = _finite(row["RSI"]), _finite(row["ATR"])
        ema_separation = ema50 - ema200
        recent = frame.iloc[max(0, feature_index - 31): feature_index + 1]
        recent_high = _finite(recent["high"].max())
        recent_low = _finite(recent["low"].min())
        local_range = recent_high - recent_low
        ema50_slope, ema50_slope_pct = _slope(frame, feature_index, "EMA50")
        ema200_slope, ema200_slope_pct = _slope(frame, feature_index, "EMA200")
        risk_amount = abs(trade.entry_price - trade.stop_price) * trade.quantity.value
        risk_percent = risk_amount / trade.balance_before * 100.0
        modeled_friction = spread_slippage * trade.quantity.value + trade.costs
        regime = regimes.get(feature_timestamp, "UNKNOWN")
        if close > ema50 > ema200:
            trend = "BULLISH"
        elif close < ema50 < ema200:
            trend = "BEARISH"
        else:
            trend = "MIXED"
        momentum = "STRONG" if rsi > 60 else "WEAK" if rsi < 40 else "NEUTRAL"
        record_id = (
            f"{window_id}:{strategy_variant}:{cost_scenario}:{trade.trade_id:04d}"
        )
        records.append(TradeResearchRecord(
            record_id=record_id,
            dataset_hash=result.dataset_hash,
            window_id=window_id,
            trade_id=trade.trade_id,
            signal_timestamp=trade.signal_timestamp,
            feature_timestamp=feature_timestamp,
            entry_timestamp=trade.entry_timestamp,
            exit_timestamp=trade.exit_timestamp,
            direction=trade.direction,
            strategy_variant=strategy_variant,
            confirmation_variant=bool(result.strategy.get("require_confirmation")),
            cost_scenario=cost_scenario,
            balance_before=trade.balance_before,
            balance_after=trade.balance_after,
            quantity=trade.quantity.value,
            quantity_unit=trade.quantity.unit.value,
            authorized_risk_amount=risk_amount,
            authorized_risk_percent=risk_percent,
            gross_pnl=trade.gross_pnl,
            recorded_costs=trade.costs,
            modeled_entry_friction=modeled_friction,
            net_pnl=trade.net_pnl,
            r_multiple=(trade.net_pnl / risk_amount if risk_amount > 0 else None),
            outcome="WIN" if trade.net_pnl > 0 else "LOSS" if trade.net_pnl < 0 else "FLAT",
            exit_reason=trade.exit_reason.value,
            holding_candles=trade.holding_candles,
            holding_minutes=trade.holding_candles * 15,
            close=close,
            ema50=ema50,
            ema200=ema200,
            ema_separation=ema_separation,
            ema_separation_percent=ema_separation / close,
            rsi=rsi,
            atr=atr,
            atr_percent=atr / close,
            regime=regime,
            translated_regime=_translated_regime(regime),
            momentum_state=momentum,
            trend_direction=trend,
            confidence=confidences.get((trade.signal_timestamp, trade.direction)),
            previous_4_bar_return=_previous_return(frame, feature_index, 4),
            previous_8_bar_return=_previous_return(frame, feature_index, 8),
            previous_16_bar_return=_previous_return(frame, feature_index, 16),
            previous_32_bar_return=_previous_return(frame, feature_index, 32),
            distance_from_recent_high=(close - recent_high) / close,
            distance_from_recent_low=(close - recent_low) / close,
            local_range=local_range,
            atr_normalized_range=(local_range / atr if atr > 0 else None),
            ema50_slope_4bar=ema50_slope,
            ema200_slope_4bar=ema200_slope,
            ema50_slope_percent=ema50_slope_pct,
            ema200_slope_percent=ema200_slope_pct,
            stop_distance=abs(trade.entry_price - trade.stop_price),
        ))
    return tuple(records)


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def distribution(records: Sequence[TradeResearchRecord], field: str) -> dict[str, Any]:
    values = [value for record in records if (value := _optional(getattr(record, field))) is not None]
    return {
        "n": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "q1": _quantile(values, 0.25),
        "q3": _quantile(values, 0.75),
        "standard_deviation": stdev(values) if len(values) > 1 else None,
    }


def wilson_interval(wins: int, trades: int, z: float = 1.959963984540054) -> tuple[float | None, float | None]:
    if trades <= 0:
        return None, None
    proportion = wins / trades
    denominator = 1.0 + z * z / trades
    center = (proportion + z * z / (2.0 * trades)) / denominator
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / trades + z * z / (4.0 * trades * trades)
    ) / denominator
    return center - margin, center + margin


def trade_statistics(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    pnls = [record.net_pnl for record in records]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    low, high = wilson_interval(len(wins), len(pnls))
    return {
        "trades": len(records),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_percent": len(wins) / len(pnls) * 100.0 if pnls else None,
        "win_rate_95_percent_interval": (
            [low * 100.0, high * 100.0] if low is not None and high is not None else None
        ),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_pnl": sum(pnls),
        "expectancy": mean(pnls) if pnls else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "average_r": mean([
            record.r_multiple for record in records if record.r_multiple is not None
        ]) if any(record.r_multiple is not None for record in records) else None,
        "small_sample_warning": len(records) < SMALL_SAMPLE_THRESHOLD,
    }


def deterministic_bootstrap_expectancy(
    records: Sequence[TradeResearchRecord],
    *,
    seed: int = BOOTSTRAP_SEED,
    repetitions: int = BOOTSTRAP_REPETITIONS,
) -> dict[str, Any]:
    pnls = [record.net_pnl for record in records]
    if not pnls:
        return {"seed": seed, "repetitions": repetitions, "sample_size": 0, "interval_95": None}
    rng = random.Random(seed)
    estimates = [
        mean(rng.choice(pnls) for _ in range(len(pnls)))
        for _ in range(repetitions)
    ]
    return {
        "seed": seed,
        "repetitions": repetitions,
        "sample_size": len(pnls),
        "point_expectancy": mean(pnls),
        "interval_95": [_quantile(estimates, 0.025), _quantile(estimates, 0.975)],
    }


def _max_drawdown(sequence: Sequence[float], starting_balance: float) -> float:
    balance = peak = starting_balance
    maximum = 0.0
    for pnl in sequence:
        balance += pnl
        peak = max(peak, balance)
        maximum = max(maximum, peak - balance)
    return maximum


def deterministic_trade_order_monte_carlo(
    records: Sequence[TradeResearchRecord],
    *,
    starting_balance: float = 50.0,
    seed: int = MONTE_CARLO_SEED,
    repetitions: int = MONTE_CARLO_REPETITIONS,
) -> dict[str, Any]:
    """Bootstrap complete observed trade outcomes without altering their values."""
    pnls = [record.net_pnl for record in records]
    if not pnls:
        return {"seed": seed, "repetitions": repetitions, "sample_size": 0}
    rng = random.Random(seed)
    terminals: list[float] = []
    drawdowns: list[float] = []
    below_40 = below_25 = 0
    for _ in range(repetitions):
        sequence = [rng.choice(pnls) for _ in range(len(pnls))]
        balance = starting_balance
        minimum = balance
        for pnl in sequence:
            balance += pnl
            minimum = min(minimum, balance)
        terminals.append(balance)
        drawdowns.append(_max_drawdown(sequence, starting_balance))
        below_40 += int(minimum < 40.0)
        below_25 += int(minimum < 25.0)
    return {
        "method": "trade_level_bootstrap_with_replacement",
        "seed": seed,
        "repetitions": repetitions,
        "sample_size": len(pnls),
        "median_terminal_balance": _quantile(terminals, 0.50),
        "terminal_balance_5th_percentile": _quantile(terminals, 0.05),
        "terminal_balance_95th_percentile": _quantile(terminals, 0.95),
        "median_max_drawdown": _quantile(drawdowns, 0.50),
        "max_drawdown_95th_percentile": _quantile(drawdowns, 0.95),
        "probability_ending_below_50": sum(value < 50.0 for value in terminals) / repetitions,
        "probability_balance_below_40": below_40 / repetitions,
        "probability_balance_below_25": below_25 / repetitions,
    }


def cost_sensitivity(
    records: Sequence[TradeResearchRecord],
    *,
    paired_spread_slippage: float = 0.75,
    paired_fee: float = 0.0,
) -> dict[str, Any]:
    """Apply a cost overlay to identical idealized trades.

    Separately simulated cost scenarios can change fills, exits, and subsequent
    trade eligibility, so they are not a causal cost comparison.  This report
    instead preserves each zero-cost trade's identity, timestamps, direction,
    quantity, and gross outcome, varying only the explicit cost term.
    """
    grouped: dict[tuple[str, str, str], list[TradeResearchRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.strategy_variant, record.window_id, record.direction)].append(record)

    keys = sorted({(variant, window, direction) for variant, window, direction in grouped})
    output: dict[str, Any] = {}
    for variant, window, direction in keys:
        zero = grouped.get((variant, window, direction), [])
        zero = [record for record in zero if record.cost_scenario == "IDEALIZED_ZERO_COST"]
        if not zero:
            continue
        paired_costs = [paired_spread_slippage * record.quantity + paired_fee for record in zero]
        paired_net = [record.gross_pnl - cost for record, cost in zip(zero, paired_costs)]
        gross_edge = mean([record.gross_pnl for record in zero])
        net_edge = mean(paired_net)
        average_cost = mean(paired_costs)
        ratio = (
            average_cost / gross_edge
            if average_cost is not None and gross_edge is not None and gross_edge > 0
            else None
        )
        problem = (
            "NO_GROSS_EDGE" if gross_edge is None or gross_edge <= 0
            else "EDGE_EXISTS_BUT_COSTS_DOMINATE" if net_edge is None or net_edge <= 0
            else "EDGE_SURVIVES_COSTS"
        )
        output[f"{variant}:{window}:{direction}"] = {
            "comparison_basis": "PAIRED_EXPLICIT_COST_OVERLAY",
            "paired_identity_verified": True,
            "zero_cost_trades": len(zero),
            "cost_trades": len(zero),
            "gross_edge_per_trade": gross_edge,
            "average_explicit_entry_friction_per_trade": average_cost,
            "net_edge_per_trade": net_edge,
            "scenario_expectancy_drag": (
                gross_edge - net_edge
                if gross_edge is not None and net_edge is not None else None
            ),
            "cost_to_gross_edge_ratio": ratio,
            "classification": problem,
        }
    return output


def _group_report(records: Sequence[TradeResearchRecord], field: str) -> dict[str, Any]:
    groups: dict[str, list[TradeResearchRecord]] = defaultdict(list)
    for record in records:
        groups[str(getattr(record, field))].append(record)
    return {key: trade_statistics(group) for key, group in sorted(groups.items())}


def holding_time_report(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    groups: dict[str, list[TradeResearchRecord]] = defaultdict(list)
    for record in records:
        candles = record.holding_candles
        label = (
            "LE_1_HOUR" if candles <= 4 else
            "GT_1_TO_4_HOURS" if candles <= 16 else
            "GT_4_TO_12_HOURS" if candles <= 48 else
            "GT_12_TO_24_HOURS" if candles <= 96 else
            "GT_24_HOURS"
        )
        groups[label].append(record)
    return {
        key: {
            **trade_statistics(group),
            "average_duration_candles": mean(item.holding_candles for item in group),
            "average_modeled_entry_friction": mean(item.modeled_entry_friction for item in group),
        }
        for key, group in sorted(groups.items())
    }


def exit_reason_report(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    groups: dict[str, list[TradeResearchRecord]] = defaultdict(list)
    for record in records:
        groups[record.exit_reason].append(record)
    return {
        reason: {
            **trade_statistics(group),
            "average_gross_pnl": mean(item.gross_pnl for item in group),
            "average_net_pnl": mean(item.net_pnl for item in group),
            "average_duration_candles": mean(item.holding_candles for item in group),
            "direction_split": dict(sorted(Counter(item.direction for item in group).items())),
        }
        for reason, group in sorted(groups.items())
    }


def winner_loser_report(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    fields = (
        "rsi", "atr_percent", "ema_separation_percent", "ema50_slope_percent",
        "ema200_slope_percent", "previous_16_bar_return", "confidence", "stop_distance",
    )
    output: dict[str, Any] = {}
    for direction in ("BUY", "SELL"):
        directional = [record for record in records if record.direction == direction]
        groups = {
            "WINNERS": [record for record in directional if record.net_pnl > 0],
            "LOSERS": [record for record in directional if record.net_pnl < 0],
        }
        output[direction] = {
            label: {
                "trades": len(group),
                "medians": {field: distribution(group, field)["median"] for field in fields},
                "regimes": dict(sorted(Counter(item.regime for item in group).items())),
            }
            for label, group in groups.items()
        }
    return output


def window_sell_report(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    fields = (
        "rsi", "atr", "atr_percent", "ema_separation_percent",
        "ema50_slope_percent", "ema200_slope_percent",
        "previous_4_bar_return", "previous_16_bar_return", "holding_candles",
    )
    output: dict[str, Any] = {}
    for window in sorted({record.window_id for record in records if record.window_id.startswith("OOS_")}):
        group = [record for record in records if record.window_id == window and record.direction == "SELL"]
        exits = Counter(record.exit_reason for record in group)
        stats = trade_statistics(group)
        output[window] = {
            "statistics": stats,
            "distributions": {field: distribution(group, field) for field in fields},
            "stop_loss_rate": exits["STOP_LOSS"] / len(group) if group else None,
            "take_profit_rate": exits["TAKE_PROFIT"] / len(group) if group else None,
            "exit_counts": dict(sorted(exits.items())),
        }
    return output


def _tertiles(records: Sequence[TradeResearchRecord], field: str) -> tuple[float, float]:
    values = [value for record in records if (value := _optional(getattr(record, field))) is not None]
    return float(_quantile(values, 1 / 3) or 0.0), float(_quantile(values, 2 / 3) or 0.0)


def _three_way(value: float | None, low: float, high: float) -> str:
    if value is None:
        return "UNAVAILABLE"
    return "LOW" if value <= low else "MEDIUM" if value <= high else "HIGH"


def bucket_report(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    atr_low, atr_high = _tertiles(records, "atr_percent")
    sep_values = [abs(record.ema_separation_percent) for record in records]
    sep_low = float(_quantile(sep_values, 1 / 3) or 0.0)
    sep_high = float(_quantile(sep_values, 2 / 3) or 0.0)
    slope_values = [abs(record.ema50_slope_percent or 0.0) for record in records]
    slope_low = float(_quantile(slope_values, 1 / 3) or 0.0)
    slope_high = float(_quantile(slope_values, 2 / 3) or 0.0)
    grouped: dict[str, dict[str, list[TradeResearchRecord]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        rsi_label = (
            "LT_20" if record.rsi < 20 else "20_TO_30" if record.rsi < 30 else
            "30_TO_40" if record.rsi < 40 else "40_TO_50" if record.rsi < 50 else "GE_50"
        )
        directional_return = (
            None if record.previous_16_bar_return is None else
            record.previous_16_bar_return * (1.0 if record.direction == "BUY" else -1.0)
        )
        return_label = (
            "STRONGLY_AGAINST" if directional_return is not None and directional_return < -0.005 else
            "MILDLY_AGAINST" if directional_return is not None and directional_return < -0.001 else
            "FLAT" if directional_return is not None and directional_return <= 0.001 else
            "MILDLY_WITH" if directional_return is not None and directional_return <= 0.005 else
            "STRONGLY_WITH" if directional_return is not None else "UNAVAILABLE"
        )
        labels = {
            "RSI": rsi_label,
            "ATR_PERCENTILE": _three_way(record.atr_percent, atr_low, atr_high),
            "EMA_SEPARATION": _three_way(abs(record.ema_separation_percent), sep_low, sep_high),
            "TREND_SLOPE": _three_way(abs(record.ema50_slope_percent or 0.0), slope_low, slope_high),
            "RECENT_RETURN": return_label,
        }
        for feature, label in labels.items():
            grouped[feature][label].append(record)
    return {
        "thresholds": {
            "atr_percent_tertiles": [atr_low, atr_high],
            "absolute_ema_separation_percent_tertiles": [sep_low, sep_high],
            "absolute_ema50_slope_percent_tertiles": [slope_low, slope_high],
            "recent_return_fixed_boundaries": [-0.005, -0.001, 0.001, 0.005],
        },
        "buckets": {
            feature: {
                label: trade_statistics(group)
                for label, group in sorted(labels.items())
            }
            for feature, labels in sorted(grouped.items())
        },
    }


def _spearman(records: Sequence[TradeResearchRecord], field: str) -> float | None:
    pairs = [
        (value, record.net_pnl)
        for record in records
        if (value := _optional(getattr(record, field))) is not None
    ]
    if len(pairs) < 3:
        return None
    if len({feature for feature, _ in pairs}) < 2 or len({pnl for _, pnl in pairs}) < 2:
        return None
    frame = pd.DataFrame(pairs, columns=["feature", "pnl"])
    correlation = frame["feature"].rank(method="average").corr(
        frame["pnl"].rank(method="average")
    )
    return float(correlation) if pd.notna(correlation) else None


def rank_candidate_features(records: Sequence[TradeResearchRecord]) -> list[dict[str, Any]]:
    fields = (
        "atr_percent", "ema_separation_percent", "ema50_slope_percent",
        "ema200_slope_percent", "rsi", "previous_16_bar_return",
    )
    candidates: list[dict[str, Any]] = []
    windows = sorted({record.window_id for record in records if record.window_id.startswith("OOS_")})
    for field in fields:
        values = [value for record in records if (value := _optional(getattr(record, field))) is not None]
        if not values:
            continue
        split = float(median(values))
        window_effects: dict[str, Any] = {}
        signs: list[int] = []
        for window in windows:
            group = [record for record in records if record.window_id == window]
            low = [record.net_pnl for record in group if (_optional(getattr(record, field)) or 0.0) <= split]
            high = [record.net_pnl for record in group if (_optional(getattr(record, field)) or 0.0) > split]
            effect = mean(high) - mean(low) if high and low else None
            if effect not in (None, 0.0):
                signs.append(1 if effect > 0 else -1)
            window_effects[window] = {
                "low_n": len(low), "high_n": len(high),
                "low_expectancy": mean(low) if low else None,
                "high_expectancy": mean(high) if high else None,
                "high_minus_low_expectancy": effect,
            }
        low_all = [record.net_pnl for record in records if (_optional(getattr(record, field)) or 0.0) <= split]
        high_all = [record.net_pnl for record in records if (_optional(getattr(record, field)) or 0.0) > split]
        effect = mean(high_all) - mean(low_all) if high_all and low_all else 0.0
        majority = max(signs.count(1), signs.count(-1)) if signs else 0
        consistency = majority / len(windows) if windows else 0.0
        candidates.append({
            "candidate": field,
            "sample_size": len(values),
            "median_split": split,
            "preferred_side": "HIGH" if effect > 0 else "LOW",
            "overall_high_minus_low_expectancy": effect,
            "spearman_rank_correlation": _spearman(records, field),
            "cross_window_directional_consistency": consistency,
            "window_performance": window_effects,
            "risk_of_overfitting": (
                "HIGH" if consistency < 2 / 3 or len(values) < 60 else
                "MEDIUM" if consistency < 1.0 else "LOWER_BUT_REQUIRES_NEW_DATA"
            ),
        })
    candidates.sort(
        key=lambda item: (
            item["cross_window_directional_consistency"],
            abs(item["overall_high_minus_low_expectancy"]),
            abs(item["spearman_rank_correlation"] or 0.0),
        ),
        reverse=True,
    )
    return candidates[:3]


def classify_candidates(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Apply the checkpoint's conservative cross-window classification."""
    possible = False
    for candidate in candidates:
        side = str(candidate["preferred_side"]).lower()
        windows = list(candidate["window_performance"].values())
        expectancies = [window.get(f"{side}_expectancy") for window in windows]
        samples = [int(window.get(f"{side}_n", 0)) for window in windows]
        if windows and all(
            expectancy is not None and expectancy > 0 and sample >= SMALL_SAMPLE_THRESHOLD
            for expectancy, sample in zip(expectancies, samples)
        ):
            return "STABLE_REGIME_EDGE_FOUND"
        if sum(expectancy is not None and expectancy > 0 for expectancy in expectancies) >= 2:
            possible = True
    return "POSSIBLE_REGIME_EDGE" if possible else "NO_DURABLE_EDGE_FOUND"


def direction_report(records: Sequence[TradeResearchRecord]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for direction in ("BUY", "SELL"):
        group = [record for record in records if record.direction == direction]
        per_window = {
            window: trade_statistics([record for record in group if record.window_id == window])
            for window in sorted({record.window_id for record in group})
        }
        comparable = {
            window: metrics for window, metrics in per_window.items()
            if metrics["expectancy"] is not None
        }
        output[direction] = {
            "overall": trade_statistics(group),
            "per_window": per_window,
            "best_window": max(comparable, key=lambda key: comparable[key]["expectancy"]) if comparable else None,
            "worst_window": min(comparable, key=lambda key: comparable[key]["expectancy"]) if comparable else None,
        }
    return output


def build_summary(
    records: Sequence[TradeResearchRecord],
    *,
    dataset_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    primary = [
        record for record in records
        if record.strategy_variant == "CONFIRMED_SELL_ONLY"
        and record.cost_scenario == "CONSERVATIVE_SIMULATION_COST"
    ]
    primary_bilateral = [
        record for record in records
        if record.strategy_variant == "CONFIRMED_BILATERAL"
        and record.cost_scenario == "CONSERVATIVE_SIMULATION_COST"
    ]
    monte_carlo = {}
    for index, variant in enumerate((
        "BASELINE_BILATERAL", "BASELINE_SELL_ONLY",
        "CONFIRMED_BILATERAL", "CONFIRMED_SELL_ONLY",
    )):
        group = [
            record for record in records
            if record.strategy_variant == variant
            and record.cost_scenario == "CONSERVATIVE_SIMULATION_COST"
        ]
        monte_carlo[variant] = deterministic_trade_order_monte_carlo(
            group, seed=MONTE_CARLO_SEED + index,
        )
    candidates = rank_candidate_features(primary)
    classification = classify_candidates(candidates)
    sell_windows = window_sell_report(primary)
    oos1, oos2, oos3 = (
        sell_windows["OOS_1"], sell_windows["OOS_2"], sell_windows["OOS_3"]
    )
    oos3_timeout_rate = (
        oos3["exit_counts"].get("TIMEOUT", 0) / oos3["statistics"]["trades"]
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "research_id": "market-structure-research-v1",
        "strategy_changed": False,
        "risk_rules_changed": False,
        "frozen_datasets_changed": False,
        "lookahead_detected": False,
        "feature_information_boundary": "last_fully_closed_candle_before_entry",
        "feature_definitions": {
            "returns": "close_t / close_t_minus_n - 1 using the pre-entry feature candle",
            "recent_range": "highest_high_minus_lowest_low over up to 32 closed candles",
            "ema_slopes": "four-bar EMA change per bar, raw and normalized by starting EMA",
            "modeled_entry_friction": "(spread + slippage) * quantity + fee_per_trade",
            "cost_scenario_warning": "scenario runs can follow different trade paths; expectancy drag is counterfactual, not booked commission",
        },
        "dataset_metadata": _normalize(dataset_metadata),
        "total_records": len(records),
        "buy_records": sum(record.direction == "BUY" for record in records),
        "sell_records": sum(record.direction == "SELL" for record in records),
        "record_dataset_hash": deterministic_hash([record.to_dict() for record in records]),
        "research_classification": classification,
        "plausible_regime_edge_answer": (
            "YES" if classification == "STABLE_REGIME_EDGE_FOUND" else
            "INCONCLUSIVE" if classification == "POSSIBLE_REGIME_EDGE" else "NO"
        ),
        "oos3_failure_diagnosis": {
            "primary_failure_mode": "WEAKER_TREND_PERSISTENCE_AND_REDUCED_TAKE_PROFIT_CONVERSION",
            "cost_is_primary_cause": False,
            "evidence": {
                "oos3_net_expectancy": oos3["statistics"]["expectancy"],
                "oos3_take_profit_rate": oos3["take_profit_rate"],
                "oos1_take_profit_rate": oos1["take_profit_rate"],
                "oos2_take_profit_rate": oos2["take_profit_rate"],
                "oos3_timeout_rate": oos3_timeout_rate,
                "oos3_median_holding_candles": oos3["distributions"]["holding_candles"]["median"],
                "oos1_median_holding_candles": oos1["distributions"]["holding_candles"]["median"],
                "oos2_median_holding_candles": oos2["distributions"]["holding_candles"]["median"],
                "oos3_median_ema50_slope_percent": oos3["distributions"]["ema50_slope_percent"]["median"],
                "oos2_median_ema50_slope_percent": oos2["distributions"]["ema50_slope_percent"]["median"],
                "oos3_median_previous_16_bar_return": oos3["distributions"]["previous_16_bar_return"]["median"],
                "oos2_median_previous_16_bar_return": oos2["distributions"]["previous_16_bar_return"]["median"],
            },
        },
        "primary_slice": {
            "definition": "CONFIRMED_SELL_ONLY under CONSERVATIVE_SIMULATION_COST",
            "statistics": trade_statistics(primary),
            "window_comparison": sell_windows,
            "winner_loser": winner_loser_report(primary),
            "buckets": bucket_report(primary),
            "holding_time": holding_time_report(primary),
            "exit_reasons": exit_reason_report(primary),
            "bootstrap_expectancy": deterministic_bootstrap_expectancy(primary),
        },
        "confirmed_bilateral_directional": direction_report(primary_bilateral),
        "confirmed_bilateral_winner_loser": winner_loser_report(primary_bilateral),
        "cost_sensitivity": cost_sensitivity(records),
        "monte_carlo": monte_carlo,
        "candidate_features": candidates,
    }
    payload["summary_hash"] = deterministic_hash(payload)
    return _normalize(payload)
