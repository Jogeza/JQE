"""Load and identify immutable local candle datasets without contacting a broker."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Sequence

from broker.types import TIMEFRAME_SECONDS, Candle, Timeframe
from core.exceptions import MarketDataError


@dataclass(frozen=True, slots=True)
class CandleDatasetManifest:
    """Reproducible identity and provenance for one frozen candle dataset."""

    provider: str
    source: str
    provider_symbol: str
    canonical_symbol: str
    timeframe: Timeframe
    granularity_seconds: int
    first_candle: datetime
    last_candle: datetime
    candle_count: int
    volume_available: bool
    retrieved_at: datetime
    content_hash: str


def candle_content_hash(candles: Sequence[Candle]) -> str:
    """Return a deterministic SHA-256 over normalized canonical candles.

    The digest identifies candle content rather than a CSV or SQLite file, so
    storage-format changes do not alter dataset identity.
    """
    normalized = [
        {
            "time": candle.time.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            ),
            "open": float(candle.open),
            "high": float(candle.high),
            "low": float(candle.low),
            "close": float(candle.close),
            "volume": None if candle.volume is None else float(candle.volume),
            "source": candle.source,
        }
        for candle in candles
    ]

    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")

    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_dataset_hash(
    candles: Sequence[Candle], *, symbol: str, timeframe: Timeframe
) -> str:
    """Identify the exact canonical market sequence used by a backtest.

    Provider and per-row source are provenance, not market facts, so they are
    deliberately excluded. Symbol and timeframe are bound to the ordered OHLCV
    sequence under an explicit schema version.
    """
    normalized_candles = []
    for candle in candles:
        if candle.time.tzinfo is None:
            raise MarketDataError("Dataset identity requires timezone-aware timestamps")
        normalized_candles.append({
            "time": candle.time.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            "open": float(candle.open), "high": float(candle.high),
            "low": float(candle.low), "close": float(candle.close),
            "volume": None if candle.volume is None else float(candle.volume),
        })
    payload = {
        "dataset_identity_schema_version": 1,
        "symbol": symbol.strip().upper(),
        "timeframe": timeframe.value,
        "candles": normalized_candles,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                         allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def build_dataset_manifest(
    candles: Sequence[Candle],
    *,
    provider: str,
    source: str,
    provider_symbol: str,
    canonical_symbol: str,
    timeframe: Timeframe,
    retrieved_at: datetime | None = None,
) -> CandleDatasetManifest:
    """Build immutable provenance metadata for a canonical candle sequence."""
    if not candles:
        raise MarketDataError("Cannot manifest an empty historical dataset")

    required_text = {
        "provider": provider,
        "source": source,
        "provider_symbol": provider_symbol,
        "canonical_symbol": canonical_symbol,
    }
    for name, value in required_text.items():
        if not value.strip():
            raise MarketDataError(
                "Historical dataset manifest field is required",
                field=name,
            )

    ordered = list(candles)
    if any(
        current.time <= previous.time
        for previous, current in zip(ordered, ordered[1:])
    ):
        raise MarketDataError(
            "Historical dataset timestamps must be strictly increasing"
        )

    captured_at = retrieved_at or datetime.now(timezone.utc)
    if captured_at.tzinfo is None:
        raise MarketDataError("Dataset retrieval timestamp must be timezone-aware")
    captured_at = captured_at.astimezone(timezone.utc)

    first = ordered[0].time
    last = ordered[-1].time
    if first.tzinfo is None or last.tzinfo is None:
        raise MarketDataError("Historical candle timestamps must be timezone-aware")

    return CandleDatasetManifest(
        provider=provider.strip(),
        source=source.strip(),
        provider_symbol=provider_symbol.strip(),
        canonical_symbol=canonical_symbol.strip(),
        timeframe=timeframe,
        granularity_seconds=TIMEFRAME_SECONDS[timeframe],
        first_candle=first.astimezone(timezone.utc),
        last_candle=last.astimezone(timezone.utc),
        candle_count=len(ordered),
        volume_available=all(candle.volume is not None for candle in ordered),
        retrieved_at=captured_at,
        content_hash=candle_content_hash(ordered),
    )


def load_candle_csv(
    path: Path,
    *,
    source: str,
    naive_timezone: tzinfo | None = None,
) -> list[Candle]:
    """Load, validate, UTC-normalize, order, and de-duplicate a fixed CSV.

    Naive timestamps are rejected unless the caller explicitly supplies the
    timezone in which the source file was recorded.
    """
    if not source.strip():
        raise MarketDataError("Historical dataset source is required")

    by_time: dict[datetime, Candle] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for line_number, row in enumerate(csv.DictReader(handle), start=2):
                try:
                    timestamp = datetime.fromisoformat(row["time"])
                    if timestamp.tzinfo is None:
                        if naive_timezone is None:
                            raise ValueError("naive timestamp")
                        timestamp = timestamp.replace(tzinfo=naive_timezone)
                    timestamp = timestamp.astimezone(timezone.utc)

                    values = {
                        name: float(row[name])
                        for name in ("open", "high", "low", "close")
                    }

                    if not all(
                        math.isfinite(value) and value > 0
                        for value in values.values()
                    ):
                        raise ValueError("prices must be positive and finite")

                    if values["high"] < max(
                        values["open"],
                        values["close"],
                        values["low"],
                    ):
                        raise ValueError("high is below an OHLC value")

                    if values["low"] > min(
                        values["open"],
                        values["close"],
                        values["high"],
                    ):
                        raise ValueError("low is above an OHLC value")

                    volume_text = row.get("volume") or row.get("tick_volume")
                    volume = (
                        float(volume_text)
                        if volume_text not in (None, "")
                        else None
                    )

                    if volume is not None and (
                        not math.isfinite(volume) or volume < 0
                    ):
                        raise ValueError("volume must be non-negative and finite")

                except (KeyError, TypeError, ValueError) as exc:
                    raise MarketDataError(
                        "Invalid historical candle",
                        path=str(path),
                        line=line_number,
                    ) from exc

                by_time[timestamp] = Candle(
                    time=timestamp,
                    volume=volume,
                    source=source,
                    **values,
                )

    except OSError as exc:
        raise MarketDataError(
            "Historical dataset could not be read",
            path=str(path),
        ) from exc

    return [by_time[key] for key in sorted(by_time)]

def save_dataset_manifest(
    path: Path,
    manifest: CandleDatasetManifest,
) -> None:
    """Atomically persist a dataset manifest as stable UTF-8 JSON."""
    payload = {
        "schema_version": 1,
        "provider": manifest.provider,
        "source": manifest.source,
        "provider_symbol": manifest.provider_symbol,
        "canonical_symbol": manifest.canonical_symbol,
        "timeframe": manifest.timeframe.value,
        "granularity_seconds": manifest.granularity_seconds,
        "first_candle": manifest.first_candle.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "last_candle": manifest.last_candle.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "candle_count": manifest.candle_count,
        "volume_available": manifest.volume_available,
        "retrieved_at": manifest.retrieved_at.astimezone(timezone.utc).isoformat(
            timespec="microseconds"
        ),
        "content_hash": manifest.content_hash,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    try:
        temporary.write_text(
            json.dumps(
                payload,
                sort_keys=True,
                indent=2,
                ensure_ascii=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

        raise MarketDataError(
            "Historical dataset manifest could not be written",
            path=str(path),
        ) from exc


def load_dataset_manifest(path: Path) -> CandleDatasetManifest:
    """Load and validate a persisted dataset manifest."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDataError(
            "Historical dataset manifest could not be read",
            path=str(path),
        ) from exc

    try:
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported schema version")

        timeframe = Timeframe(payload["timeframe"])

        granularity_seconds = int(payload["granularity_seconds"])
        if granularity_seconds != TIMEFRAME_SECONDS[timeframe]:
            raise ValueError("timeframe granularity mismatch")

        first_candle = datetime.fromisoformat(payload["first_candle"])
        last_candle = datetime.fromisoformat(payload["last_candle"])
        retrieved_at = datetime.fromisoformat(payload["retrieved_at"])

        if (
            first_candle.tzinfo is None
            or last_candle.tzinfo is None
            or retrieved_at.tzinfo is None
        ):
            raise ValueError("manifest timestamps must be timezone-aware")

        first_candle = first_candle.astimezone(timezone.utc)
        last_candle = last_candle.astimezone(timezone.utc)
        retrieved_at = retrieved_at.astimezone(timezone.utc)

        candle_count = int(payload["candle_count"])
        if candle_count <= 0:
            raise ValueError("candle count must be positive")

        if last_candle < first_candle:
            raise ValueError("manifest candle range is invalid")

        volume_available = payload["volume_available"]
        if not isinstance(volume_available, bool):
            raise ValueError("volume_available must be boolean")

        content_hash = str(payload["content_hash"])
        if not content_hash.startswith("sha256:") or len(content_hash) != 71:
            raise ValueError("invalid content hash")

        digest = content_hash.removeprefix("sha256:")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("invalid content hash")

        required_text = {
            "provider": payload["provider"],
            "source": payload["source"],
            "provider_symbol": payload["provider_symbol"],
            "canonical_symbol": payload["canonical_symbol"],
        }

        for name, value in required_text.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

    except (KeyError, TypeError, ValueError) as exc:
        raise MarketDataError(
            "Historical dataset manifest is invalid",
            path=str(path),
        ) from exc

    return CandleDatasetManifest(
        provider=required_text["provider"].strip(),
        source=required_text["source"].strip(),
        provider_symbol=required_text["provider_symbol"].strip(),
        canonical_symbol=required_text["canonical_symbol"].strip(),
        timeframe=timeframe,
        granularity_seconds=granularity_seconds,
        first_candle=first_candle,
        last_candle=last_candle,
        candle_count=candle_count,
        volume_available=volume_available,
        retrieved_at=retrieved_at,
        content_hash=content_hash,
    )


def verify_dataset_manifest(
    manifest: CandleDatasetManifest,
    candles: Sequence[Candle],
) -> None:
    """Fail closed when canonical candle content differs from its manifest."""
    if not candles:
        raise MarketDataError(
            "Historical dataset cannot be verified because it is empty"
        )

    ordered = list(candles)

    if any(
        current.time <= previous.time
        for previous, current in zip(ordered, ordered[1:])
    ):
        raise MarketDataError(
            "Historical dataset verification requires strictly increasing timestamps"
        )

    if manifest.granularity_seconds != TIMEFRAME_SECONDS[manifest.timeframe]:
        raise MarketDataError(
            "Historical dataset manifest granularity is inconsistent"
        )

    if len(ordered) != manifest.candle_count:
        raise MarketDataError(
            "Historical dataset candle count does not match manifest"
        )

    first = ordered[0].time
    last = ordered[-1].time

    if first.tzinfo is None or last.tzinfo is None:
        raise MarketDataError(
            "Historical dataset verification requires timezone-aware timestamps"
        )

    if first.astimezone(timezone.utc) != manifest.first_candle:
        raise MarketDataError(
            "Historical dataset first candle does not match manifest"
        )

    if last.astimezone(timezone.utc) != manifest.last_candle:
        raise MarketDataError(
            "Historical dataset last candle does not match manifest"
        )

    volume_available = all(candle.volume is not None for candle in ordered)
    if volume_available != manifest.volume_available:
        raise MarketDataError(
            "Historical dataset volume availability does not match manifest"
        )

    actual_hash = candle_content_hash(ordered)
    if actual_hash != manifest.content_hash:
        raise MarketDataError(
            "Historical dataset content hash does not match manifest"
        )

def _write_candle_csv(path: Path, candles: Sequence[Candle]) -> None:
    """Write canonical candles as deterministic UTF-8 CSV."""
    ordered = list(candles)

    if not ordered:
        raise MarketDataError("Historical dataset cannot be exported because it is empty")

    if any(
        current.time <= previous.time
        for previous, current in zip(ordered, ordered[1:])
    ):
        raise MarketDataError(
            "Historical dataset export requires strictly increasing timestamps"
        )

    temporary = path.with_name(path.name + ".tmp")

    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(
                ["time", "open", "high", "low", "close", "volume", "source"]
            )

            for candle in ordered:
                if candle.time.tzinfo is None:
                    raise MarketDataError(
                        "Historical dataset export requires timezone-aware timestamps"
                    )

                writer.writerow(
                    [
                        candle.time.astimezone(timezone.utc).isoformat(
                            timespec="microseconds"
                        ),
                        repr(float(candle.open)),
                        repr(float(candle.high)),
                        repr(float(candle.low)),
                        repr(float(candle.close)),
                        "" if candle.volume is None else repr(float(candle.volume)),
                        candle.source,
                    ]
                )

        temporary.replace(path)
    except MarketDataError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

        raise MarketDataError(
            "Historical dataset candles could not be written",
            path=str(path),
        ) from exc


def export_dataset_bundle(
    directory: Path,
    candles: Sequence[Candle],
    manifest: CandleDatasetManifest,
) -> None:
    """Persist candles and their verified manifest as one frozen dataset bundle."""
    ordered = list(candles)

    # Do not persist a manifest that does not describe the supplied candles.
    verify_dataset_manifest(manifest, ordered)

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MarketDataError(
            "Historical dataset bundle directory could not be created",
            path=str(directory),
        ) from exc

    candle_path = directory / "candles.csv"
    manifest_path = directory / "manifest.json"

    _write_candle_csv(candle_path, ordered)

    try:
        save_dataset_manifest(manifest_path, manifest)
    except Exception:
        # Avoid leaving a newly exported candle file presented as a complete bundle.
        try:
            candle_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_dataset_bundle(
    directory: Path,
) -> tuple[list[Candle], CandleDatasetManifest]:
    """Load a frozen bundle and fail closed unless its manifest matches its candles."""
    manifest_path = directory / "manifest.json"
    candle_path = directory / "candles.csv"

    manifest = load_dataset_manifest(manifest_path)

    candles = load_candle_csv(
        candle_path,
        source=manifest.source,
    )

    # The CSV source column is part of canonical candle identity. load_candle_csv()
    # accepts an explicit source for older external CSVs, so restore the bundle's
    # per-row source values here when the loader does not already preserve them.
    try:
        with candle_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise MarketDataError(
            "Historical dataset bundle candles could not be read",
            path=str(candle_path),
        ) from exc

    if len(rows) != len(candles):
        raise MarketDataError(
            "Historical dataset bundle row count is inconsistent"
        )

    restored: list[Candle] = []
    for candle, row in zip(candles, rows):
        row_source = (row.get("source") or "").strip()
        if not row_source:
            raise MarketDataError(
                "Historical dataset bundle candle source is missing"
            )

        restored.append(
            Candle(
                time=candle.time,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
                source=row_source,
            )
        )

    verify_dataset_manifest(manifest, restored)

    return restored, manifest
