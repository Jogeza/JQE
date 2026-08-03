"""Tests for data.historical.HistoricalDataService."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from broker.types import Candle, Timeframe
from data.historical import HistoricalDataService
from data.storage import CandleStore

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


def _mock_gateway(candles: list[Candle]) -> MagicMock:
    gateway = MagicMock()
    gateway.get_candles = AsyncMock(return_value=candles)
    return gateway


class TestGetCandlesEmptyCache:
    async def test_downloads_full_window_when_nothing_cached(self, store: CandleStore) -> None:
        fetched = [_candle(i * 5) for i in range(10)]
        gateway = _mock_gateway(fetched)
        service = HistoricalDataService(gateway, store=store)

        result = await service.get_candles("R_100", Timeframe.M5, 10)

        gateway.get_candles.assert_awaited_once_with("R_100", Timeframe.M5, 10)
        assert len(result) == 10
        assert store.count("R_100", Timeframe.M5) == 10


class TestGetCandlesIncrementalUpdate:
    async def test_second_call_only_downloads_the_gap_not_a_full_redownload(
        self, store: CandleStore
    ) -> None:
        # Cache ending 20 minutes ago (a real but small staleness gap),
        # not the fixed 2024 fixture time — the point of this test is
        # to measure how many candles the incremental sync requests,
        # so the gap needs to be realistically small.
        now = datetime.now(timezone.utc)
        cached = [
            Candle(
                time=now - timedelta(minutes=20 + 5 * i),
                open=1,
                high=2,
                low=0.5,
                close=1.5,
                volume=1,
            )
            for i in range(10, 0, -1)
        ]
        store.save_candles("R_100", Timeframe.M5, cached)

        fresh_candle = Candle(time=now, open=1, high=2, low=0.5, close=1.5, volume=1)
        gateway = _mock_gateway([fresh_candle])
        service = HistoricalDataService(gateway, store=store)

        # fill_gaps=False: this test isolates the incremental-download
        # count specifically. The 20-minute hole this fixture leaves
        # between the old cache and the single fresh candle is a real
        # gap and would trigger a second, separate gateway call if gap
        # filling ran too — covered by TestFillGaps instead.
        await service.get_candles("R_100", Timeframe.M5, 10, fill_gaps=False)

        gateway.get_candles.assert_awaited_once()
        requested_count = gateway.get_candles.call_args[0][2]
        # ~20 minutes of staleness at a 5-minute step is ~4-5 candles —
        # far fewer than redownloading the full `count` window would
        # need if the cache held e.g. thousands of candles already.
        assert requested_count <= 6


class TestGetCandlesFreshCache:
    async def test_no_download_when_cache_is_already_current(self, store: CandleStore) -> None:
        now = datetime.now(timezone.utc)
        recent_candles = [
            Candle(
                # Newest candle is 1 minute old — comfortably inside the
                # one-candle-width (5 minute) freshness tolerance, with
                # margin for the small amount of real time this test
                # takes to execute.
                time=now - timedelta(minutes=1 + 5 * i),
                open=1,
                high=2,
                low=0.5,
                close=1.5,
                volume=1,
            )
            for i in range(9, -1, -1)
        ]
        store.save_candles("R_100", Timeframe.M5, recent_candles)
        gateway = _mock_gateway([])
        service = HistoricalDataService(gateway, store=store)

        result = await service.get_candles("R_100", Timeframe.M5, 10, fill_gaps=False)

        gateway.get_candles.assert_not_awaited()
        assert len(result) == 10


class TestFillGaps:
    async def test_fills_a_detected_gap(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0), _candle(5), _candle(50)])
        gap_filler = [_candle(m) for m in range(10, 50, 5)]
        gateway = _mock_gateway(gap_filler)
        service = HistoricalDataService(gateway, store=store)

        filled = await service.fill_gaps("R_100", Timeframe.M5)

        assert filled == 1
        assert store.validate("R_100", Timeframe.M5).is_valid is True

    async def test_returns_zero_when_no_gaps(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(i * 5) for i in range(10)])
        gateway = _mock_gateway([])
        service = HistoricalDataService(gateway, store=store)

        filled = await service.fill_gaps("R_100", Timeframe.M5)

        assert filled == 0
        gateway.get_candles.assert_not_awaited()

    async def test_returns_zero_with_fewer_than_two_candles(self, store: CandleStore) -> None:
        store.save_candles("R_100", Timeframe.M5, [_candle(0)])
        gateway = _mock_gateway([])
        service = HistoricalDataService(gateway, store=store)

        assert await service.fill_gaps("R_100", Timeframe.M5) == 0

    async def test_get_candles_fills_gaps_by_default(self, store: CandleStore) -> None:
        now = datetime.now(timezone.utc)
        # Two clusters of candles with a deliberate 60-minute gap
        # between them; the cache already ends at "now", so no
        # separate recency download is needed — isolates this test to
        # gap-filling behavior specifically.
        older_cluster = [now - timedelta(minutes=m) for m in (100, 95, 90, 85, 80)]
        newer_cluster = [now - timedelta(minutes=m) for m in (20, 15, 10, 5, 0)]
        store.save_candles(
            "R_100",
            Timeframe.M5,
            [
                Candle(time=t, open=1, high=1, low=1, close=1, volume=1)
                for t in older_cluster + newer_cluster
            ],
        )

        gap_filler = [
            Candle(time=now - timedelta(minutes=m), open=1, high=1, low=1, close=1, volume=1)
            for m in (75, 70, 65, 60, 55, 50, 45, 40, 35, 30, 25)
        ]
        gateway = _mock_gateway(gap_filler)
        service = HistoricalDataService(gateway, store=store)

        await service.get_candles("R_100", Timeframe.M5, 100, fill_gaps=True)

        assert store.validate("R_100", Timeframe.M5).is_valid is True

    async def test_fill_gaps_false_leaves_gap_unfilled(self, store: CandleStore) -> None:
        now = datetime.now(timezone.utc)
        older_cluster = [now - timedelta(minutes=m) for m in (100, 95, 90, 85, 80)]
        newer_cluster = [now - timedelta(minutes=m) for m in (20, 15, 10, 5, 0)]
        store.save_candles(
            "R_100",
            Timeframe.M5,
            [
                Candle(time=t, open=1, high=1, low=1, close=1, volume=1)
                for t in older_cluster + newer_cluster
            ],
        )
        gateway = _mock_gateway([])
        service = HistoricalDataService(gateway, store=store)

        await service.get_candles("R_100", Timeframe.M5, 100, fill_gaps=False)

        assert store.validate("R_100", Timeframe.M5).is_valid is False


class TestSync:
    async def test_report_reflects_downloads_and_validation(self, store: CandleStore) -> None:
        fetched = [_candle(i * 5) for i in range(10)]
        gateway = _mock_gateway(fetched)
        service = HistoricalDataService(gateway, store=store)

        report = await service.sync("R_100", Timeframe.M5, 10)

        assert report.symbol == "R_100"
        assert report.timeframe == "M5"
        assert report.candle_count == 10
        assert report.is_valid is True
        assert report.candles_downloaded == 10
