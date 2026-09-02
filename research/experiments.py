"""Immutable deterministic research experiment records for JQE."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from core.exceptions import MarketDataError


SCHEMA_VERSION = 1


class ResearchPartition(str, Enum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    OOS = "OOS"


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    schema_version: int
    experiment_id: str
    created_at: datetime
    dataset_hash: str
    partition_hash: str
    symbol: str
    timeframe: str
    partition: ResearchPartition
    partition_first_candle: datetime
    partition_last_candle: datetime
    partition_candle_count: int
    strategy_name: str
    strategy_config: dict[str, Any]
    starting_balance: float
    metrics: dict[str, Any]


def _require_text(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise MarketDataError(f"Research experiment {field} must not be blank")
    return cleaned


def _require_aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None:
        raise MarketDataError(
            f"Research experiment {field} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MarketDataError(
                "Research experiment configuration contains a naive datetime"
            )
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise MarketDataError(
        "Research experiment contains unsupported configuration value",
        value_type=type(value).__name__,
    )


def _validate_hash(value: str) -> str:
    if (
        not value.startswith("sha256:")
        or len(value) != 71
        or any(char not in "0123456789abcdef" for char in value[7:])
    ):
        raise MarketDataError(
            "Research experiment dataset hash must be a lowercase sha256 digest"
        )
    return value


def experiment_identity(
    *,
    dataset_hash: str,
    partition_hash: str,
    symbol: str,
    timeframe: str,
    partition: ResearchPartition,
    partition_first_candle: datetime,
    partition_last_candle: datetime,
    partition_candle_count: int,
    strategy_name: str,
    strategy_config: Mapping[str, Any],
    starting_balance: float,
) -> str:
    """Derive stable identity from experiment inputs, excluding results/time."""
    dataset_hash = _validate_hash(dataset_hash)
    partition_hash = _validate_hash(partition_hash)

    first = _require_aware_utc(
        partition_first_candle,
        "partition first candle",
    )
    last = _require_aware_utc(
        partition_last_candle,
        "partition last candle",
    )

    if last < first:
        raise MarketDataError(
            "Research experiment partition ends before it starts"
        )

    if partition_candle_count <= 0:
        raise MarketDataError(
            "Research experiment partition candle count must be positive"
        )

    payload = {
        "dataset_hash": dataset_hash,
        "partition_hash": partition_hash,
        "symbol": _require_text(symbol, "symbol"),
        "timeframe": _require_text(timeframe, "timeframe"),
        "partition": partition.value,
        "partition_first_candle": first.isoformat(timespec="microseconds"),
        "partition_last_candle": last.isoformat(timespec="microseconds"),
        "partition_candle_count": partition_candle_count,
        "strategy_name": _require_text(strategy_name, "strategy name"),
        "strategy_config": _normalize_json_value(strategy_config),
        "starting_balance": float(starting_balance),
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_experiment_record(
    *,
    dataset_hash: str,
    partition_hash: str,
    symbol: str,
    timeframe: str,
    partition: ResearchPartition,
    partition_first_candle: datetime,
    partition_last_candle: datetime,
    partition_candle_count: int,
    strategy_name: str,
    strategy_config: Mapping[str, Any],
    starting_balance: float,
    metrics: Mapping[str, Any],
    created_at: datetime | None = None,
) -> ExperimentRecord:
    created = _require_aware_utc(
        created_at or datetime.now(timezone.utc),
        "creation time",
    )

    normalized_config = _normalize_json_value(strategy_config)
    normalized_metrics = _normalize_json_value(metrics)

    experiment_id = experiment_identity(
        dataset_hash=dataset_hash,
        partition_hash=partition_hash,
        symbol=symbol,
        timeframe=timeframe,
        partition=partition,
        partition_first_candle=partition_first_candle,
        partition_last_candle=partition_last_candle,
        partition_candle_count=partition_candle_count,
        strategy_name=strategy_name,
        strategy_config=normalized_config,
        starting_balance=starting_balance,
    )

    return ExperimentRecord(
        schema_version=SCHEMA_VERSION,
        experiment_id=experiment_id,
        created_at=created,
        dataset_hash=_validate_hash(dataset_hash),
        partition_hash=_validate_hash(partition_hash),
        symbol=_require_text(symbol, "symbol"),
        timeframe=_require_text(timeframe, "timeframe"),
        partition=partition,
        partition_first_candle=_require_aware_utc(
            partition_first_candle,
            "partition first candle",
        ),
        partition_last_candle=_require_aware_utc(
            partition_last_candle,
            "partition last candle",
        ),
        partition_candle_count=partition_candle_count,
        strategy_name=_require_text(strategy_name, "strategy name"),
        strategy_config=normalized_config,
        starting_balance=float(starting_balance),
        metrics=normalized_metrics,
    )


def save_experiment_record(path: Path, record: ExperimentRecord) -> None:
    payload = asdict(record)

    payload["created_at"] = record.created_at.isoformat(
        timespec="microseconds"
    )
    payload["partition_first_candle"] = record.partition_first_candle.isoformat(
        timespec="microseconds"
    )
    payload["partition_last_candle"] = record.partition_last_candle.isoformat(
        timespec="microseconds"
    )
    payload["partition"] = record.partition.value

    serialized = json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        ensure_ascii=True,
    ) + "\n"

    temporary = path.with_name(path.name + ".tmp")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

        raise MarketDataError(
            "Research experiment record could not be written",
            path=str(path),
        ) from exc


def load_experiment_record(path: Path) -> ExperimentRecord:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError(
            "Research experiment record could not be loaded",
            path=str(path),
        ) from exc

    try:
        if payload["schema_version"] != SCHEMA_VERSION:
            raise ValueError("unsupported schema")

        partition = ResearchPartition(payload["partition"])

        created_at = datetime.fromisoformat(payload["created_at"])
        first = datetime.fromisoformat(payload["partition_first_candle"])
        last = datetime.fromisoformat(payload["partition_last_candle"])

        expected_id = experiment_identity(
            dataset_hash=payload["dataset_hash"],
            partition_hash=payload["partition_hash"],
            symbol=payload["symbol"],
            timeframe=payload["timeframe"],
            partition=partition,
            partition_first_candle=first,
            partition_last_candle=last,
            partition_candle_count=int(payload["partition_candle_count"]),
            strategy_name=payload["strategy_name"],
            strategy_config=payload["strategy_config"],
            starting_balance=float(payload["starting_balance"]),
        )

        if payload["experiment_id"] != expected_id:
            raise ValueError("experiment identity mismatch")

        return ExperimentRecord(
            schema_version=SCHEMA_VERSION,
            experiment_id=expected_id,
            created_at=_require_aware_utc(created_at, "creation time"),
            dataset_hash=_validate_hash(payload["dataset_hash"]),
            partition_hash=_validate_hash(payload["partition_hash"]),
            symbol=_require_text(payload["symbol"], "symbol"),
            timeframe=_require_text(payload["timeframe"], "timeframe"),
            partition=partition,
            partition_first_candle=_require_aware_utc(
                first,
                "partition first candle",
            ),
            partition_last_candle=_require_aware_utc(
                last,
                "partition last candle",
            ),
            partition_candle_count=int(payload["partition_candle_count"]),
            strategy_name=_require_text(
                payload["strategy_name"],
                "strategy name",
            ),
            strategy_config=_normalize_json_value(
                payload["strategy_config"]
            ),
            starting_balance=float(payload["starting_balance"]),
            metrics=_normalize_json_value(payload["metrics"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError(
            "Research experiment record is invalid",
            path=str(path),
        ) from exc
