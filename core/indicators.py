"""
JQE Canonical Indicator Engine
"""

import pandas as pd


def calculate_indicators(df):
    """Calculates canonical indicators and provides compatibility aliases.
    
    Provides primary canonical names:
        EMA50, EMA200, RSI, ATR
        
    Provides legacy aliases for strategy/features/feature_engine:
        EMA_50, EMA_200, RSI_14, ATR_14
    """

    data = df.copy()

    # Trend
    data["EMA50"] = data["close"].ewm(span=50, adjust=False).mean()
    data["EMA200"] = data["close"].ewm(span=200, adjust=False).mean()

    # Legacy aliases
    data["EMA_50"] = data["EMA50"]
    data["EMA_200"] = data["EMA200"]

    # RSI
    delta = data["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    
    data["RSI"] = 100 - (100 / (1 + rs))
    
    # Legacy alias
    data["RSI_14"] = data["RSI"]

    # ATR
    high_low = data["high"] - data["low"]
    high_close = abs(data["high"] - data["close"].shift())
    low_close = abs(data["low"] - data["close"].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)

    data["ATR"] = true_range.rolling(14).mean()
    
    # Legacy alias
    data["ATR_14"] = data["ATR"]

    return data