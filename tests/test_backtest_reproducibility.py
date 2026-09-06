"""Scientific reproducibility guarantees for the canonical backtest path."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import pandas as pd

from backtesting.backtest import run_backtest
from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExecutionAssumptions, BacktestExitReason
from broker.types import Candle, Timeframe
from data.dataset import canonical_dataset_hash


def _candles(count: int = 230) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Candle(
            time=start + timedelta(minutes=15 * index),
            open=100.0 + index * 0.1,
            high=102.0 + index * 0.1,
            low=99.0 + index * 0.1,
            close=101.0 + index * 0.1,
            volume=index,
            source="fixture-a",
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_identical_inputs_produce_identical_complete_results() -> None:
    candles = _candles()
    first = await run_backtest(dataset=candles, provider="fixture-a", timeframe=Timeframe.M15)
    second = await run_backtest(dataset=list(candles), provider="fixture-a", timeframe=Timeframe.M15)

    assert first.result is not second.result
    assert first.result.dataset_hash == second.result.dataset_hash
    assert first.result.run_fingerprint == second.result.run_fingerprint
    assert first.result.result_hash == second.result.result_hash
    assert first.result.decisions == second.result.decisions
    assert first.result.trades == second.result.trades
    assert first.equity_curve == second.equity_curve
    assert first.result.to_json_bytes() == second.result.to_json_bytes()


def test_dataset_identity_changes_for_one_ohlc_mutation() -> None:
    original = _candles()
    changed = list(original)
    candle = changed[50]
    changed[50] = candle.model_copy(update={"close": candle.close + 0.01})

    assert canonical_dataset_hash(
        original, symbol="XAUUSD", timeframe=Timeframe.M15
    ) != canonical_dataset_hash(
        changed, symbol="XAUUSD", timeframe=Timeframe.M15
    )


def test_dataset_identity_is_independent_of_provider_provenance() -> None:
    original = _candles()
    renamed_source = [
        candle.model_copy(update={"source": "fixture-b"}) for candle in original
    ]
    assert canonical_dataset_hash(
        original, symbol="XAUUSD", timeframe=Timeframe.M15
    ) == canonical_dataset_hash(
        renamed_source, symbol="XAUUSD", timeframe=Timeframe.M15
    )


@pytest.mark.asyncio
async def test_material_execution_configuration_changes_run_identity() -> None:
    candles = _candles()
    first = await run_backtest(dataset=candles, provider="fixture", timeframe=Timeframe.M15)
    second = await run_backtest(
        dataset=candles,
        provider="fixture",
        timeframe=Timeframe.M15,
        execution_assumptions=replace(
            BacktestExecutionAssumptions(), max_holding_candles=18
        ),
    )

    assert first.result.dataset_hash == second.result.dataset_hash
    assert first.result.run_fingerprint != second.result.run_fingerprint


@pytest.mark.asyncio
async def test_future_candle_mutation_cannot_change_decisions_through_cutoff() -> None:
    cutoff = 210
    original = _candles()
    changed = list(original)
    for index in range(cutoff + 1, len(changed)):
        candle = changed[index]
        changed[index] = candle.model_copy(
            update={
                "open": candle.open * 4,
                "high": candle.high * 5,
                "low": candle.low * 0.5,
                "close": candle.close * 3,
            }
        )

    first = await run_backtest(dataset=original, provider="fixture", timeframe=Timeframe.M15)
    second = await run_backtest(dataset=changed, provider="fixture", timeframe=Timeframe.M15)

    first_prefix = tuple(item for item in first.result.decisions if item.candle_index <= cutoff)
    second_prefix = tuple(item for item in second.result.decisions if item.candle_index <= cutoff)
    assert first_prefix == second_prefix
    assert first.result.indicators[: cutoff + 1] == second.result.indicators[: cutoff + 1]


def test_same_candle_stop_and_target_collision_is_stop_first() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    frame = pd.DataFrame({
        "time": [start, start + timedelta(minutes=15)],
        "open": [100.0, 100.0], "high": [100.0, 104.0],
        "low": [100.0, 98.0], "close": [100.0, 101.0],
        "ATR": [1.0, 1.0], "spread": [0.0, 0.0],
    })
    engine = BacktestEngine(starting_balance=1000.0, timeframe=Timeframe.M15)
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)
    engine.process_candle(1, frame)

    assert engine.trades[0].exit_reason is BacktestExitReason.STOP_LOSS
