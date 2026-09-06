import json
from datetime import datetime, timezone

import pytest

from core.exceptions import MarketDataError
from research.experiments import (
    ExperimentCatalog, ExperimentStatus, ResearchPartition, build_experiment_record,
    compare_experiments, load_experiment_record,
)

HASH_A, HASH_B, HASH_C = ("sha256:" + character * 64 for character in "abc")
FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)
LAST = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _record(**updates):
    values = dict(
        dataset_hash=HASH_A, run_fingerprint=HASH_B, result_hash=HASH_C,
        engine_version="jqe-backtest-v1", identity_schema_version=1,
        symbol="XAUUSD", timeframe="M15", partition=ResearchPartition.TRAIN,
        partition_first_candle=FIRST, partition_last_candle=LAST,
        partition_candle_count=97, strategy_name="TrendContinuation",
        configuration={"strategy": {"minimum_confidence": 70},
                       "risk": {"risk_percent": 1.0},
                       "execution": {"spread": 0.0}, "initial_capital": 50.0},
        metrics={"Total Trades": 4, "Net P&L": 3.5},
        created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    values.update(updates)
    return build_experiment_record(**values)


def test_two_records_have_distinct_ids_but_shared_scientific_identity() -> None:
    first, second = _record(), _record(created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert first.experiment_id != second.experiment_id
    assert first.created_at != second.created_at
    assert first.dataset_hash == second.dataset_hash
    assert first.run_fingerprint == second.run_fingerprint
    assert first.result_hash == second.result_hash
    assert compare_experiments(first, second) == {
        "both_fully_reproducible": True, "same_dataset": True,
        "same_run_configuration": True, "same_result": True,
    }


def test_configuration_and_metrics_are_recursively_immutable() -> None:
    record = _record()
    with pytest.raises(TypeError):
        record.configuration["strategy"]["minimum_confidence"] = 99
    with pytest.raises(TypeError):
        record.metrics["Total Trades"] = 999


def test_json_round_trip_preserves_record_and_identities(tmp_path) -> None:
    record, catalog = _record(), ExperimentCatalog(tmp_path)
    catalog.save(record)
    loaded = catalog.load(record.experiment_id)
    assert loaded == record
    assert loaded.fully_reproducible


def test_json_serialization_of_same_record_is_stable(tmp_path) -> None:
    record = _record()
    first_catalog, second_catalog = ExperimentCatalog(tmp_path / "first"), ExperimentCatalog(tmp_path / "second")
    first_catalog.save(record)
    second_catalog.save(record)
    first = first_catalog.root / f"{record.experiment_id}.experiment.json"
    second = second_catalog.root / f"{record.experiment_id}.experiment.json"
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("field", ["dataset_hash", "run_fingerprint", "result_hash"])
def test_invalid_deterministic_hash_is_rejected(field) -> None:
    with pytest.raises(MarketDataError):
        _record(**{field: "sha256:bad"})


def test_comparison_distinguishes_dataset_and_configuration() -> None:
    baseline = _record()
    other_dataset = _record(dataset_hash=HASH_B, run_fingerprint=HASH_C)
    other_config = _record(run_fingerprint=HASH_C)
    assert not compare_experiments(baseline, other_dataset)["same_dataset"]
    assert not compare_experiments(baseline, other_dataset)["same_run_configuration"]
    assert compare_experiments(baseline, other_config)["same_dataset"]
    assert not compare_experiments(baseline, other_config)["same_run_configuration"]


def test_schema_one_record_loads_as_explicitly_incomplete_legacy(tmp_path) -> None:
    payload = {
        "schema_version": 1, "experiment_id": HASH_A,
        "created_at": FIRST.isoformat(), "dataset_hash": HASH_A,
        "partition_hash": HASH_B, "symbol": "XAUUSD", "timeframe": "M15",
        "partition": "TRAIN", "partition_first_candle": FIRST.isoformat(),
        "partition_last_candle": LAST.isoformat(), "partition_candle_count": 97,
        "strategy_name": "legacy", "strategy_config": {"x": 1},
        "starting_balance": 50.0, "metrics": {},
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    record = load_experiment_record(path)
    assert record.status is ExperimentStatus.LEGACY_INCOMPLETE
    assert not record.fully_reproducible
    assert record.dataset_hash is record.run_fingerprint is record.result_hash is None
    assert record.provenance["legacy_dataset_hash"] == HASH_A


def test_unknown_future_schema_is_rejected(tmp_path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    with pytest.raises(MarketDataError):
        load_experiment_record(path)


def test_legacy_record_cannot_be_resaved_as_complete_schema(tmp_path) -> None:
    payload = {
        "schema_version": 1, "experiment_id": HASH_A, "created_at": FIRST.isoformat(),
        "dataset_hash": HASH_A, "partition_hash": HASH_B, "symbol": "XAUUSD",
        "timeframe": "M15", "partition": "TRAIN",
        "partition_first_candle": FIRST.isoformat(), "partition_last_candle": LAST.isoformat(),
        "partition_candle_count": 97, "strategy_name": "legacy",
        "strategy_config": {}, "starting_balance": 50.0, "metrics": {},
    }
    source, target = tmp_path / "legacy.json", tmp_path / "catalog"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MarketDataError, match="Only complete schema-v2"):
        ExperimentCatalog(target).save(load_experiment_record(source))
    assert not target.exists()


def test_loader_rejects_malformed_persisted_canonical_hash(tmp_path) -> None:
    record, catalog = _record(), ExperimentCatalog(tmp_path)
    catalog.save(record)
    path = tmp_path / f"{record.experiment_id}.experiment.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["result_hash"] = "sha256:bad"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MarketDataError):
        load_experiment_record(path)
