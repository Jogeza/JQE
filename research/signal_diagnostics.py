"""Bounded diagnostics for the unchanged canonical JQE signal pipeline."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Any, Sequence

import pandas as pd

from broker.types import Candle
from core.indicators import calculate_indicators
from core.regime import detect_regime
from strategy.pipeline import generate_trading_signal

WARMUP_CANDLES = 200


@dataclass(frozen=True, slots=True)
class SignalDiagnosticResult:
    candle_count: int
    warmup_candles: int
    evaluations: int
    buy_signals: int
    sell_signals: int
    no_signal: int
    reason_counts: dict[str, int]
    regime_counts: dict[str, int]
    condition_pass_counts: dict[str, int]
    indicator_sanity: dict[str, dict[str, float | int | None]]


def _reason(signal: dict[str, Any]) -> str:
    intelligence = signal["intelligence"]
    regime = intelligence.get("regime", "UNKNOWN")
    trend = intelligence.get("trend", "UNKNOWN")
    momentum = intelligence.get("momentum", "UNKNOWN")
    if regime == "HIGH_VOLATILITY":
        return "REGIME_HIGH_VOLATILITY"
    if regime == "RANGING":
        return "REGIME_RANGING_NO_DIRECTIONAL_ADVANTAGE"
    if regime == "UNKNOWN":
        return "REGIME_UNKNOWN_NO_STRATEGY_MATCH"
    if regime == "TRENDING" and trend == "BULLISH" and momentum != "STRONG":
        return "BULLISH_MOMENTUM_NOT_STRONG"
    if regime == "TRENDING" and trend == "BEARISH" and momentum != "STRONG":
        return "BEARISH_MOMENTUM_NOT_STRONG"
    if regime == "TRENDING" and trend not in ("BULLISH", "BEARISH"):
        return "TREND_DIRECTION_UNAVAILABLE"
    return "NO_SIGNAL_UNCLASSIFIED"


def _indicator_stats(frame: pd.DataFrame, name: str) -> dict[str, float | int | None]:
    numeric = pd.to_numeric(frame[name], errors="coerce")
    valid = numeric.dropna()
    return {
        "valid": int(valid.size), "missing": int(numeric.size - valid.size),
        "minimum": float(valid.min()) if not valid.empty else None,
        "maximum": float(valid.max()) if not valid.empty else None,
        "median": float(median(valid.tolist())) if not valid.empty else None,
    }


def diagnose_signals(candles: Sequence[Candle], symbol: str = "XAUUSD") -> SignalDiagnosticResult:
    frame = calculate_indicators(pd.DataFrame([candle.model_dump() for candle in candles]))
    reasons: Counter[str] = Counter()
    regimes: Counter[str] = Counter()
    passes: Counter[str] = Counter()
    buys = sells = 0
    for index in range(WARMUP_CANDLES, len(frame)):
        history = frame.iloc[: index + 1]
        raw_regime = detect_regime(history)
        signal = generate_trading_signal(history, symbol, regime=raw_regime, include_details=True)
        intel = signal["intelligence"]
        regime, trend, momentum = intel["regime"], intel["trend"], intel["momentum"]
        rsi = float(intel["rsi"])
        regimes[regime] += 1
        passes["REGIME_TRENDING"] += regime == "TRENDING"
        passes["REGIME_NOT_HIGH_VOLATILITY"] += regime != "HIGH_VOLATILITY"
        passes["BULLISH_TREND"] += trend == "BULLISH"
        passes["BEARISH_TREND"] += trend == "BEARISH"
        passes["MOMENTUM_STRONG"] += momentum == "STRONG"
        passes["RSI_BUY_GT_60"] += rsi > 60
        passes["RSI_SELL_LT_50"] += rsi < 50
        passes["BUY_PARTIAL_TRENDING_BULLISH"] += regime == "TRENDING" and trend == "BULLISH"
        passes["SELL_PARTIAL_TRENDING_BEARISH"] += regime == "TRENDING" and trend == "BEARISH"
        passes["FULL_BUY"] += signal["signal"] == "BUY"
        passes["FULL_SELL"] += signal["signal"] == "SELL"
        if signal["signal"] == "BUY": buys += 1
        elif signal["signal"] == "SELL": sells += 1
        else: reasons[_reason(signal)] += 1
    evaluations = max(0, len(frame) - WARMUP_CANDLES)
    return SignalDiagnosticResult(
        len(frame), min(len(frame), WARMUP_CANDLES), evaluations, buys, sells,
        evaluations - buys - sells, dict(sorted(reasons.items())),
        dict(sorted(regimes.items())), dict(sorted(passes.items())),
        {name: _indicator_stats(frame.iloc[WARMUP_CANDLES:], name)
         for name in ("EMA50", "EMA200", "RSI", "ATR")},
    )
