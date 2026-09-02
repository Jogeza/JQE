import json
from datetime import datetime, timezone

import pytest

from core.exceptions import MarketDataError
from research.experiments import (
    ResearchPartition,
    build_experiment_record,
    experiment_identity,
    load_experiment_record,
    save_experiment_record,
)


DATASET_HASH = "sha256:" + "a" * 64
PARTITION_HASH = "sha256:" + "b" * 64
FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)
LAST = datetime(2026, 1, 2, tzinfo=timezone.utc)
CREATED = datetime(2026, 1, 3, tzinfo=timezone.utc)


def _record():
    return build_experiment_record(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={
            "min_confidence": 70,
            "risk_percent": 1.0,
        },
        starting_balance=50.0,
        metrics={
            "Total Trades": 4,
            "Net P&L": 3.5,
        },
        created_at=CREATED,
    )


def test_experiment_identity_is_deterministic() -> None:
    first = _record()
    second = _record()

    assert first.experiment_id == second.experiment_id


def test_metrics_do_not_change_experiment_identity() -> None:
    first = _record()

    second = build_experiment_record(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={
            "min_confidence": 70,
            "risk_percent": 1.0,
        },
        starting_balance=50.0,
        metrics={"Total Trades": 999},
        created_at=CREATED,
    )

    assert first.experiment_id == second.experiment_id


def test_strategy_config_changes_experiment_identity() -> None:
    first = _record()

    changed = build_experiment_record(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={
            "min_confidence": 75,
            "risk_percent": 1.0,
        },
        starting_balance=50.0,
        metrics={},
        created_at=CREATED,
    )

    assert first.experiment_id != changed.experiment_id


def test_partition_changes_experiment_identity() -> None:
    train = _record()

    validation = build_experiment_record(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.VALIDATION,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={
            "min_confidence": 70,
            "risk_percent": 1.0,
        },
        starting_balance=50.0,
        metrics={},
        created_at=CREATED,
    )

    assert train.experiment_id != validation.experiment_id


def test_experiment_json_round_trip(tmp_path) -> None:
    record = _record()
    path = tmp_path / "experiment.json"

    save_experiment_record(path, record)
    loaded = load_experiment_record(path)

    assert loaded == record


def test_experiment_json_is_stable(tmp_path) -> None:
    record = _record()

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    save_experiment_record(first, record)
    save_experiment_record(second, record)

    assert first.read_bytes() == second.read_bytes()


def test_loader_rejects_tampered_identity(tmp_path) -> None:
    record = _record()
    path = tmp_path / "experiment.json"

    save_experiment_record(path, record)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["strategy_config"]["min_confidence"] = 99
    path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(MarketDataError):
        load_experiment_record(path)


@pytest.mark.parametrize(
    "dataset_hash",
    [
        "",
        "sha256:abc",
        "sha1:" + "a" * 40,
        "sha256:" + "A" * 64,
    ],
)
def test_invalid_dataset_hash_is_rejected(dataset_hash: str) -> None:
    with pytest.raises(MarketDataError):
        build_experiment_record(
            dataset_hash=dataset_hash,
            partition_hash=PARTITION_HASH,
            symbol="XAUUSD",
            timeframe="M15",
            partition=ResearchPartition.TRAIN,
            partition_first_candle=FIRST,
            partition_last_candle=LAST,
            partition_candle_count=97,
            strategy_name="TrendContinuation",
            strategy_config={},
            starting_balance=50.0,
            metrics={},
        )


def test_experiment_identity_ignores_mapping_key_order() -> None:
    first = experiment_identity(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={"a": 1, "b": 2},
        starting_balance=50.0,
    )

    second = experiment_identity(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={"b": 2, "a": 1},
        starting_balance=50.0,
    )

    assert first == second


def test_partition_hash_changes_experiment_identity() -> None:
    first = experiment_identity(
        dataset_hash=DATASET_HASH,
        partition_hash=PARTITION_HASH,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
    )

    second = experiment_identity(
        dataset_hash=DATASET_HASH,
        partition_hash="sha256:" + "c" * 64,
        symbol="XAUUSD",
        timeframe="M15",
        partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST,
        partition_last_candle=LAST,
        partition_candle_count=97,
        strategy_name="TrendContinuation",
        strategy_config={"min_confidence": 70},
        starting_balance=50.0,
    )

    assert first != second


def test_loader_rejects_tampered_partition_hash(tmp_path) -> None:
    record = _record()
    path = tmp_path / "experiment.json"

    save_experiment_record(path, record)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["partition_hash"] = "sha256:" + "c" * 64

    path.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(MarketDataError):
        load_experiment_record(path)
