from datetime import datetime, timezone

import pytest

from broker.types import Candle
from research.market_regime_corpus import (
    assert_not_protected, candidate_windows, direction_label, diversity_gate,
    efficiency_label, market_behavior, trend_persistence, volatility_label,
)


def test_direction_and_efficiency_labels_are_fixed() -> None:
    assert direction_label(5) == "STRONG_UP"
    assert direction_label(2) == "UP"
    assert direction_label(0) == "SIDEWAYS"
    assert direction_label(-2) == "DOWN"
    assert direction_label(-5) == "STRONG_DOWN"
    assert efficiency_label(0.1) == "LOW_EFFICIENCY"
    assert efficiency_label(0.3) == "MEDIUM_EFFICIENCY"
    assert efficiency_label(0.7) == "HIGH_EFFICIENCY"
    assert volatility_label(1, 2, 3) == "LOW_VOLATILITY"
    assert volatility_label(2.5, 2, 3) == "NORMAL_VOLATILITY"
    assert volatility_label(4, 2, 3) == "HIGH_VOLATILITY"


def test_protected_holdout_overlap_is_refused() -> None:
    with pytest.raises(PermissionError, match="OOS_4"):
        assert_not_protected(datetime(2026, 2, 1, tzinfo=timezone.utc), datetime(2026, 2, 28, tzinfo=timezone.utc))


def test_discovery_calendar_is_fixed_and_protected() -> None:
    windows = candidate_windows()
    assert len(windows) == 5
    assert all((end - start).days == 27 for _, start, end in windows)


def test_diversity_gate_requires_direction_and_two_volatility_classes() -> None:
    class Window:
        def __init__(self, direction, volatility):
            self.direction_label = direction
            self.volatility_label = volatility
    assert not diversity_gate([Window("UP", "LOW_VOLATILITY"), Window("DOWN", "LOW_VOLATILITY")])
    assert diversity_gate([Window("UP", "LOW_VOLATILITY"), Window("SIDEWAYS", "NORMAL_VOLATILITY"), Window("DOWN", "LOW_VOLATILITY")])


def test_market_behavior_outputs_are_deterministic_and_strategy_free() -> None:
    candles = [Candle(time=datetime(2026, 1, 1, tzinfo=timezone.utc) + __import__("datetime").timedelta(minutes=15 * i),
                      open=100 + i * 0.1, high=101 + i * 0.1, low=99 + i * 0.1, close=100 + i * 0.1, source="test")
               for i in range(80)]
    first = market_behavior(candles)
    assert first == market_behavior(candles)
    assert first["trend_persistence"]["count"] >= 0
    assert "pnl" not in str(first).lower()