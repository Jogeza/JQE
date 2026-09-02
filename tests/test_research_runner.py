from datetime import datetime, timedelta, timezone

import pytest

from backtesting.engine import BacktestEngine
from broker.types import Candle, Timeframe
from data.dataset import (
    build_dataset_manifest,
    candle_content_hash,
    export_dataset_bundle,
)
from research.experiments import (
    ResearchPartition,
    load_experiment_record,
)
from research.runner import run_training_experiment


def _candles(count: int = 400) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    return [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i * 0.1,
            high=2601.0 + i * 0.1,
            low=2599.0 + i * 0.1,
            close=2600.2 + i * 0.1,
            volume=None,
            source="research-runner-fixture",
        )
        for i in range(count)
    ]


def _bundle(tmp_path):
    candles = _candles()

    manifest = build_dataset_manifest(
        candles,
        provider="fixture",
        source="research runner fixture",
        provider_symbol="fixture-XAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(
            2026,
            1,
            10,
            tzinfo=timezone.utc,
        ),
    )

    bundle = tmp_path / "bundle"
    export_dataset_bundle(bundle, candles, manifest)

    return bundle, candles, manifest


@pytest.mark.asyncio
async def test_training_runner_passes_only_train_partition_to_backtest(
    tmp_path,
    monkeypatch,
) -> None:
    bundle, candles, _ = _bundle(tmp_path)
    captured = {}

    async def fake_run_backtest(**kwargs):
        captured.update(kwargs)
        return BacktestEngine(
            starting_balance=kwargs["starting_balance"]
        )

    monkeypatch.setattr(
        "research.runner.run_backtest",
        fake_run_backtest,
    )

    output = tmp_path / "experiment.json"

    result = await run_training_experiment(
        bundle_directory=bundle,
        experiment_path=output,
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
        created_at=datetime(
            2026,
            1,
            11,
            tzinfo=timezone.utc,
        ),
    )

    expected_train_count = int(len(candles) * 0.60)

    assert len(captured["dataset"]) == expected_train_count
    assert captured["dataset"] == result.split.train
    assert captured["candles"] == expected_train_count

    assert captured["dataset"][-1].time < result.split.validation[0].time
    assert (
        result.split.validation[-1].time
        < result.split.out_of_sample[0].time
    )

    assert "manifest" not in captured

    assert result.experiment.partition is ResearchPartition.TRAIN
    assert result.experiment.partition_candle_count == expected_train_count
    assert result.experiment.partition_hash == candle_content_hash(
        result.split.train
    )
    assert output.exists()


@pytest.mark.asyncio
async def test_training_runner_persists_verified_experiment(
    tmp_path,
    monkeypatch,
) -> None:
    bundle, _, manifest = _bundle(tmp_path)

    async def fake_run_backtest(**kwargs):
        return BacktestEngine(
            starting_balance=kwargs["starting_balance"]
        )

    monkeypatch.setattr(
        "research.runner.run_backtest",
        fake_run_backtest,
    )

    output = tmp_path / "experiment.json"

    result = await run_training_experiment(
        bundle_directory=bundle,
        experiment_path=output,
        strategy_name="TrendContinuation",
        strategy_config={
            "min_confidence": 70,
            "risk_percent": 1.0,
        },
        starting_balance=50.0,
        created_at=datetime(
            2026,
            1,
            11,
            tzinfo=timezone.utc,
        ),
    )

    loaded = load_experiment_record(output)

    assert loaded == result.experiment
    assert loaded.dataset_hash == manifest.content_hash
    assert loaded.partition is ResearchPartition.TRAIN
    assert loaded.starting_balance == 50.0
    assert loaded.metrics["Total Trades"] == 0


@pytest.mark.asyncio
async def test_training_runner_is_deterministic_for_same_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    bundle, _, _ = _bundle(tmp_path)

    async def fake_run_backtest(**kwargs):
        return BacktestEngine(
            starting_balance=kwargs["starting_balance"]
        )

    monkeypatch.setattr(
        "research.runner.run_backtest",
        fake_run_backtest,
    )

    created = datetime(
        2026,
        1,
        11,
        tzinfo=timezone.utc,
    )

    first = await run_training_experiment(
        bundle_directory=bundle,
        experiment_path=tmp_path / "first.json",
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
        created_at=created,
    )

    second = await run_training_experiment(
        bundle_directory=bundle,
        experiment_path=tmp_path / "second.json",
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
        created_at=created,
    )

    assert first.experiment == second.experiment
    assert (
        (tmp_path / "first.json").read_bytes()
        == (tmp_path / "second.json").read_bytes()
    )
