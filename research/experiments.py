"""Immutable persisted research records bound to canonical backtest identity."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4
import re

from core.exceptions import MarketDataError

SCHEMA_VERSION = 2


class ResearchPartition(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    OOS = "OOS"


class ExperimentStatus(str, Enum):
    COMPLETED = "COMPLETED"
    LEGACY_INCOMPLETE = "LEGACY_INCOMPLETE"


class ComparisonClassification(str, Enum):
    IDENTICAL_RESULT = "IDENTICAL_RESULT"
    SAME_RUN_CONFIGURATION_DIFFERENT_OBSERVATION = "SAME_RUN_CONFIGURATION_DIFFERENT_OBSERVATION"
    SAME_DATASET_DIFFERENT_CONFIGURATION = "SAME_DATASET_DIFFERENT_CONFIGURATION"
    DIFFERENT_DATASET = "DIFFERENT_DATASET"
    LEGACY_OR_INCOMPLETE = "LEGACY_OR_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    schema_version: int
    experiment_id: str
    status: ExperimentStatus
    created_at: datetime
    dataset_hash: str | None
    run_fingerprint: str | None
    result_hash: str | None
    engine_version: str | None
    identity_schema_version: int | None
    symbol: str
    timeframe: str
    partition: ResearchPartition
    partition_first_candle: datetime
    partition_last_candle: datetime
    partition_candle_count: int
    strategy_name: str
    configuration: Mapping[str, Any]
    metrics: Mapping[str, Any]
    provenance: Mapping[str, Any]

    @property
    def fully_reproducible(self) -> bool:
        return self.status is ExperimentStatus.COMPLETED and all(
            (self.dataset_hash, self.run_fingerprint, self.result_hash)
        )


@dataclass(frozen=True, slots=True)
class ExperimentSummary:
    experiment_id: str
    status: ExperimentStatus
    created_at: datetime
    symbol: str
    timeframe: str
    effective_start: datetime
    effective_end: datetime
    candle_count: int
    dataset_hash: str | None
    run_fingerprint: str | None
    result_hash: str | None
    engine_version: str | None
    identity_schema_version: int | None
    initial_capital: float | None
    ending_capital: float | None
    total_return: float | None
    total_trades: int | None
    fully_reproducible: bool


@dataclass(frozen=True, slots=True)
class DiscoveryIssue:
    file_name: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ExperimentDiscovery:
    experiments: tuple[ExperimentSummary, ...]
    issues: tuple[DiscoveryIssue, ...]
    total: int


@dataclass(frozen=True, slots=True)
class ExperimentComparison:
    left_experiment_id: str
    right_experiment_id: str
    classification: ComparisonClassification
    controlled_comparison: bool
    both_fully_reproducible: bool
    same_dataset: bool
    same_run_configuration: bool
    same_result: bool
    same_strategy_configuration: bool
    same_risk_configuration: bool
    same_execution_assumptions: bool
    metric_deltas: Mapping[str, float | int | None]


class ExperimentNotFoundError(LookupError):
    pass


class ExperimentConflictError(RuntimeError):
    pass


def _require_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise MarketDataError(f"Research experiment {field} must not be blank")
    return cleaned


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise MarketDataError(f"Research experiment {field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _aware(value, "configuration timestamp").isoformat(timespec="microseconds")
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda p: str(p[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise MarketDataError("Research experiment contains unsupported value", value_type=type(value).__name__)


def _freeze(value: Any) -> Any:
    normalized = _normalize(value)
    if isinstance(normalized, dict):
        return MappingProxyType({key: _freeze(item) for key, item in normalized.items()})
    if isinstance(normalized, list):
        return tuple(_freeze(item) for item in normalized)
    return normalized


def _hash(value: str, field: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71 or any(c not in "0123456789abcdef" for c in value[7:]):
        raise MarketDataError(f"Research experiment {field} must be a lowercase sha256 digest")
    return value


def build_experiment_record(
    *, dataset_hash: str, run_fingerprint: str, result_hash: str,
    engine_version: str, identity_schema_version: int,
    symbol: str, timeframe: str, partition: ResearchPartition,
    partition_first_candle: datetime, partition_last_candle: datetime,
    partition_candle_count: int, strategy_name: str,
    configuration: Mapping[str, Any], metrics: Mapping[str, Any],
    provenance: Mapping[str, Any] | None = None,
    created_at: datetime | None = None, experiment_id: str | None = None,
) -> ExperimentRecord:
    first, last = _aware(partition_first_candle, "partition first candle"), _aware(partition_last_candle, "partition last candle")
    if last < first or partition_candle_count <= 0 or identity_schema_version <= 0:
        raise MarketDataError("Research experiment partition or identity version is invalid")
    return ExperimentRecord(
        SCHEMA_VERSION, _require_text(experiment_id or uuid4().hex, "ID"),
        ExperimentStatus.COMPLETED, _aware(created_at or datetime.now(timezone.utc), "creation time"),
        _hash(dataset_hash, "dataset hash"), _hash(run_fingerprint, "run fingerprint"),
        _hash(result_hash, "result hash"), _require_text(engine_version, "engine version"),
        identity_schema_version, _require_text(symbol, "symbol"), _require_text(timeframe, "timeframe"),
        partition, first, last, partition_candle_count, _require_text(strategy_name, "strategy name"),
        _freeze(configuration), _freeze(metrics), _freeze(provenance or {}),
    )


def _payload(record: ExperimentRecord) -> dict[str, Any]:
    return {
        "schema_version": record.schema_version, "experiment_id": record.experiment_id,
        "status": record.status.value, "created_at": record.created_at.isoformat(timespec="microseconds"),
        "dataset_hash": record.dataset_hash, "run_fingerprint": record.run_fingerprint,
        "result_hash": record.result_hash, "engine_version": record.engine_version,
        "identity_schema_version": record.identity_schema_version, "symbol": record.symbol,
        "timeframe": record.timeframe, "partition": record.partition.value,
        "partition_first_candle": record.partition_first_candle.isoformat(timespec="microseconds"),
        "partition_last_candle": record.partition_last_candle.isoformat(timespec="microseconds"),
        "partition_candle_count": record.partition_candle_count, "strategy_name": record.strategy_name,
        "configuration": _normalize(record.configuration), "metrics": _normalize(record.metrics),
        "provenance": _normalize(record.provenance),
    }


def load_experiment_record(path: Path) -> ExperimentRecord:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = int(payload["schema_version"])
        common = dict(
            experiment_id=_require_text(payload["experiment_id"], "ID"),
            created_at=_aware(datetime.fromisoformat(payload["created_at"]), "creation time"),
            symbol=_require_text(payload["symbol"], "symbol"), timeframe=_require_text(payload["timeframe"], "timeframe"),
            partition=ResearchPartition(payload["partition"]),
            partition_first_candle=_aware(datetime.fromisoformat(payload["partition_first_candle"]), "partition first candle"),
            partition_last_candle=_aware(datetime.fromisoformat(payload["partition_last_candle"]), "partition last candle"),
            partition_candle_count=int(payload["partition_candle_count"]),
            strategy_name=_require_text(payload["strategy_name"], "strategy name"),
        )
        if common["partition_candle_count"] <= 0 or common["partition_last_candle"] < common["partition_first_candle"]:
            raise ValueError("invalid partition")
        if version == 1:
            return ExperimentRecord(
                1, status=ExperimentStatus.LEGACY_INCOMPLETE, dataset_hash=None,
                run_fingerprint=None, result_hash=None, engine_version=None, identity_schema_version=None,
                configuration=_freeze({"strategy": payload.get("strategy_config", {}),
                                       "initial_capital": payload.get("starting_balance")}),
                metrics=_freeze(payload.get("metrics", {})),
                provenance=_freeze({"legacy_dataset_hash": payload.get("dataset_hash"),
                                    "legacy_partition_hash": payload.get("partition_hash")}), **common,
            )
        if version != SCHEMA_VERSION or payload.get("status") != ExperimentStatus.COMPLETED.value:
            raise ValueError("unsupported schema or status")
        record_id, created = common.pop("experiment_id"), common.pop("created_at")
        return build_experiment_record(
            dataset_hash=payload["dataset_hash"], run_fingerprint=payload["run_fingerprint"],
            result_hash=payload["result_hash"], engine_version=payload["engine_version"],
            identity_schema_version=int(payload["identity_schema_version"]),
            configuration=payload["configuration"], metrics=payload["metrics"],
            provenance=payload.get("provenance", {}), experiment_id=record_id, created_at=created, **common,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise MarketDataError("Research experiment record is invalid", path=str(path)) from exc


def compare_experiments(first: ExperimentRecord, second: ExperimentRecord) -> dict[str, bool]:
    """Return factual comparability without interpreting performance."""
    return {
        "both_fully_reproducible": first.fully_reproducible and second.fully_reproducible,
        "same_dataset": first.dataset_hash is not None and first.dataset_hash == second.dataset_hash,
        "same_run_configuration": first.run_fingerprint is not None and first.run_fingerprint == second.run_fingerprint,
        "same_result": first.result_hash is not None and first.result_hash == second.result_hash,
    }


def experiment_record_dict(record: ExperimentRecord) -> dict[str, Any]:
    """Return the stable public representation without exposing storage paths."""
    return _payload(record)


def _metric(record: ExperimentRecord, *names: str) -> float | int | None:
    for name in names:
        value = record.metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def summarize_experiment(record: ExperimentRecord) -> ExperimentSummary:
    return ExperimentSummary(
        record.experiment_id, record.status, record.created_at, record.symbol,
        record.timeframe, record.partition_first_candle, record.partition_last_candle,
        record.partition_candle_count, record.dataset_hash, record.run_fingerprint,
        record.result_hash, record.engine_version, record.identity_schema_version,
        _metric(record, "Starting Balance", "initial_capital"),
        _metric(record, "Ending Balance", "ending_capital"),
        _metric(record, "Return %", "return_percent"),
        int(value) if (value := _metric(record, "Total Trades", "total_trades")) is not None else None,
        record.fully_reproducible,
    )


def compare_experiment_records(first: ExperimentRecord, second: ExperimentRecord) -> ExperimentComparison:
    facts = compare_experiments(first, second)
    first_config, second_config = first.configuration, second.configuration
    same_strategy = first_config.get("strategy") == second_config.get("strategy")
    same_risk = first_config.get("risk") == second_config.get("risk")
    same_execution = first_config.get("execution") == second_config.get("execution")
    if not facts["both_fully_reproducible"]:
        classification = ComparisonClassification.LEGACY_OR_INCOMPLETE
    elif facts["same_result"]:
        classification = ComparisonClassification.IDENTICAL_RESULT
    elif facts["same_run_configuration"]:
        classification = ComparisonClassification.SAME_RUN_CONFIGURATION_DIFFERENT_OBSERVATION
    elif facts["same_dataset"]:
        classification = ComparisonClassification.SAME_DATASET_DIFFERENT_CONFIGURATION
    else:
        classification = ComparisonClassification.DIFFERENT_DATASET
    deltas = {}
    for public_name, aliases in {
        "ending_capital": ("Ending Balance", "ending_capital"),
        "total_return": ("Return %", "return_percent"),
        "total_trades": ("Total Trades", "total_trades"),
        "win_rate": ("Win Rate %", "win_rate_percent"),
        "maximum_drawdown": ("Maximum Drawdown", "maximum_drawdown"),
        "profit_factor": ("Profit Factor", "profit_factor"),
    }.items():
        left, right = _metric(first, *aliases), _metric(second, *aliases)
        deltas[public_name] = None if left is None or right is None else right - left
    return ExperimentComparison(
        first.experiment_id, second.experiment_id, classification,
        bool(facts["both_fully_reproducible"] and facts["same_dataset"]),
        facts["both_fully_reproducible"], facts["same_dataset"],
        facts["same_run_configuration"], facts["same_result"], same_strategy,
        same_risk, same_execution, _freeze(deltas),
    )


_SAFE_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")


class ExperimentCatalog:
    """Bounded, non-recursive authority for persisted experiment records."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, record: ExperimentRecord) -> None:
        if not _SAFE_EXPERIMENT_ID.fullmatch(record.experiment_id):
            raise MarketDataError("Experiment ID is invalid")
        if record.schema_version != SCHEMA_VERSION or record.status is not ExperimentStatus.COMPLETED or not record.fully_reproducible:
            raise MarketDataError("Only complete schema-v2 experiments may be cataloged")
        if self.root.is_symlink():
            raise MarketDataError("Experiment catalog root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{record.experiment_id}.experiment.json"
        if target.is_symlink():
            raise MarketDataError("Experiment target cannot be a symlink")
        serialized = json.dumps(
            _payload(record), sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False
        ) + "\n"
        if target.exists():
            if target.read_text(encoding="utf-8") == serialized:
                return
            raise ExperimentConflictError(
                f"Experiment ID {record.experiment_id} already identifies different content"
            )
        temporary = self.root / f".{record.experiment_id}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(serialized, encoding="utf-8")
            os.link(temporary, target)
            temporary.unlink()
        except FileExistsError:
            temporary.unlink(missing_ok=True)
            if target.is_symlink():
                raise MarketDataError("Experiment target cannot be a symlink")
            if target.read_text(encoding="utf-8") == serialized:
                return
            raise ExperimentConflictError(
                f"Experiment ID {record.experiment_id} was concurrently assigned different content"
            )
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise MarketDataError("Experiment record could not be persisted") from exc

    def discover(
        self, *, symbol: str | None = None, timeframe: str | None = None,
        status: ExperimentStatus | None = None, fully_reproducible: bool | None = None,
        dataset_hash: str | None = None, run_fingerprint: str | None = None,
        limit: int = 50, offset: int = 0,
    ) -> ExperimentDiscovery:
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError("Experiment discovery bounds are invalid")
        if dataset_hash is not None:
            _hash(dataset_hash, "dataset hash")
        if run_fingerprint is not None:
            _hash(run_fingerprint, "run fingerprint")
        records, issues = [], []
        if self.root.is_dir():
            for path in sorted(self.root.iterdir(), key=lambda item: item.name):
                if path.is_symlink() or not path.is_file() or not path.name.endswith(".experiment.json"):
                    continue
                try:
                    records.append(load_experiment_record(path))
                except MarketDataError:
                    issues.append(DiscoveryIssue(path.name, "INVALID_EXPERIMENT_RECORD",
                                                 "Record is malformed or uses an unsupported schema"))
        filtered = [
            record for record in records
            if (symbol is None or record.symbol == symbol)
            and (timeframe is None or record.timeframe == timeframe)
            and (status is None or record.status is status)
            and (fully_reproducible is None or record.fully_reproducible is fully_reproducible)
            and (dataset_hash is None or record.dataset_hash == dataset_hash)
            and (run_fingerprint is None or record.run_fingerprint == run_fingerprint)
        ]
        filtered.sort(key=lambda record: record.experiment_id)
        filtered.sort(key=lambda record: record.created_at, reverse=True)
        return ExperimentDiscovery(
            tuple(summarize_experiment(record) for record in filtered[offset:offset + limit]),
            tuple(issues),
            len(filtered),
        )

    def load(self, experiment_id: str) -> ExperimentRecord:
        if not _SAFE_EXPERIMENT_ID.fullmatch(experiment_id):
            raise ExperimentNotFoundError(experiment_id)
        candidate = self.root / f"{experiment_id}.experiment.json"
        if candidate.is_file() and not candidate.is_symlink():
            record = load_experiment_record(candidate)
            if record.experiment_id != experiment_id:
                raise MarketDataError("Experiment filename and record ID do not match")
            return record
        if self.root.is_dir():
            for path in self.root.iterdir():
                if path.is_file() and not path.is_symlink() and path.name.endswith(".experiment.json"):
                    try:
                        record = load_experiment_record(path)
                    except MarketDataError:
                        continue
                    if record.experiment_id == experiment_id:
                        return record
        raise ExperimentNotFoundError(experiment_id)
