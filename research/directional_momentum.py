"""Direction-relative momentum graduated into the canonical FeatureEngine.

The canonical engine now scores momentum relative to the detected trend
(aligned -> STRONG, opposed -> WEAK), making canonical SELL entries
reachable. This module keeps the historical import path alive —
``research.fibonacci_confluence.FibonacciFeatures`` subclasses
``DirectionalMomentumFeatures`` — as a documented alias for the
canonical behaviour.
"""
from __future__ import annotations

from strategy.features.feature_engine import FeatureEngine
from strategy.strategy_engine import StrategyEngine


class DirectionalMomentumFeatures(FeatureEngine):
    """Alias of the canonical engine; direction-relative logic now lives there."""


def experimental_engine():
    """An explicit injected research dependency; no broker factory or settings."""
    return StrategyEngine(feature_engine=DirectionalMomentumFeatures())
