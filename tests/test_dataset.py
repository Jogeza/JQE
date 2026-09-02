from datetime import timezone

import pytest

from core.exceptions import MarketDataError
from data.dataset import load_candle_csv


def test_csv_loader_requires_explicit_timezone_for_naive_data(tmp_path) -> None:
    path = tmp_path / "candles.csv"
    path.write_text("time,open,high,low,close\n2024-01-01 00:00:00,1,2,0.5,1.5\n")
    with pytest.raises(MarketDataError):
        load_candle_csv(path, source="fixture")


def test_csv_loader_is_ordered_duplicate_safe_and_preserves_missing_volume(tmp_path) -> None:
    path = tmp_path / "candles.csv"
    path.write_text(
        "time,open,high,low,close\n"
        "2024-01-01 00:05:00,2,3,1,2.5\n"
        "2024-01-01 00:00:00,1,2,0.5,1.5\n"
        "2024-01-01 00:05:00,2,3,1,2.6\n"
    )
    candles = load_candle_csv(path, source="fixture", naive_timezone=timezone.utc)
    assert len(candles) == 2
    assert candles[0].time < candles[1].time
    assert candles[1].close == 2.6
    assert candles[0].volume is None
    assert candles[0].source == "fixture"

def test_dataset_manifest_records_identity_and_provenance() -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="deriv",
        )
        for i in range(3)
    ]

    retrieved_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=retrieved_at,
    )

    assert manifest.provider == "Deriv"
    assert manifest.source == "public historical API"
    assert manifest.provider_symbol == "frxXAUUSD"
    assert manifest.canonical_symbol == "XAUUSD"
    assert manifest.timeframe is Timeframe.M15
    assert manifest.granularity_seconds == 900
    assert manifest.first_candle == candles[0].time
    assert manifest.last_candle == candles[-1].time
    assert manifest.candle_count == 3
    assert manifest.volume_available is False
    assert manifest.retrieved_at == retrieved_at
    assert manifest.content_hash.startswith("sha256:")
    assert len(manifest.content_hash) == 71


def test_dataset_content_hash_is_deterministic() -> None:
    from datetime import datetime, timezone

    from broker.types import Candle
    from data.dataset import candle_content_hash

    candles = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    first = candle_content_hash(candles)
    second = candle_content_hash(list(candles))

    assert first == second


def test_dataset_content_hash_changes_when_candle_content_changes() -> None:
    from datetime import datetime, timezone

    from broker.types import Candle
    from data.dataset import candle_content_hash

    original = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    changed = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.6,
            volume=None,
            source="deriv",
        )
    ]

    assert candle_content_hash(original) != candle_content_hash(changed)


def test_dataset_manifest_rejects_non_monotonic_candles() -> None:
    from datetime import datetime, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest

    time = datetime(2026, 1, 1, tzinfo=timezone.utc)

    candle = Candle(
        time=time,
        open=2600.0,
        high=2601.0,
        low=2599.0,
        close=2600.5,
        volume=None,
        source="deriv",
    )

    with pytest.raises(MarketDataError):
        build_dataset_manifest(
            [candle, candle],
            provider="Deriv",
            source="public historical API",
            provider_symbol="frxXAUUSD",
            canonical_symbol="XAUUSD",
            timeframe=Timeframe.M15,
        )

def test_dataset_manifest_json_round_trip(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import (
        build_dataset_manifest,
        load_dataset_manifest,
        save_dataset_manifest,
    )

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="deriv",
        )
        for i in range(3)
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    path = tmp_path / "xauusd-m15.manifest.json"
    save_dataset_manifest(path, manifest)

    loaded = load_dataset_manifest(path)

    assert loaded == manifest


def test_dataset_manifest_json_is_stable(tmp_path) -> None:
    from datetime import datetime, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest, save_dataset_manifest

    candles = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    save_dataset_manifest(first, manifest)
    save_dataset_manifest(second, manifest)

    assert first.read_bytes() == second.read_bytes()


def test_dataset_manifest_verifies_original_candles() -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest, verify_dataset_manifest

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="deriv",
        )
        for i in range(3)
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
    )

    verify_dataset_manifest(manifest, candles)


def test_dataset_manifest_rejects_modified_candle_content() -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest, verify_dataset_manifest

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    original = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="deriv",
        )
        for i in range(3)
    ]

    manifest = build_dataset_manifest(
        original,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
    )

    modified = list(original)
    modified[1] = Candle(
        time=modified[1].time,
        open=modified[1].open,
        high=modified[1].high,
        low=modified[1].low,
        close=modified[1].close + 0.01,
        volume=modified[1].volume,
        source=modified[1].source,
    )

    with pytest.raises(MarketDataError):
        verify_dataset_manifest(manifest, modified)


def test_dataset_manifest_loader_rejects_tampered_hash(tmp_path) -> None:
    import json
    from datetime import datetime, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import (
        build_dataset_manifest,
        load_dataset_manifest,
        save_dataset_manifest,
    )

    candles = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
    )

    path = tmp_path / "manifest.json"
    save_dataset_manifest(path, manifest)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["content_hash"] = "sha256:not-a-valid-digest"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MarketDataError):
        load_dataset_manifest(path)

def test_dataset_bundle_round_trip(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import (
        build_dataset_manifest,
        export_dataset_bundle,
        load_dataset_bundle,
    )

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="deriv",
        )
        for i in range(3)
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    bundle = tmp_path / "XAUUSD_M15"
    export_dataset_bundle(bundle, candles, manifest)

    loaded_candles, loaded_manifest = load_dataset_bundle(bundle)

    assert loaded_candles == candles
    assert loaded_manifest == manifest
    assert (bundle / "candles.csv").is_file()
    assert (bundle / "manifest.json").is_file()


def test_dataset_bundle_export_is_deterministic(tmp_path) -> None:
    from datetime import datetime, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest, export_dataset_bundle

    candles = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    first = tmp_path / "first"
    second = tmp_path / "second"

    export_dataset_bundle(first, candles, manifest)
    export_dataset_bundle(second, candles, manifest)

    assert (first / "candles.csv").read_bytes() == (
        second / "candles.csv"
    ).read_bytes()

    assert (first / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()


def test_dataset_bundle_rejects_tampered_candles(tmp_path) -> None:
    from datetime import datetime, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import (
        build_dataset_manifest,
        export_dataset_bundle,
        load_dataset_bundle,
    )

    candles = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
    )

    bundle = tmp_path / "bundle"
    export_dataset_bundle(bundle, candles, manifest)

    candle_path = bundle / "candles.csv"
    content = candle_path.read_text(encoding="utf-8")
    candle_path.write_text(
        content.replace("2600.5", "2600.6"),
        encoding="utf-8",
    )

    with pytest.raises(MarketDataError):
        load_dataset_bundle(bundle)


def test_dataset_bundle_rejects_manifest_for_different_candles(tmp_path) -> None:
    from datetime import datetime, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest, export_dataset_bundle

    original = [
        Candle(
            time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            open=2600.0,
            high=2601.0,
            low=2599.0,
            close=2600.5,
            volume=None,
            source="deriv",
        )
    ]

    manifest = build_dataset_manifest(
        original,
        provider="Deriv",
        source="public historical API",
        provider_symbol="frxXAUUSD",
        canonical_symbol="XAUUSD",
        timeframe=Timeframe.M15,
    )

    changed = [
        Candle(
            time=original[0].time,
            open=original[0].open,
            high=original[0].high,
            low=original[0].low,
            close=2600.6,
            volume=None,
            source="deriv",
        )
    ]

    with pytest.raises(MarketDataError):
        export_dataset_bundle(tmp_path / "bundle", changed, manifest)
