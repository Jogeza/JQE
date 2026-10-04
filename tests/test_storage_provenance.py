from datetime import datetime, timezone
import sqlite3

from broker.types import Candle, Tick, Timeframe
from data.provenance import DatasetProvenance, VolumeType
from data.storage import CandleStore


def test_provenance_round_trip_and_schema_version(tmp_path):
    path = tmp_path / "candles.db"
    store = CandleStore(path)
    value = DatasetProvenance(
        provider="deriv", symbol="XAUUSD", timeframe="M15",
        source="Deriv public historical WebSocket", provider_symbol="frxXAUUSD",
        volume_type=VolumeType.UNAVAILABLE,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    store.save_provenance(value)
    assert store.load_provenance("deriv", "XAUUSD", Timeframe.M15) == value
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()[0] == "2"


def test_read_only_legacy_database_without_provenance_returns_none(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE candles(provider TEXT,symbol TEXT,timeframe TEXT,time INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL,source TEXT)")
    store = CandleStore(path, read_only=True)
    assert store.load_provenance("legacy", "XAUUSD", Timeframe.M15) is None


def test_cached_dataset_enumeration_preserves_symbol_timeframe_and_provenance_isolation(tmp_path):
    path = tmp_path / "markets.db"; store = CandleStore(path)
    candle = Candle(time=datetime(2026, 1, 1, tzinfo=timezone.utc), open=1, high=2, low=1, close=2, volume=None, source="deriv")
    for symbol, timeframe, provider_symbol in (("EURUSD", Timeframe.M15, "frxEURUSD"),
        ("GBPUSD", Timeframe.M15, "frxGBPUSD"), ("EURUSD", Timeframe.M5, "frxEURUSD")):
        store.save_candles(symbol, timeframe, [candle], provider="deriv")
        store.save_provenance(DatasetProvenance("deriv", symbol, timeframe.value, "public", provider_symbol,
            VolumeType.UNAVAILABLE, datetime(2026, 1, 1, tzinfo=timezone.utc)))
    summaries = store.list_cached_datasets("deriv")
    assert {(item.canonical_symbol, item.timeframe) for item in summaries} == {("EURUSD", "M15"), ("GBPUSD", "M15"), ("EURUSD", "M5")}
    assert all(item.volume_type is VolumeType.UNAVAILABLE for item in summaries)


def test_tick_round_trip_isolated_by_provider_and_keeps_terminal_symbol(tmp_path):
    store = CandleStore(tmp_path / "ticks.db")
    tick = Tick(
        time=datetime(2026, 1, 1, tzinfo=timezone.utc).replace(microsecond=123000),
        symbol="FX Vol 20",
        bid=100.0,
        ask=100.2,
        last=100.1,
    )

    assert store.save_ticks("FX Vol 20", "FX Vol 20", [tick], provider="weltrade") == 1
    assert store.save_ticks("FX Vol 20", "FX Vol 20", [tick], provider="weltrade") == 0
    assert store.load_latest_tick("FX Vol 20", provider="weltrade") == tick
    assert store.load_latest_tick("FX Vol 20", provider="simulation") is None
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute(
            "SELECT provider_symbol FROM ticks WHERE provider='weltrade'"
        ).fetchone()[0] == "FX Vol 20"
