"""Tests for data.storage — the local SQLite candle cache."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from broker.types import Candle, Timeframe
from core.exceptions import CacheError
from data.storage import CandleStore, find_gaps

_BASE_TIME = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _candle(minutes_offset: int, price: float = 100.0) -> Candle:
    return Candle(
        time=_BASE_TIME + timedelta(minutes=minutes_offset),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=10.0,
    )


@pytest.fixture
def store() -> CandleStore:
    with tempfile.TemporaryDirectory() as tmp:
        yield CandleStore(db_path=Path(tmp) / "test.db")


class TestSaveAndLoadCandles:
    def test_round_trips_candle_data(self, store: CandleStore) -> None:
        candles = [_candle(0), _candle(5), _candle(10)]
        written = store.save_candles("R_100", Timeframe.M5, candles)
        assert written == 3

        loaded = store.load_candles("R_100", Timeframe.M5)
        assert len(loaded) == 3
        assert loaded[0].time == candles[0].time
        assert loaded == sorted(loaded, key=lambda c: c.time)

    def test_overlapping_save_does_not_duplicate(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0), _candle(5)])
        store.save_candles("R_100", Timeframe.M5, [_candle(5), _candle(10)])
        assert store.count("R_100", Timeframe.M5) == 3

    def test_upsert_replaces_existing_candle_at_same_time(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0, price=100.0)])
        store.save_candles("R_100", Timeframe.M5, [_candle(0, price=200.0)])
        loaded = store.load_candles("R_100", Timeframe.M5)
        assert len(loaded) == 1
        assert loaded[0].close == 200.0

    def test_saving_empty_list_writes_nothing(self, store: CandleStore) -> None:
        assert store.save_candles("R_100", Timeframe.M5, []) == 0

    def test_different_symbols_are_isolated(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0)])
        store.save_candles("R_50", Timeframe.M5, [_candle(0), _candle(5)])
        assert store.count("R_100", Timeframe.M5) == 1
        assert store.count("R_50", Timeframe.M5) == 2

    def test_different_timeframes_are_isolated(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0)])
        store.save_candles("R_100", Timeframe.M1, [_candle(0), _candle(1)])
        assert store.count("R_100", Timeframe.M5) == 1
        assert store.count("R_100", Timeframe.M1) == 2

    def test_load_respects_start_and_end(self, store: CandleStore) -> None:
        store.save_candles(
            "R_100", Timeframe.M5, [_candle(0), _candle(5), _candle(10), _candle(15)]
        )
        loaded = store.load_candles(
            "R_100",
            Timeframe.M5,
            start=_BASE_TIME + timedelta(minutes=5),
            end=_BASE_TIME + timedelta(minutes=10),
        )
        assert [c.time for c in loaded] == [
            _BASE_TIME + timedelta(minutes=5),
            _BASE_TIME + timedelta(minutes=10),
        ]


class TestLoadLatest:
    def test_returns_most_recent_n_oldest_to_newest(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(i * 5) for i in range(10)])
        latest = store.load_latest("R_100", Timeframe.M5, 3)
        assert [c.time for c in latest] == [
            _BASE_TIME + timedelta(minutes=35),
            _BASE_TIME + timedelta(minutes=40),
            _BASE_TIME + timedelta(minutes=45),
        ]

    def test_shorter_than_requested_when_not_enough_cached(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0), _candle(5)])
        assert len(store.load_latest("R_100", Timeframe.M5, 10)) == 2


class TestCoverageAndCount:
    def test_returns_none_when_nothing_cached(self, store: CandleStore) -> None:
        assert store.get_coverage("R_100", Timeframe.M5) is None

    def test_returns_earliest_and_latest(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0), _candle(5), _candle(10)])
        earliest, latest = store.get_coverage("R_100", Timeframe.M5)
        assert earliest == _BASE_TIME
        assert latest == _BASE_TIME + timedelta(minutes=10)

    def test_count_reflects_stored_rows(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0), _candle(5)])
        assert store.count("R_100", Timeframe.M5) == 2
        assert store.count("R_50", Timeframe.M5) == 0


class TestValidate:
    def test_empty_cache_is_valid(self, store: CandleStore) -> None:
        result = store.validate("R_100", Timeframe.M5)
        assert result.is_valid is True
        assert result.candle_count == 0

    def test_clean_gap_free_series_is_valid(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(i * 5) for i in range(10)])
        result = store.validate("R_100", Timeframe.M5)
        assert result.is_valid is True
        assert result.issues == []

    def test_detects_gap(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0), _candle(5), _candle(50)])
        result = store.validate("R_100", Timeframe.M5)
        assert result.is_valid is False
        assert any("gap" in issue for issue in result.issues)

    def test_detects_inverted_high_low(self, store: CandleStore) -> None:
        bad = Candle(time=_BASE_TIME, open=100, high=90, low=110, close=100, volume=1)
        store.save_candles("R_100", Timeframe.M5, [bad])
        result = store.validate("R_100", Timeframe.M5)
        assert result.is_valid is False
        assert any("high < low" in issue for issue in result.issues)


class TestClear:
    def test_clears_specific_symbol_timeframe(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0)])
        store.save_candles("R_50", Timeframe.M5, [_candle(0)])
        deleted = store.clear("R_100", Timeframe.M5)
        assert deleted == 1
        assert store.count("R_100", Timeframe.M5) == 0
        assert store.count("R_50", Timeframe.M5) == 1

    def test_clears_everything_when_unscoped(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0)])
        store.save_candles("R_50", Timeframe.M5, [_candle(0)])
        store.clear()
        assert store.count("R_100", Timeframe.M5) == 0
        assert store.count("R_50", Timeframe.M5) == 0


class TestCacheErrorHandling:
    def test_db_path_under_a_file_raises_cache_error(self) -> None:
        # A parent path that is itself a file (not a directory) makes
        # mkdir()/sqlite3.connect() fail deterministically, regardless
        # of the running user's filesystem permissions.
        with tempfile.NamedTemporaryFile() as blocking_file:
            bad_path = Path(blocking_file.name) / "subdir" / "candles.db"
            with pytest.raises(CacheError):
                CandleStore(db_path=bad_path)


class TestFindGaps:
    def test_no_gaps_in_evenly_spaced_series(self) -> None:
        candles = [_candle(i * 5) for i in range(5)]
        assert find_gaps(candles, step_seconds=300) == []

    def test_detects_single_gap(self) -> None:
        candles = [_candle(0), _candle(5), _candle(50)]
        gaps = find_gaps(candles, step_seconds=300)
        assert gaps == [(_BASE_TIME + timedelta(minutes=5), _BASE_TIME + timedelta(minutes=50))]

    def test_detects_multiple_gaps(self) -> None:
        candles = [_candle(0), _candle(50), _candle(100)]
        gaps = find_gaps(candles, step_seconds=300)
        assert len(gaps) == 2

    def test_minor_jitter_within_tolerance_is_not_a_gap(self) -> None:
        # 300s expected step; a candle 6 minutes later (360s) is within
        # the 1.5x tolerance (450s) and should not be flagged.
        candles = [_candle(0), _candle(6)]
        assert find_gaps(candles, step_seconds=300) == []

    def test_empty_or_single_candle_has_no_gaps(self) -> None:
        assert find_gaps([], step_seconds=300) == []
        assert find_gaps([_candle(0)], step_seconds=300) == []
