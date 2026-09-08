"""Strategy-independent market-regime discovery and corpus selection."""
from __future__ import annotations

import json
import math
import statistics
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from broker.types import Candle, Timeframe
from data.coverage import validate_historical_coverage
from data.dataset import canonical_dataset_hash
from data.storage import CandleStore
from research.strategy_v2 import DEVELOPMENT_WINDOWS, HOLDOUT_WINDOWS, deterministic_hash


WINDOW_DAYS = 28
DISCOVERY_WINDOWS = (
    ("DISCOVERY_01", datetime(2026, 3, 2, tzinfo=timezone.utc), datetime(2026, 3, 29, tzinfo=timezone.utc)),
    ("DISCOVERY_02", datetime(2026, 4, 6, tzinfo=timezone.utc), datetime(2026, 5, 3, tzinfo=timezone.utc)),
    ("DISCOVERY_03", datetime(2026, 5, 26, tzinfo=timezone.utc), datetime(2026, 6, 22, tzinfo=timezone.utc)),
    ("DISCOVERY_04", datetime(2026, 7, 6, tzinfo=timezone.utc), datetime(2026, 8, 2, tzinfo=timezone.utc)),
    ("DISCOVERY_05", datetime(2026, 8, 4, tzinfo=timezone.utc), datetime(2026, 8, 31, tzinfo=timezone.utc)),
)
EXCLUDED_WINDOWS = (
    *HOLDOUT_WINDOWS,
)


@dataclass(frozen=True, slots=True)
class RegimeWindow:
    window_id: str
    start: datetime
    end: datetime
    candle_count: int
    dataset_hash: str
    window_return_percent: float
    realized_volatility: float
    atr_percent_median: float
    range_percent: float
    directional_efficiency: float
    up_candle_percent: float
    down_candle_percent: float
    direction_label: str
    volatility_label: str
    efficiency_label: str
    coverage_state: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["end"] = self.end.isoformat()
        return payload


def overlaps(start: datetime, end: datetime, other_start: datetime, other_end: datetime) -> bool:
    return start < other_end and end >= other_start


def assert_not_protected(start: datetime, end: datetime) -> None:
    for name, protected_start, protected_end, *_ in EXCLUDED_WINDOWS:
        if overlaps(start, end, protected_start, protected_end):
            raise PermissionError(f"Window overlaps protected evidence: {name}")


def exclusion_registry() -> tuple[dict[str, Any], ...]:
    return tuple({"window_id": name, "start": start.isoformat(), "end": end.isoformat(),
                  "dataset_hash": extra if isinstance(extra, str) and extra.startswith("sha256:") else None,
                  "purpose": "LOCKED_HOLDOUT" if name in {x[0] for x in HOLDOUT_WINDOWS} else "EXISTING_DEVELOPMENT_EVIDENCE",
                  "access_policy": "EXCLUDED_FROM_REGIME_DISCOVERY_SELECTION"}
                 for name, start, end, *extra in EXCLUDED_WINDOWS)


def direction_label(return_percent: float) -> str:
    if return_percent >= 4.0:
        return "STRONG_UP"
    if return_percent >= 1.0:
        return "UP"
    if return_percent <= -4.0:
        return "STRONG_DOWN"
    if return_percent <= -1.0:
        return "DOWN"
    return "SIDEWAYS"


def efficiency_label(value: float) -> str:
    if value < 0.25:
        return "LOW_EFFICIENCY"
    if value < 0.50:
        return "MEDIUM_EFFICIENCY"
    return "HIGH_EFFICIENCY"


def volatility_label(value: float, low: float, high: float) -> str:
    if value <= low:
        return "LOW_VOLATILITY"
    if value <= high:
        return "NORMAL_VOLATILITY"
    return "HIGH_VOLATILITY"


def _raw_metrics(candles: Sequence[Candle]) -> dict[str, float]:
    returns = [float(candles[i].close) / float(candles[i - 1].close) - 1.0 for i in range(1, len(candles))]
    absolute_moves = [abs(float(candles[i].close) - float(candles[i - 1].close)) for i in range(1, len(candles))]
    total_move = sum(absolute_moves)
    direct_move = abs(float(candles[-1].close) - float(candles[0].open))
    return {
        "window_return_percent": (float(candles[-1].close) / float(candles[0].open) - 1.0) * 100.0,
        "realized_volatility": statistics.pstdev(returns) * math.sqrt(96 * 5) if len(returns) > 1 else 0.0,
        "atr_percent_median": statistics.median((float(c.high) - float(c.low)) / float(c.close) for c in candles) * 100.0,
        "range_percent": (max(float(c.high) for c in candles) - min(float(c.low) for c in candles)) / float(candles[0].open) * 100.0,
        "directional_efficiency": direct_move / total_move if total_move else 0.0,
        "up_candle_percent": sum(value > 0 for value in returns) / len(returns) * 100.0 if returns else 0.0,
        "down_candle_percent": sum(value < 0 for value in returns) / len(returns) * 100.0 if returns else 0.0,
    }


def build_window(window_id: str, start: datetime, end: datetime, candles: Sequence[Candle], volatility_low: float, volatility_high: float) -> RegimeWindow:
    coverage = validate_historical_coverage(candles, provider="deriv", canonical_symbol="XAUUSD",
        provider_symbol="frxXAUUSD", timeframe=Timeframe.M15, start=start, end=end)
    if coverage.missing_count or coverage.unexpected_returned_count:
        raise ValueError(f"Ineligible incomplete/unexplained window: {window_id}")
    metrics = _raw_metrics(candles)
    return RegimeWindow(window_id, start, end, len(candles), canonical_dataset_hash(candles, symbol="XAUUSD", timeframe=Timeframe.M15),
        **metrics, direction_label=direction_label(metrics["window_return_percent"]),
        volatility_label=volatility_label(metrics["realized_volatility"], volatility_low, volatility_high),
        efficiency_label=efficiency_label(metrics["directional_efficiency"]), coverage_state="COMPLETE")


def candidate_windows() -> tuple[tuple[str, datetime, datetime], ...]:
    for name, start, end in DISCOVERY_WINDOWS:
        assert_not_protected(start, end)
    return DISCOVERY_WINDOWS


def select_balanced(windows: Sequence[RegimeWindow]) -> tuple[RegimeWindow, ...]:
    """Select representative windows by market labels, then calendar order.

    The score is distance from the center of each direction class and no
    strategy result or trade statistic is consulted.
    """
    selected: list[RegimeWindow] = []
    direction_targets = ("STRONG_UP", "UP", "SIDEWAYS", "DOWN", "STRONG_DOWN")
    for label in direction_targets:
        group = [item for item in windows if item.direction_label == label]
        if not group:
            continue
        center = statistics.median(item.window_return_percent for item in group)
        selected.extend(sorted(group, key=lambda item: (abs(item.window_return_percent - center), item.start))[:2])
    # Keep selected windows non-overlapping and preserve deterministic order.
    output: list[RegimeWindow] = []
    for item in sorted(selected, key=lambda value: value.start):
        if not any(overlaps(item.start, item.end, other.start, other.end) for other in output):
            output.append(item)
    return tuple(output)


def diversity_gate(windows: Sequence[RegimeWindow]) -> bool:
    directions = {item.direction_label for item in windows}
    volatilities = {item.volatility_label for item in windows}
    return bool(directions & {"UP", "STRONG_UP"}) and "SIDEWAYS" in directions and bool(directions & {"DOWN", "STRONG_DOWN"}) and len(volatilities) >= 2


def discovery_artifact(windows: Sequence[RegimeWindow]) -> dict[str, Any]:
    payload = {"methodology": "Fixed Monday-aligned 28-day windows; direction fixed boundaries; volatility terciles from eligible discovery metrics; no strategy metrics.",
        "windows": [item.to_dict() for item in windows], "exclusions": exclusion_registry()}
    payload["artifact_hash"] = deterministic_hash(payload)
    return payload


def corpus_artifact(windows: Sequence[RegimeWindow]) -> dict[str, Any]:
    payload = {"selection_methodology": "Two representative calendar-ordered windows per direction label, nearest the class median return; overlapping selections removed.",
        "selected_windows": [item.to_dict() for item in windows], "exclusions": exclusion_registry(),
        "diversity_gate": diversity_gate(windows), "status": "FROZEN_MARKET_ONLY_BEFORE_STRATEGY_ANALYSIS"}
    payload["artifact_hash"] = deterministic_hash(payload)
    return payload


def _close_returns(candles: Sequence[Candle]) -> list[float]:
    return [float(candles[i].close) / float(candles[i - 1].close) - 1.0 for i in range(1, len(candles))]


def _bootstrap_interval(values: Sequence[float], seed: int = 62032, repetitions: int = 1000) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(repetitions))
    return means[int(repetitions * 0.025)], means[int(repetitions * 0.975) - 1]


def trend_persistence(candles: Sequence[Candle], impulse_bars: int = 16, forward_bars: int = 16, impulse_threshold_percent: float = 1.0) -> dict[str, Any]:
    closes = [float(c.close) for c in candles]
    rows = []
    for index in range(impulse_bars, len(closes) - forward_bars):
        impulse = closes[index] / closes[index - impulse_bars] - 1.0
        if abs(impulse) < impulse_threshold_percent / 100:
            continue
        forward = closes[index + forward_bars] / closes[index] - 1.0
        rows.append({"direction": "UP" if impulse > 0 else "DOWN", "impulse_return": impulse, "forward_return": forward,
                     "continued": forward * impulse > 0})
    return {"impulse_bars": impulse_bars, "forward_bars": forward_bars, "threshold_percent": impulse_threshold_percent,
            "count": len(rows), "up_count": sum(x["direction"] == "UP" for x in rows),
            "down_count": sum(x["direction"] == "DOWN" for x in rows),
            "follow_through_rate": sum(x["continued"] for x in rows) / len(rows) if rows else None,
            "median_forward_return": statistics.median(x["forward_return"] for x in rows) if rows else None,
            "bootstrap_ci": _bootstrap_interval([x["forward_return"] for x in rows]), "rows": rows}


def breakout_follow_through(candles: Sequence[Candle], range_bars: int = 20, forward_bars: int = 8) -> dict[str, Any]:
    rows = []
    for index in range(range_bars, len(candles) - forward_bars):
        prior = candles[index - range_bars:index]
        close = float(candles[index].close)
        high = max(float(c.high) for c in prior)
        low = min(float(c.low) for c in prior)
        direction = "UP" if close > high else "DOWN" if close < low else None
        if direction is None:
            continue
        forward = float(candles[index + forward_bars].close) / close - 1.0
        aligned = forward > 0 if direction == "UP" else forward < 0
        rows.append({"direction": direction, "forward_return": forward, "follow_through": aligned})
    return {"range_bars": range_bars, "forward_bars": forward_bars, "count": len(rows),
            "follow_through_rate": sum(x["follow_through"] for x in rows) / len(rows) if rows else None,
            "false_breakout_rate": sum(not x["follow_through"] for x in rows) / len(rows) if rows else None,
            "median_forward_return": statistics.median(x["forward_return"] for x in rows) if rows else None,
            "bootstrap_ci": _bootstrap_interval([x["forward_return"] for x in rows]), "rows": rows}


def mean_reversion_tendency(candles: Sequence[Candle], reference_span: int = 50, forward_bars: int = 8, stretch_atr: float = 1.5) -> dict[str, Any]:
    closes = [float(c.close) for c in candles]
    atrs = [statistics.mean(float(c.high) - float(c.low) for c in candles[max(0, i - 13):i + 1]) for i in range(len(candles))]
    ema = []
    alpha = 2 / (reference_span + 1)
    for close in closes:
        ema.append(close if not ema else alpha * close + (1 - alpha) * ema[-1])
    rows = []
    for index in range(reference_span, len(candles) - forward_bars):
        displacement = closes[index] - ema[index]
        if abs(displacement) < stretch_atr * atrs[index]:
            continue
        later_displacement = closes[index + forward_bars] - ema[index]
        toward = abs(later_displacement) < abs(displacement)
        rows.append({"direction": "ABOVE_REFERENCE" if displacement > 0 else "BELOW_REFERENCE", "displacement_atr": displacement / atrs[index], "toward_reference": toward, "forward_displacement": later_displacement})
    return {"reference_span": reference_span, "forward_bars": forward_bars, "stretch_atr": stretch_atr,
            "count": len(rows), "reversion_rate": sum(x["toward_reference"] for x in rows) / len(rows) if rows else None,
            "median_forward_displacement": statistics.median(x["forward_displacement"] for x in rows) if rows else None,
            "bootstrap_ci": _bootstrap_interval([x["forward_displacement"] for x in rows]), "rows": rows}


def market_behavior(candles: Sequence[Candle]) -> dict[str, Any]:
    returns = _close_returns(candles)
    abs_returns = [abs(value) for value in returns]
    lag1 = statistics.correlation(returns[:-1], returns[1:]) if len(returns) > 2 else 0.0
    lag4 = statistics.correlation(returns[:-4], returns[4:]) if len(returns) > 5 else 0.0
    vol_lag1 = statistics.correlation(abs_returns[:-1], abs_returns[1:]) if len(abs_returns) > 2 else 0.0
    reversals = sum(returns[i] * returns[i - 1] < 0 for i in range(1, len(returns))) / max(1, len(returns) - 1)
    return {"trend_persistence": trend_persistence(candles), "breakout_follow_through": breakout_follow_through(candles),
            "mean_reversion_tendency": mean_reversion_tendency(candles),
            "return_autocorrelation": {"lag_1": lag1, "lag_4": lag4, "lag_1_ci": _bootstrap_interval(returns)},
            "volatility_clustering": {"absolute_return_lag_1": vol_lag1}, "reversal_frequency": reversals}