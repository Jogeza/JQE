"""JQE Market Regime Engine.

Identifies the current market regime from indicator data.
Provides the canonical vocabulary: TRENDING, RANGING, HIGH_VOLATILITY, UNKNOWN.
"""

from __future__ import annotations

import pandas as pd

from core.logger import logger


def detect_regime(df: pd.DataFrame) -> str:
    """Detects market regime from the latest row of indicator data.

    Args:
        df: OHLC data with ``EMA50``, ``EMA200``, ``RSI``, and ``ATR``
            columns (as produced by ``core.indicators.calculate_indicators``).

    Returns:
        ``"TRENDING"``, ``"RANGING"``, ``"HIGH_VOLATILITY"``, or ``"UNKNOWN"``.
    """
    latest = df.iloc[-1]

    close = latest["close"]
    ema50 = latest.get("EMA50", latest.get("EMA_50"))
    ema200 = latest.get("EMA200", latest.get("EMA_200"))
    rsi = latest.get("RSI", latest.get("RSI_14"))
    atr = latest.get("ATR", latest.get("ATR_14"))
    
    # Calculate average ATR if available for volatility check
    avg_atr_col = "ATR" if "ATR" in df.columns else "ATR_14"
    if avg_atr_col in df.columns and len(df) > 14:
        avg_atr = df[avg_atr_col].mean()
    else:
        avg_atr = atr

    regime = "UNKNOWN"

    if atr > avg_atr * 1.5:
        regime = "HIGH_VOLATILITY"
    elif close > ema50 > ema200 and rsi > 50:
        regime = "TRENDING"
    elif close < ema50 < ema200 and rsi < 50:
        regime = "TRENDING"
    elif abs(ema50 - ema200) < atr * 0.5:
        regime = "RANGING"

    logger.info("Canonical market regime detected: {}", regime)
    return regime


def detect_legacy_regime(df: pd.DataFrame) -> str:
    """Legacy regime detection for backward compatibility.
    
    Returns:
        ``"TREND_UP"``, ``"TREND_DOWN"``, ``"RANGE"``, or ``"NO_TRADE"``.
    """
    latest = df.iloc[-1]

    close = latest["close"]
    ema50 = latest.get("EMA50", latest.get("EMA_50"))
    ema200 = latest.get("EMA200", latest.get("EMA_200"))
    rsi = latest.get("RSI", latest.get("RSI_14"))
    atr = latest.get("ATR", latest.get("ATR_14"))

    regime = "NO_TRADE"

    if close > ema50 > ema200 and rsi > 50:
        regime = "TREND_UP"
    elif close < ema50 < ema200 and rsi < 50:
        regime = "TREND_DOWN"
    elif abs(ema50 - ema200) < atr * 0.5:
        regime = "RANGE"

    return regime
