from datetime import datetime, timedelta, timezone

import pytest

from broker.types import Candle, Timeframe
from data.dataset import (
    build_dataset_manifest,
    canonical_dataset_hash,
    export_dataset_bundle,
)
from research.experiments import (
    ExperimentCatalog,
    ResearchPartition,
)
from research.runner import run_training_experiment


def test_training_runner_has_no_caller_selected_output_path() -> None:
    from inspect import signature

    parameters = signature(run_training_experiment).parameters
    assert "catalog" in parameters
    assert "experiment_path" not in parameters
    assert "output_path" not in parameters


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

    real_run_backtest = __import__("research.runner", fromlist=["run_backtest"]).run_backtest

    async def fake_run_backtest(**kwargs):
        captured.update(kwargs)
        return await real_run_backtest(**kwargs)

    monkeypatch.setattr(
        "research.runner.run_backtest",
        fake_run_backtest,
    )

    catalog = ExperimentCatalog(tmp_path / "catalog")

    result = await run_training_experiment(
        bundle_directory=bundle,
        catalog=catalog,
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
    assert result.experiment.dataset_hash == canonical_dataset_hash(
        result.split.train, symbol="XAUUSD", timeframe=Timeframe.M15
    )
    assert catalog.load(result.experiment.experiment_id) == result.experiment


@pytest.mark.asyncio
async def test_training_runner_persists_verified_experiment(
    tmp_path,
    monkeypatch,
) -> None:
    bundle, _, manifest = _bundle(tmp_path)

    catalog = ExperimentCatalog(tmp_path / "catalog")

    result = await run_training_experiment(
        bundle_directory=bundle,
        catalog=catalog,
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

    loaded = catalog.load(result.experiment.experiment_id)

    assert loaded == result.experiment
    assert [path.name for path in catalog.root.iterdir()] == [
        f"{result.experiment.experiment_id}.experiment.json"
    ]
    assert catalog.discover().experiments[0].experiment_id == result.experiment.experiment_id
    assert loaded.dataset_hash == result.engine.result.dataset_hash
    assert loaded.run_fingerprint == result.engine.result.run_fingerprint
    assert loaded.result_hash == result.engine.result.result_hash
    assert loaded.provenance["frozen_manifest_content_hash"] == manifest.content_hash
    assert loaded.partition is ResearchPartition.TRAIN
    assert loaded.configuration["initial_capital"] == 50.0
    assert loaded.metrics["Total Trades"] == result.engine.total_trades


@pytest.mark.asyncio
async def test_training_runner_is_deterministic_for_same_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    bundle, _, _ = _bundle(tmp_path)

    created = datetime(
        2026,
        1,
        11,
        tzinfo=timezone.utc,
    )

    first = await run_training_experiment(
        bundle_directory=bundle,
        catalog=ExperimentCatalog(tmp_path / "catalog"),
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
        created_at=created,
    )

    second = await run_training_experiment(
        bundle_directory=bundle,
        catalog=ExperimentCatalog(tmp_path / "catalog"),
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
        created_at=created,
    )

    assert first.experiment.experiment_id != second.experiment.experiment_id
    assert first.experiment.dataset_hash == second.experiment.dataset_hash
    assert first.experiment.run_fingerprint == second.experiment.run_fingerprint
    assert first.experiment.result_hash == second.experiment.result_hash


@pytest.mark.asyncio
async def test_training_experiment_dataset_mutation_changes_canonical_identity(tmp_path) -> None:
    first_bundle, candles, _ = _bundle(tmp_path / "first-source")
    changed = list(candles)
    changed[50] = changed[50].model_copy(update={"close": changed[50].close + 0.01})
    changed_manifest = build_dataset_manifest(
        changed, provider="fixture", source="research runner fixture",
        provider_symbol="fixture-XAUUSD", canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )
    second_bundle = tmp_path / "second-source" / "bundle"
    export_dataset_bundle(second_bundle, changed, changed_manifest)
    first = await run_training_experiment(
        bundle_directory=first_bundle, catalog=ExperimentCatalog(tmp_path / "dataset-catalog"),
        strategy_name="TrendContinuation", strategy_config={"version": 1},
    )
    second = await run_training_experiment(
        bundle_directory=second_bundle, catalog=ExperimentCatalog(tmp_path / "dataset-catalog"),
        strategy_name="TrendContinuation", strategy_config={"version": 1},
    )
    assert first.experiment.dataset_hash != second.experiment.dataset_hash
    assert first.experiment.run_fingerprint != second.experiment.run_fingerprint


@pytest.mark.asyncio
async def test_training_experiment_material_config_change_preserves_dataset_identity(tmp_path) -> None:
    bundle, _, _ = _bundle(tmp_path)
    first = await run_training_experiment(
        bundle_directory=bundle, catalog=ExperimentCatalog(tmp_path / "capital-catalog"),
        strategy_name="TrendContinuation", strategy_config={"version": 1},
        starting_balance=50.0,
    )
    second = await run_training_experiment(
        bundle_directory=bundle, catalog=ExperimentCatalog(tmp_path / "capital-catalog"),
        strategy_name="TrendContinuation", strategy_config={"version": 1},
        starting_balance=75.0,
    )
    assert first.experiment.dataset_hash == second.experiment.dataset_hash
    assert first.experiment.run_fingerprint != second.experiment.run_fingerprint
