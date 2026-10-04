from datetime import datetime, timedelta, timezone

from broker.types import Candle, Timeframe
from data.provenance import DatasetProvenance, VolumeType
from data.storage import CandleStore
from tools.refresh_syntx_cache import archive_and_normalize_legacy_cache


def test_candlestore_uses_busy_timeout_for_locked_cache(tmp_path):
    path = tmp_path / "history.db"
    store = CandleStore(path)
    with store._connect() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000


def test_legacy_cache_is_archived_and_server_time_normalized_once(tmp_path):
    path = tmp_path / "history.db"
    store = CandleStore(path)
    raw_time = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    normalized_time = raw_time - timedelta(hours=3)
    store.save_candles("FX Vol 20", Timeframe.M1, [
        Candle(time=raw_time, open=100, high=102, low=99, close=101, volume=12, source="weltrade"),
        Candle(time=raw_time + timedelta(hours=3), open=103, high=105, low=102, close=104, volume=13, source="weltrade"),
        Candle(time=normalized_time, open=100, high=102, low=99, close=101, volume=12, source="mt5"),
    ], provider="weltrade")
    store.save_provenance(DatasetProvenance(
        provider="weltrade", symbol="FX Vol 20", timeframe="M1",
        source="Weltrade MT5 terminal", provider_symbol="FX Vol 20",
        volume_type=VolumeType.TICK_VOLUME, retrieved_at=raw_time,
    ))

    backup, archived, shifted = archive_and_normalize_legacy_cache(path, ("FX Vol 20",))

    assert backup is not None and backup.is_file()
    assert archived == 3
    assert shifted == 2
    active = store.load_latest("FX Vol 20", Timeframe.M1, 10, provider="weltrade")
    assert len(active) == 2
    assert [candle.time for candle in active] == [normalized_time, raw_time]
    assert all(candle.source == "weltrade" for candle in active)
    legacy = store.load_latest(
        "FX Vol 20", Timeframe.M1, 10, provider="weltrade_legacy_raw_server_time"
    )
    assert len(legacy) == 3
    assert any(candle.time == raw_time for candle in legacy)
    assert store.load_provenance(
        "weltrade_legacy_raw_server_time", "FX Vol 20", Timeframe.M1
    ) is not None

    second_backup, second_archived, second_shifted = archive_and_normalize_legacy_cache(
        path, ("FX Vol 20",)
    )
    assert (second_backup, second_archived, second_shifted) == (None, 0, 0)
    assert store.load_latest("FX Vol 20", Timeframe.M1, 2, provider="weltrade")[0].time == normalized_time