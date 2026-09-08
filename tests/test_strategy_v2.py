from datetime import datetime, timezone

import pytest

from research.strategy_v2 import (
    HYPOTHESES, HOLDOUT_WINDOWS, assert_holdout_closed, bootstrap_expectancy,
    classify_development, deterministic_hash, holdout_registry,
    validate_trade_chronology, validate_trade_risk,
)


def test_holdout_registry_is_locked_and_explicit() -> None:
    registry = holdout_registry()
    assert [item["window_id"] for item in registry] == ["OOS_4", "OOS_5"]
    assert all(item["status"] == "LOCKED_HOLDOUT" for item in registry)
    assert registry[0]["dataset_hash"] == HOLDOUT_WINDOWS[0][3]


def test_development_access_refuses_holdout_windows() -> None:
    with pytest.raises(PermissionError, match="LOCKED_HOLDOUT"):
        assert_holdout_closed(("BASELINE", "OOS_4"))
    assert_holdout_closed(("BASELINE", "OOS_4"), final_validation=True)


def test_hypothesis_hash_is_deterministic_and_immutable() -> None:
    first = HYPOTHESES[0]
    assert first.hypothesis_hash == deterministic_hash(first.__dict__) if hasattr(first, "__dict__") else first.hypothesis_hash.startswith("sha256:")
    assert len({hypothesis.hypothesis_hash for hypothesis in HYPOTHESES}) == 3


def test_three_hypotheses_are_pre_registered() -> None:
    assert len(HYPOTHESES) == 3
    assert {hypothesis.hypothesis_id for hypothesis in HYPOTHESES} == {
        "V2_TREND_PULLBACK", "V2_VOLATILITY_BREAKOUT", "V2_MEAN_REVERSION",
    }


def test_bootstrap_is_deterministic() -> None:
    class Trade:
        def __init__(self, pnl):
            self.net_pnl = pnl
    trades = [Trade(-1.0), Trade(2.0), Trade(3.0)]
    assert bootstrap_expectancy(trades, repetitions=100) == bootstrap_expectancy(trades, repetitions=100)


def test_development_classification_requires_multiple_positive_windows() -> None:
    positive = {"conservative": {"net_expectancy": 0.1, "executed_trades": 10, "max_drawdown": 2, "risk_validation": "PASS"},
                "zero_cost": {"net_expectancy": 0.1}}
    negative = {"conservative": {"net_expectancy": -0.1, "executed_trades": 10, "max_drawdown": 2, "risk_validation": "PASS"},
                "zero_cost": {"net_expectancy": -0.1}}
    assert classify_development([positive, positive, negative, negative]) == "REJECTED_INCONSISTENT"


def test_trade_chronology_and_risk_helpers_are_fail_closed() -> None:
    class Quantity:
        value = 1.0

    class Trade:
        signal_timestamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        entry_timestamp = datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc)
        entry_price = 100.0
        stop_price = 99.0
        quantity = Quantity()
        net_pnl = -1.0

    assert validate_trade_chronology([Trade()])
    assert validate_trade_risk([Trade()])
    Trade.entry_timestamp = Trade.signal_timestamp
    assert not validate_trade_chronology([Trade()])