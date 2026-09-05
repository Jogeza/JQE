from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backtesting.backtest import run_backtest
from backtesting.models import BacktestExitReason, BacktestTrade
from broker.types import Candle, ExecutionQuantity, ExecutionQuantityUnit, Timeframe
from data.dataset import candle_content_hash
from data.provenance import VolumeType
from research.frvp_experiments import (
    ExperimentRequest, ExperimentStatus, HypothesisId, MAX_PARAMETER_CANDIDATES,
    MAX_PROFILE_CALCULATIONS,
    ValueAreaLocation, run_frvp_experiment,
)


def candles(count=240):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(time=start+timedelta(minutes=15*i), open=100+i*.02, high=101+i*.02,
        low=99+i*.02, close=100.5+i*.02, volume=10, source="synthetic") for i in range(count)]


async def baseline_for(items):
    engine = await run_backtest(dataset=items, provider="synthetic", timeframe=Timeframe.M15)
    indexes = (70, 90, 150, 170, 200, 220)
    trades = []
    for trade_id, index in enumerate(indexes, 1):
        pnl = 2.0 if trade_id % 2 else -1.0
        trades.append(BacktestTrade(trade_id, "XAUUSD", Timeframe.M15, "BUY", items[index].time,
            items[index+1].time, items[index+1].open, items[index+2].time, items[index+2].close,
            items[index+1].open-1, items[index+1].open+2,
            ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS), pnl, 0, pnl,
            100, 100+pnl, 2, BacktestExitReason.TAKE_PROFIT if pnl > 0 else BacktestExitReason.STOP_LOSS))
    indicators = tuple(replace(obs, atr=1.0) for obs in engine.result.indicators)
    return replace(engine.result, trades=tuple(trades), indicators=indicators,
                   total_trades=len(trades))


def request(hypothesis=HypothesisId.POC_PROXIMITY_FILTER_V1, **kwargs):
    return ExperimentRequest(hypothesis, kwargs.pop("profile_lookback", 20), Decimal("0.5"),
        kwargs.pop("threshold_candidates", (Decimal("0.25"), Decimal("0.5"))),
        minimum_trade_count=kwargs.pop("minimum_trade_count", 1), **kwargs)


@pytest.mark.asyncio
async def test_deterministic_rolling_experiment_split_selection_and_metrics():
    data = candles(); baseline = await baseline_for(data); identity = candle_content_hash(data)
    first = run_frvp_experiment(data, baseline, dataset_identity=identity,
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="deterministic fixture", request=request())
    second = run_frvp_experiment(data, baseline, dataset_identity=identity,
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="deterministic fixture", request=request())
    assert first == second
    assert first.split_boundaries == (144, 192)
    assert first.selected_threshold in (Decimal("0.25"), Decimal("0.5"))
    assert len(first.training_candidates) == len(first.validation_candidates) == 2
    assert first.train and first.validation and first.out_of_sample
    assert first.out_of_sample.deltas.trade_count_delta <= 0
    assert all(feature.profile_end_index == feature.candle_index for feature in first.features)
    assert all(feature.profile_start_index == feature.candle_index-19 for feature in first.features)
    assert first.frvp_algorithm_version == "frvp-contract-v1"


@pytest.mark.asyncio
async def test_future_candles_cannot_change_earlier_feature():
    data = candles(); baseline = await baseline_for(data); identity = candle_content_hash(data)
    original = run_frvp_experiment(data, baseline, dataset_identity=identity,
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="fixture", request=request())
    changed = list(data)
    for index in range(171, len(changed)):
        changed[index] = changed[index].model_copy(update={"high": changed[index].high+100, "volume": 1000})
    mutated = run_frvp_experiment(changed, baseline, dataset_identity=candle_content_hash(changed),
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="fixture", request=request())
    assert [f for f in original.features if f.candle_index <= 170] == [f for f in mutated.features if f.candle_index <= 170]


@pytest.mark.asyncio
async def test_value_area_location_classification_groups_baseline_trades():
    data = candles(); baseline = await baseline_for(data)
    result = run_frvp_experiment(data, baseline, dataset_identity=candle_content_hash(data),
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="fixture",
        request=request(HypothesisId.VALUE_AREA_LOCATION_V1))
    assert {group.location for group in result.location_groups} == set(ValueAreaLocation)
    assert sum(group.metrics.trade_count for group in result.location_groups) == len(result.features)


@pytest.mark.asyncio
async def test_ineligible_volume_and_insufficient_data_fail_closed():
    data = candles(); baseline = await baseline_for(data); identity = candle_content_hash(data)
    unavailable = run_frvp_experiment(data, baseline, dataset_identity=identity,
        volume_type=VolumeType.UNAVAILABLE, volume_source="Deriv public", request=request())
    assert unavailable.status is ExperimentStatus.FRVP_EXPERIMENT_UNAVAILABLE
    assert unavailable.features == ()
    short = data[:60]
    insufficient = run_frvp_experiment(short, baseline, dataset_identity=candle_content_hash(short),
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="fixture", request=request())
    assert insufficient.status is ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT


@pytest.mark.asyncio
async def test_resource_and_sample_guards():
    data = candles(); baseline = await baseline_for(data)
    excessive = tuple(Decimal(i)/10 for i in range(MAX_PARAMETER_CANDIDATES+1))
    result = run_frvp_experiment(data, baseline, dataset_identity=candle_content_hash(data),
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="fixture",
        request=request(threshold_candidates=excessive))
    assert result.status is ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT
    repeated = tuple(replace(baseline.trades[i % len(baseline.trades)], trade_id=i+1)
                     for i in range(MAX_PROFILE_CALCULATIONS+1))
    oversized = run_frvp_experiment(data, replace(baseline, trades=repeated),
        dataset_identity=candle_content_hash(data), volume_type=VolumeType.SIMULATED_VOLUME,
        volume_source="fixture", request=request())
    assert oversized.status is ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT
    assert "calculation limit" in oversized.reason
    sparse = run_frvp_experiment(data, baseline, dataset_identity=candle_content_hash(data),
        volume_type=VolumeType.SIMULATED_VOLUME, volume_source="fixture",
        request=request(minimum_trade_count=30))
    assert sparse.status is ExperimentStatus.INSUFFICIENT_SAMPLE
