"""Experimental direction-aware momentum; not a configured live strategy.

Keep existing feature weights and thresholds, but interpret RSI strength
relative to trend direction. Evaluate only through the canonical pipeline.
"""
from __future__ import annotations

import math

from strategy.features.feature_engine import FeatureEngine
from strategy.strategy_engine import StrategyEngine


class DirectionalMomentumFeatures(FeatureEngine):
    def analyze(self, df):
        features = super().analyze(df)
        rsi = float(df.iloc[-1]['RSI_14'])
        if not math.isfinite(rsi):
            return {**features, 'momentum': 'UNKNOWN', 'confidence': 0}
        old_points = 30 if rsi > 60 else 10 if rsi < 40 else 20
        trend = features['trend']
        aligned = (trend == 'BULLISH' and rsi > 60) or (trend == 'BEARISH' and rsi < 40)
        opposed = (trend == 'BULLISH' and rsi < 40) or (trend == 'BEARISH' and rsi > 60)
        momentum, points = ('STRONG', 30) if aligned else ('WEAK', 10) if opposed else ('NEUTRAL', 20)
        return {**features, 'momentum': momentum,
                'confidence': features['confidence'] - old_points + points}


def experimental_engine():
    """An explicit injected research dependency; no broker factory or settings."""
    return StrategyEngine(feature_engine=DirectionalMomentumFeatures())
