import json
from datetime import datetime, timedelta, timezone

import pytest

from research.experiments import (
    ComparisonClassification, ExperimentCatalog, ExperimentConflictError, ExperimentNotFoundError,
    ExperimentStatus, ResearchPartition, build_experiment_record,
    compare_experiment_records,
)

H1, H2, H3 = ("sha256:" + char * 64 for char in "abc")
START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def record(*, record_id: str, created_offset: int = 0, symbol: str = "XAUUSD",
           timeframe: str = "M15", dataset_hash: str = H1,
           run_fingerprint: str = H2, result_hash: str = H3,
           capital: float = 50.0):
    return build_experiment_record(
        experiment_id=record_id, created_at=START + timedelta(hours=created_offset),
        dataset_hash=dataset_hash, run_fingerprint=run_fingerprint,
        result_hash=result_hash, engine_version="jqe-backtest-v1",
        identity_schema_version=1, symbol=symbol, timeframe=timeframe,
        partition=ResearchPartition.TRAIN, partition_first_candle=START,
        partition_last_candle=START + timedelta(days=1), partition_candle_count=97,
        strategy_name="canonical", configuration={
            "strategy": {"version": 1}, "risk": {"risk_percent": 1.0},
            "execution": {"spread": 0.0}, "initial_capital": capital,
        }, metrics={"Starting Balance": capital, "Ending Balance": capital + 2,
                    "Total Trades": 3, "Win Rate %": 50.0,
                    "Maximum Drawdown": 1.0, "Profit Factor": None},
    )


def legacy_payload(record_id: str) -> dict:
    return {
        "schema_version": 1, "experiment_id": record_id, "created_at": START.isoformat(),
        "dataset_hash": H1, "partition_hash": H2, "symbol": "XAUUSD",
        "timeframe": "M15", "partition": "TRAIN",
        "partition_first_candle": START.isoformat(),
        "partition_last_candle": (START + timedelta(days=1)).isoformat(),
        "partition_candle_count": 97, "strategy_name": "legacy",
        "strategy_config": {}, "starting_balance": 50.0, "metrics": {},
    }


def test_discovery_is_ordered_bounded_and_keeps_duplicate_runs(tmp_path) -> None:
    catalog = ExperimentCatalog(tmp_path)
    for item in (record(record_id="b", created_offset=1),
                 record(record_id="a", created_offset=1),
                 record(record_id="old", created_offset=0)):
        catalog.save(item)
    page = catalog.discover(limit=2)
    assert page.total == 3
    assert [item.experiment_id for item in page.experiments] == ["a", "b"]
    assert page.experiments[0].run_fingerprint == page.experiments[1].run_fingerprint
    assert [item.experiment_id for item in catalog.discover(limit=2, offset=1).experiments] == ["b", "old"]


def test_catalog_save_is_idempotent_but_rejects_conflicting_duplicate_id(tmp_path) -> None:
    catalog = ExperimentCatalog(tmp_path)
    original = record(record_id="fixed")
    catalog.save(original)
    target = tmp_path / "fixed.experiment.json"
    before = target.read_bytes()
    catalog.save(original)
    assert target.read_bytes() == before
    conflicting = record(record_id="fixed", capital=75.0)
    with pytest.raises(ExperimentConflictError):
        catalog.save(conflicting)
    assert target.read_bytes() == before
    assert [path.name for path in tmp_path.iterdir()] == ["fixed.experiment.json"]


def test_catalog_save_rejects_unsafe_ids_and_symlink_surfaces(tmp_path, monkeypatch) -> None:
    from pathlib import Path
    from core.exceptions import MarketDataError

    with pytest.raises(MarketDataError):
        ExperimentCatalog(tmp_path).save(record(record_id="../escape"))
    root = tmp_path / "linked-root"
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == root)
    with pytest.raises(MarketDataError, match="root cannot be a symlink"):
        ExperimentCatalog(root).save(record(record_id="safe"))
    assert not root.exists()


def test_catalog_save_rejects_symlink_target_without_overwrite(tmp_path, monkeypatch) -> None:
    from pathlib import Path
    from core.exceptions import MarketDataError

    target = tmp_path / "safe.experiment.json"
    target.write_text("outside sentinel", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == target or original(self))
    with pytest.raises(MarketDataError, match="target cannot be a symlink"):
        ExperimentCatalog(tmp_path).save(record(record_id="safe"))
    assert target.read_text(encoding="utf-8") == "outside sentinel"


def test_exact_filters_cover_symbol_timeframe_dataset_run_and_status(tmp_path) -> None:
    catalog = ExperimentCatalog(tmp_path)
    catalog.save(record(record_id="match"))
    catalog.save(record(record_id="other", symbol="EURUSD", timeframe="H1",
                        dataset_hash=H2, run_fingerprint=H3))
    filters = dict(symbol="XAUUSD", timeframe="M15", dataset_hash=H1,
                   run_fingerprint=H2, status=ExperimentStatus.COMPLETED,
                   fully_reproducible=True)
    assert [item.experiment_id for item in catalog.discover(**filters).experiments] == ["match"]


def test_legacy_and_malformed_records_do_not_destroy_catalog(tmp_path) -> None:
    catalog = ExperimentCatalog(tmp_path)
    catalog.save(record(record_id="valid"))
    (tmp_path / "legacy.experiment.json").write_text(json.dumps(legacy_payload("legacy")), encoding="utf-8")
    (tmp_path / "broken.experiment.json").write_text("{", encoding="utf-8")
    (tmp_path / "unrelated.json").write_text("{}", encoding="utf-8")
    result = catalog.discover()
    assert {item.experiment_id for item in result.experiments} == {"valid", "legacy"}
    legacy = next(item for item in result.experiments if item.experiment_id == "legacy")
    assert legacy.status is ExperimentStatus.LEGACY_INCOMPLETE
    assert not legacy.fully_reproducible and legacy.dataset_hash is None
    assert result.issues[0].file_name == "broken.experiment.json"
    assert result.issues[0].code == "INVALID_EXPERIMENT_RECORD"


def test_exact_loading_rejects_unknown_and_path_traversal(tmp_path) -> None:
    catalog = ExperimentCatalog(tmp_path)
    catalog.save(record(record_id="exact"))
    assert catalog.load("exact").experiment_id == "exact"
    for value in ("missing", "../exact", "..\\exact", "C:\\exact", "%2e%2e"):
        with pytest.raises(ExperimentNotFoundError):
            catalog.load(value)


def test_named_malformed_record_fails_explicitly(tmp_path) -> None:
    (tmp_path / "bad.experiment.json").write_text("{", encoding="utf-8")
    with pytest.raises(Exception, match="invalid"):
        ExperimentCatalog(tmp_path).load("bad")


def test_comparison_classifies_identical_config_and_dataset_boundaries() -> None:
    baseline = record(record_id="base")
    identical = record(record_id="repeat")
    same_dataset = record(record_id="config", run_fingerprint=H3, result_hash=H2, capital=75)
    different_dataset = record(record_id="dataset", dataset_hash=H2, run_fingerprint=H3,
                               result_hash=H2)
    identical_comparison = compare_experiment_records(baseline, identical)
    assert identical_comparison.classification is ComparisonClassification.IDENTICAL_RESULT
    assert identical_comparison.metric_deltas["profit_factor"] is None
    comparison = compare_experiment_records(baseline, same_dataset)
    assert comparison.classification is ComparisonClassification.SAME_DATASET_DIFFERENT_CONFIGURATION
    assert comparison.controlled_comparison and comparison.metric_deltas["ending_capital"] == 25
    comparison = compare_experiment_records(baseline, different_dataset)
    assert comparison.classification is ComparisonClassification.DIFFERENT_DATASET
    assert not comparison.controlled_comparison


def test_legacy_comparison_is_never_controlled(tmp_path) -> None:
    path = tmp_path / "legacy.experiment.json"
    path.write_text(json.dumps(legacy_payload("legacy")), encoding="utf-8")
    comparison = compare_experiment_records(
        ExperimentCatalog(tmp_path).load("legacy"), record(record_id="complete")
    )
    assert comparison.classification is ComparisonClassification.LEGACY_OR_INCOMPLETE
    assert not comparison.controlled_comparison


@pytest.mark.parametrize("limit,offset", [(0, 0), (201, 0), (1, -1)])
def test_discovery_bounds_fail_closed(tmp_path, limit, offset) -> None:
    with pytest.raises(ValueError):
        ExperimentCatalog(tmp_path).discover(limit=limit, offset=offset)


def test_read_only_research_api_lists_loads_and_compares_catalog_records(tmp_path, monkeypatch) -> None:
    from api import research

    catalog = ExperimentCatalog(tmp_path)
    catalog.save(record(record_id="left"))
    catalog.save(record(record_id="right"))
    monkeypatch.setattr(research, "_experiment_catalog", catalog)
    listing = research.list_persisted_experiments(
        symbol=None, timeframe=None, status=None, fully_reproducible=None,
        dataset_hash=None, run_fingerprint=None, limit=50, offset=0,
    )
    assert [item["experiment_id"] for item in listing["experiments"]] == ["left", "right"]
    assert research.get_persisted_experiment("left")["experiment_id"] == "left"
    comparison = research.compare_persisted_experiments("left", "right")
    assert comparison["classification"] == "IDENTICAL_RESULT"
    assert comparison["controlled_comparison"]


def test_api_hash_validation_unknown_hash_enums_and_legacy_nulls(tmp_path, monkeypatch) -> None:
    from fastapi import HTTPException
    from api import research

    catalog = ExperimentCatalog(tmp_path)
    catalog.save(record(record_id="complete"))
    (tmp_path / "legacy.experiment.json").write_text(
        json.dumps(legacy_payload("legacy")), encoding="utf-8"
    )
    monkeypatch.setattr(research, "_experiment_catalog", catalog)
    with pytest.raises(HTTPException) as malformed:
        research.list_persisted_experiments(
            symbol=None, timeframe=None, status=None, fully_reproducible=None,
            dataset_hash="sha256:bad", run_fingerprint=None, limit=50, offset=0,
        )
    assert malformed.value.status_code == 422
    unknown = research.list_persisted_experiments(
        symbol=None, timeframe=None, status=None, fully_reproducible=None,
        dataset_hash="sha256:" + "f" * 64, run_fingerprint=None, limit=50, offset=0,
    )
    assert unknown["total"] == 0 and unknown["experiments"] == []
    listing = research.ExperimentListDTO.model_validate(
        research.list_persisted_experiments(
            symbol=None, timeframe=None, status=None, fully_reproducible=None,
            dataset_hash=None, run_fingerprint=None, limit=50, offset=0,
        )
    ).model_dump(mode="json")
    legacy = next(item for item in listing["experiments"] if item["experiment_id"] == "legacy")
    assert legacy["status"] == "LEGACY_INCOMPLETE"
    for field in (
        "dataset_hash", "run_fingerprint", "result_hash", "engine_version",
        "identity_schema_version", "ending_capital", "total_return", "total_trades",
    ):
        assert legacy[field] is None


def test_read_only_catalog_api_has_no_execution_or_filesystem_side_effects(tmp_path, monkeypatch) -> None:
    from unittest.mock import Mock
    from fastapi import HTTPException
    from api import research

    root = tmp_path / "missing-catalog"
    backtest = Mock(side_effect=AssertionError("backtest must not run"))
    gateway = Mock(side_effect=AssertionError("broker must not be constructed"))
    monkeypatch.setattr(research, "_experiment_catalog", ExperimentCatalog(root))
    monkeypatch.setattr(research, "run_backtest", backtest)
    monkeypatch.setattr("broker.factory.get_gateway", gateway)
    listing = research.list_persisted_experiments(
        symbol=None, timeframe=None, status=None, fully_reproducible=None,
        dataset_hash=None, run_fingerprint=None, limit=50, offset=0,
    )
    assert listing == {"experiments": [], "issues": [], "total": 0, "limit": 50, "offset": 0}
    with pytest.raises(HTTPException) as missing:
        research.get_persisted_experiment("unknown")
    assert missing.value.status_code == 404
    assert not root.exists()
    backtest.assert_not_called()
    gateway.assert_not_called()
