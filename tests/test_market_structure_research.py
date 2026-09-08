"""Tests for deterministic, entry-bounded market-structure research."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backtesting.models import (
    BacktestDecision,
    BacktestExecutionAssumptions,
    BacktestExitReason,
    BacktestIndicatorObservation,
    BacktestTrade,
)
from broker.types import Candle, ExecutionQuantity, ExecutionQuantityUnit, Timeframe
from research.market_structure_research import (
    bucket_report,
    classify_candidates,
    cost_sensitivity,
    deterministic_bootstrap_expectancy,
    deterministic_trade_order_monte_carlo,
    extract_trade_records,
    rank_candidate_features,
    serialize_records,
    trade_statistics,
    window_sell_report,
)


def _candles() -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for index in range(48):
        close = 120.0 - index * 0.1
        candles.append(Candle(
            time=start + timedelta(minutes=15 * index),
            open=close + 0.05,
            high=close + 0.5,
            low=close - 0.5,
            close=close,
            source="fixture",
        ))
    return candles


def _result(candles: list[Candle], *, net_pnl: float = 1.0) -> SimpleNamespace:
    quantity = ExecutionQuantity(
        value=2.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS,
    )
    trade = BacktestTrade(
        trade_id=1,
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        direction="SELL",
        signal_timestamp=candles[38].time,
        entry_timestamp=candles[40].time,
        entry_price=candles[40].open,
        exit_timestamp=candles[45].time,
        exit_price=candles[40].open - net_pnl / quantity.value,
        stop_price=candles[40].open + 1.5,
        target_price=candles[40].open - 3.0,
        quantity=quantity,
        gross_pnl=net_pnl,
        costs=0.0,
        net_pnl=net_pnl,
        balance_before=50.0,
        balance_after=50.0 + net_pnl,
        holding_candles=6,
        exit_reason=(
            BacktestExitReason.TAKE_PROFIT if net_pnl > 0
            else BacktestExitReason.STOP_LOSS
        ),
    )
    return SimpleNamespace(
        dataset_hash="sha256:" + "a" * 64,
        trades=(trade,),
        indicators=(BacktestIndicatorObservation(
            candle_index=39,
            timestamp=candles[39].time,
            ema50=116.0,
            ema200=118.0,
            rsi=30.0,
            atr=1.0,
            regime="TREND_DOWN",
        ),),
        decisions=(BacktestDecision(
            candle_index=38,
            timestamp=candles[38].time,
            signal="SELL",
            confidence=80,
            state="QUEUED",
        ),),
        execution=BacktestExecutionAssumptions(),
        strategy={"require_confirmation": True},
    )


def _record(*, net_pnl: float = 1.0):
    candles = _candles()
    return extract_trade_records(
        _result(candles, net_pnl=net_pnl),
        candles,
        window_id="OOS_1",
        strategy_variant="CONFIRMED_SELL_ONLY",
        cost_scenario="CONSERVATIVE_SIMULATION_COST",
    )[0]


def test_features_use_last_closed_candle_before_entry() -> None:
    candles = _candles()
    record = extract_trade_records(
        _result(candles), candles, window_id="OOS_1",
        strategy_variant="CONFIRMED_SELL_ONLY",
        cost_scenario="CONSERVATIVE_SIMULATION_COST",
    )[0]

    assert record.signal_timestamp == candles[38].time
    assert record.feature_timestamp == candles[39].time
    assert record.entry_timestamp == candles[40].time
    assert record.feature_timestamp < record.entry_timestamp
    assert record.confidence == 80


def test_future_market_and_outcome_changes_do_not_change_predictors() -> None:
    original = _candles()
    changed = list(original)
    for index in range(40, len(changed)):
        candle = changed[index]
        changed[index] = candle.model_copy(update={
            "open": candle.open + 10.0,
            "high": candle.high + 20.0,
            "low": candle.low + 5.0,
            "close": candle.close + 10.0,
        })
    first = extract_trade_records(
        _result(original, net_pnl=1.0), original, window_id="OOS_1",
        strategy_variant="CONFIRMED_SELL_ONLY",
        cost_scenario="CONSERVATIVE_SIMULATION_COST",
    )[0]
    second_result = _result(changed, net_pnl=-3.0)
    second = extract_trade_records(
        second_result, changed, window_id="OOS_1",
        strategy_variant="CONFIRMED_SELL_ONLY",
        cost_scenario="CONSERVATIVE_SIMULATION_COST",
    )[0]

    predictor_fields = (
        "feature_timestamp", "close", "ema50", "ema200", "rsi", "atr",
        "ema_separation_percent", "previous_4_bar_return",
        "previous_16_bar_return", "distance_from_recent_high",
        "distance_from_recent_low", "local_range", "ema50_slope_percent",
    )
    assert tuple(getattr(first, field) for field in predictor_fields) == tuple(
        getattr(second, field) for field in predictor_fields
    )
    assert first.net_pnl != second.net_pnl


def test_trade_feature_serialization_is_deterministic() -> None:
    record = _record()
    assert serialize_records([record]) == serialize_records([record])
    assert serialize_records([replace(record, record_id="b"), record]) == serialize_records(
        [record, replace(record, record_id="b")]
    )


def test_cost_attribution_and_window_isolation() -> None:
    base = _record(net_pnl=0.10)
    zero = replace(
        base,
        record_id="zero",
        cost_scenario="IDEALIZED_ZERO_COST",
        modeled_entry_friction=0.0,
    )
    cost = replace(
        base,
        record_id="cost",
        net_pnl=-0.05,
        cost_scenario="CONSERVATIVE_SIMULATION_COST",
        modeled_entry_friction=0.04,
    )
    other_window = replace(cost, record_id="other", window_id="OOS_3")

    report = cost_sensitivity([zero, cost, other_window])

    oos1 = report["CONFIRMED_SELL_ONLY:OOS_1:SELL"]
    assert oos1["gross_edge_per_trade"] == pytest.approx(0.10)
    expected_cost = 0.75 * zero.quantity
    assert oos1["comparison_basis"] == "PAIRED_EXPLICIT_COST_OVERLAY"
    assert oos1["paired_identity_verified"] is True
    assert oos1["average_explicit_entry_friction_per_trade"] == pytest.approx(expected_cost)
    assert oos1["net_edge_per_trade"] == pytest.approx(zero.gross_pnl - expected_cost)
    assert oos1["scenario_expectancy_drag"] == pytest.approx(expected_cost)
    assert "CONFIRMED_SELL_ONLY:OOS_3:SELL" not in report


def test_buckets_are_deterministic_and_warn_for_small_samples() -> None:
    base = _record()
    records = [
        replace(
            base,
            record_id=str(index),
            rsi=15.0 + index * 5,
            atr_percent=0.001 + index * 0.001,
            net_pnl=1.0 if index % 2 else -1.0,
        )
        for index in range(8)
    ]

    first = bucket_report(records)
    second = bucket_report(list(reversed(records)))

    assert first == second
    assert sum(item["trades"] for item in first["buckets"]["RSI"].values()) == 8
    assert all(item["small_sample_warning"] for item in first["buckets"]["RSI"].values())


def test_bootstrap_and_monte_carlo_are_seed_deterministic() -> None:
    base = _record()
    records = [
        replace(base, record_id=str(index), net_pnl=float((index % 3) - 1))
        for index in range(12)
    ]

    first_bootstrap = deterministic_bootstrap_expectancy(records, seed=7, repetitions=200)
    second_bootstrap = deterministic_bootstrap_expectancy(records, seed=7, repetitions=200)
    first_monte_carlo = deterministic_trade_order_monte_carlo(records, seed=9, repetitions=200)
    second_monte_carlo = deterministic_trade_order_monte_carlo(records, seed=9, repetitions=200)

    assert first_bootstrap == second_bootstrap
    assert first_monte_carlo == second_monte_carlo
    assert first_bootstrap["interval_95"] is not None
    assert 0.0 <= first_monte_carlo["probability_ending_below_50"] <= 1.0


def test_candidate_ranking_is_stable_across_input_order() -> None:
    base = _record()
    records = []
    for window_index, window in enumerate(("OOS_1", "OOS_2", "OOS_3")):
        for index in range(24):
            value = index / 10_000
            records.append(replace(
                base,
                record_id=f"{window}-{index}",
                window_id=window,
                atr_percent=value,
                ema_separation_percent=-value,
                ema50_slope_percent=-value / 10,
                net_pnl=value * 100 - 0.1 + window_index * 0.001,
            ))

    assert rank_candidate_features(records) == rank_candidate_features(list(reversed(records)))
    assert len(rank_candidate_features(records)) == 3


def test_candidate_classification_requires_every_window_for_stable_edge() -> None:
    candidate = {
        "preferred_side": "LOW",
        "window_performance": {
            "OOS_1": {"low_expectancy": 0.10, "low_n": 25},
            "OOS_2": {"low_expectancy": 0.05, "low_n": 24},
            "OOS_3": {"low_expectancy": -0.01, "low_n": 19},
        },
    }
    assert classify_candidates([candidate]) == "POSSIBLE_REGIME_EDGE"

    stable = {
        **candidate,
        "window_performance": {
            key: {"low_expectancy": 0.01, "low_n": 20}
            for key in ("OOS_1", "OOS_2", "OOS_3")
        },
    }
    assert classify_candidates([stable]) == "STABLE_REGIME_EDGE_FOUND"


def test_empty_and_small_sample_statistics_are_safe() -> None:
    empty = trade_statistics([])
    assert empty["trades"] == 0
    assert empty["expectancy"] is None
    assert empty["small_sample_warning"] is True
    assert deterministic_bootstrap_expectancy([], repetitions=10)["interval_95"] is None
    assert deterministic_trade_order_monte_carlo([], repetitions=10)["sample_size"] == 0
    assert window_sell_report([]) == {}
