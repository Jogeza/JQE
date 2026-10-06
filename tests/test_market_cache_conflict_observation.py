from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.service import ApplicationService
from broker.types import Candle, Timeframe
from core.exceptions import CacheError


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse', [False, True])
async def test_cache_conflict_preserves_history_and_validates_uncached_closed_bars(monkeypatch, reverse):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    candles = [Candle(time=now-timedelta(minutes=5*(30-i)), open=100, high=102,
                      low=99, close=101, volume=20, source='weltrade') for i in range(31)]
    if reverse:
        candles.reverse()
    source = MagicMock()
    source.get_candles = AsyncMock(return_value=candles)
    service = object.__new__(ApplicationService)
    service._pinned_market_batch = None
    service._market_data_source = None
    service._candle_store = MagicMock()
    service._candle_store.resolve_symbol_partition.return_value = 'FX Vol 20'
    service._candle_store.load_latest.return_value = []
    service._get_market_data_source = lambda: (source, 'BROKER')

    @asynccontextmanager
    async def connected(_source):
        yield _source
    service._connected_source = connected
    monkeypatch.setattr('api.service.HistoricalDataService.refresh_latest',
                        AsyncMock(side_effect=CacheError('Conflicting duplicate candle')))
    result, provider, status, cache = await service._get_market_candle_data('FX VOL 20', Timeframe.M5, 30)
    service._candle_store.save_candles.assert_not_called()
    if reverse:
        assert result == [] and status == 'UNAVAILABLE'
    else:
        assert len(result) == 30
        assert result[-1].time + timedelta(minutes=5) <= now
        assert (provider, status, cache) == ('BROKER', 'CURRENT', 'CACHE_WRITE_FAILED')
