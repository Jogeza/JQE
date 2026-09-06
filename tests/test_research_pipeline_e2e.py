"""Offline end-to-end research pipeline verification."""

from datetime import datetime, timedelta, timezone

import pytest

from core.exceptions import MarketDataError
from broker.types import Candle, Timeframe
from data.dataset import (
    build_dataset_manifest,
    candle_content_hash,
    export_dataset_bundle,
    load_dataset_bundle,
)
from research.experiments import (
    ExperimentCatalog,
    ResearchPartition,
)
from research.runner import run_training_experiment


def _public_fixture(count: int = 400) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    return [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i * 0.10,
            high=2601.0 + i * 0.10,
            low=2599.0 + i * 0.10,
            close=2600.20 + i * 0.10,
            volume=None,
            source="deriv",
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_frozen_public_data_to_train_experiment(
    tmp_path,
    monkeypatch,
) -> None:
    candles = _public_fixture()

    manifest = build_dataset_manifest(
        candles,
        provider="deriv",
        source="deriv-public-market-data",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(
            2026,
            1,
            10,
            tzinfo=timezone.utc,
        ),
    )

    bundle = tmp_path / "XAUUSD_M15_frozen"
    export_dataset_bundle(bundle, candles, manifest)

    loaded_candles, loaded_manifest = load_dataset_bundle(bundle)

    assert loaded_candles == candles
    assert loaded_manifest == manifest
    assert loaded_manifest.content_hash == candle_content_hash(candles)

    captured = {}

    from research.runner import run_backtest as real_run_backtest

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
        strategy_config={"research_fixture": True},
        starting_balance=50.0,
        created_at=datetime(
            2026,
            1,
            11,
            tzinfo=timezone.utc,
        ),
    )

    train = result.split.train

    assert len(train) == 240
    assert len(result.split.validation) == 80
    assert len(result.split.out_of_sample) == 80

    assert captured["dataset"] == train
    assert captured["symbol"] == "XAUUSD"
    assert captured["timeframe"] is Timeframe.M15

    assert train[-1].time < result.split.validation[0].time
    assert (
        result.split.validation[-1].time
        < result.split.out_of_sample[0].time
    )

    record = catalog.load(result.experiment.experiment_id)

    assert record.partition is ResearchPartition.TRAIN
    assert record.dataset_hash == result.engine.result.dataset_hash
    assert record.run_fingerprint == result.engine.result.run_fingerprint
    assert record.result_hash == result.engine.result.result_hash
    assert record.provenance["frozen_manifest_content_hash"] == manifest.content_hash
    assert record.partition_candle_count == 240
    assert record.symbol == "XAUUSD"
    assert record.timeframe == "M15"


@pytest.mark.asyncio
async def test_pipeline_rejects_tampered_frozen_dataset(
    tmp_path,
) -> None:
    candles = _public_fixture()

    manifest = build_dataset_manifest(
        candles,
        provider="deriv",
        source="deriv-public-market-data",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(
            2026,
            1,
            10,
            tzinfo=timezone.utc,
        ),
    )

    bundle = tmp_path / "tampered"
    export_dataset_bundle(bundle, candles, manifest)

    csv_path = bundle / "candles.csv"
    text = csv_path.read_text(encoding="utf-8")
    text = text.replace("2600.2", "9999.2", 1)
    csv_path.write_text(text, encoding="utf-8")

    catalog = ExperimentCatalog(tmp_path / "catalog")

    with pytest.raises(MarketDataError):
        await run_training_experiment(
            bundle_directory=bundle,
            catalog=catalog,
            strategy_name="TrendContinuation",
            strategy_config={"research_fixture": True},
            starting_balance=50.0,
            created_at=datetime(
                2026,
                1,
                11,
                tzinfo=timezone.utc,
            ),
        )

    assert not catalog.root.exists()
