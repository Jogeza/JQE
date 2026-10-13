"""Experimental feature semantics only; no signals, labels, fitting or execution."""
from datetime import datetime, timedelta
import math

import pandas as pd

from core.indicators import calculate_indicators
from research.ml_validation import FEATURES, validate_features


def closed_bar_features(raw: pd.DataFrame, *, signal_open: datetime,
                        prefix_start: datetime, spread_open: datetime,
                        recorded_spread_price: float) -> dict[str, float]:
    """M5 feature contract v1; caller must bind raw prefix/spread to frozen hashes.

    Cut raw bars before indicators. Never accept caller-supplied indicators or
    shorten the original prefix. This helper does not establish provenance or
    recreate a canonical signal and is not a dataset exporter.
    """
    for timestamp in (signal_open, prefix_start, spread_open):
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Aware timestamps required")
    if spread_open != signal_open:
        raise ValueError("Spread must bind to the signal bar, lagged relative to entry")
    if isinstance(recorded_spread_price, bool) or not math.isfinite(recorded_spread_price) or recorded_spread_price < 0:
        raise ValueError("Explicit finite recorded spread required; no fallback")
    frame = raw.loc[:, ["time", "open", "high", "low", "close"]].copy()
    if any(pd.Timestamp(t).tzinfo is None for t in frame["time"]):
        raise ValueError("Aware raw bar times required")
    if not frame["time"].is_monotonic_increasing or frame["time"].duplicated().any():
        raise ValueError("Strict bar ordering required")
    frame = frame[frame["time"] <= signal_open].reset_index(drop=True)
    if len(frame) < 201 or frame.iloc[0]["time"] != prefix_start or frame.iloc[-1]["time"] != signal_open:
        raise ValueError("Original full indicator prefix and target bar required")
    if any(b-a != timedelta(minutes=5) for a,b in zip(frame["time"].tail(4),frame["time"].tail(4).iloc[1:])):
        raise ValueError("Three-bar feature window crosses a gap")
    prices = frame[["open", "high", "low", "close"]]
    if not all(math.isfinite(float(v)) and float(v)>0 for v in prices.to_numpy().flat):
        raise ValueError("Finite positive raw prices required")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) |
        (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid raw OHLC")
    indicators = calculate_indicators(frame)
    row = indicators.iloc[-1]
    atr, close = float(row["ATR"]), float(row["close"])
    if not math.isfinite(atr) or atr <= 0:
        raise ValueError("Positive finite ATR required")
    features = {
        "rsi": float(row["RSI"]),
        "ema_distance_atr": (close-float(row["EMA50"]))/atr,
        "ema_slope_atr": (float(row["EMA50"])-float(indicators.iloc[-2]["EMA50"]))/atr,
        "atr_price_ratio": atr/close,
        "return_1_atr": (close-float(frame.iloc[-2]["close"]))/atr,
        "return_3_atr": (close-float(frame.iloc[-4]["close"]))/atr,
        "range_atr": (float(row["high"])-float(row["low"]))/atr,
        "lagged_spread_atr": float(recorded_spread_price)/atr,
    }
    validate_features(features)
    assert set(features) == FEATURES
    return features
