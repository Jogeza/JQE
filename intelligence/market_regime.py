"""JQE Market Regime Engine.

Identifies the current market regime from indicator data.
"""

from __future__ import annotations

import pandas as pd

from core.logger import logger


def detect_regime(df: pd.DataFrame) -> str:
    """Detects market regime from the latest row of indicator data.

    Args:
        df: OHLC data with ``EMA50``, ``EMA200``, ``RSI``, and ``ATR``
            columns (as produced by ``core.indicators.
            calculate_indicators``).

    Returns:
        ``"TREND_UP"``, ``"TREND_DOWN"``, ``"RANGE"``, or
        ``"NO_TRADE"`` (ambiguous/no clear regime).
    """
    latest = df.iloc[-1]

    close = latest["close"]
    ema50 = latest["EMA50"]
    ema200 = latest["EMA200"]
    rsi = latest["RSI"]
    atr = latest["ATR"]

    regime = "NO_TRADE"

    if close > ema50 > ema200 and rsi > 50:
        regime = "TREND_UP"
    elif close < ema50 < ema200 and rsi < 50:
        regime = "TREND_DOWN"
    elif abs(ema50 - ema200) < atr * 0.5:
        regime = "RANGE"

    logger.info("Market regime detected: {}", regime)
    return regime
