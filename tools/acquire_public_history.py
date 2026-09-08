"""Acquire a fixed 90-day XAUUSD M15 dataset through public Deriv data only."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from broker.deriv_public_data import DerivPublicMarketData
from broker.types import Timeframe
from data.coverage import validate_historical_coverage
from data.historical import HistoricalDataService
from data.provenance import DatasetProvenance, VolumeType
from data.storage import CandleStore
from research.markets import adapt_active_symbols


async def main() -> None:
    timeframe = Timeframe.M15
    # The repository's XAUUSD session policy is explicitly verified for this
    # fixed interval. The attempted 90-day target crossed an unmodelled holiday
    # early-close and therefore failed closed before any strategy run.
    start = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
    store = CandleStore()
    async with DerivPublicMarketData() as source:
        instruments = adapt_active_symbols(await source.get_active_symbols())
        instrument = next((item for item in instruments if item.provider_symbol == "frxXAUUSD"), None)
        if instrument is None or instrument.is_trading_suspended or timeframe not in instrument.timeframes:
            raise RuntimeError("Public Deriv catalogue does not support active frxXAUUSD M15")
        service = HistoricalDataService(source, store)
        cursor = start
        while cursor <= end:
            # The current public service truncates requests around 500 candles.
            # Four-day chunks are at most 384 M15 buckets and preserve the
            # preselected overall 90-day range.
            chunk_end = min(cursor + timedelta(days=3, hours=23, minutes=45), end)
            count = int((chunk_end - cursor).total_seconds() // 900) + 1
            await service.get_candles_range(
                "XAUUSD", timeframe, cursor, chunk_end, count=count,
                provider="deriv", source_symbol="frxXAUUSD",
            )
            cursor = chunk_end + timedelta(minutes=15)
    store.save_provenance(DatasetProvenance(
        provider="deriv", symbol="XAUUSD", timeframe="M15",
        source="Deriv public historical WebSocket", provider_symbol="frxXAUUSD",
        volume_type=VolumeType.UNAVAILABLE, retrieved_at=datetime.now(timezone.utc),
    ))
    candles = store.load_candles("XAUUSD", timeframe, start, end, provider="deriv")
    coverage = validate_historical_coverage(
        candles, provider="deriv", canonical_symbol="XAUUSD",
        provider_symbol="frxXAUUSD", timeframe=timeframe, start=start, end=end,
    )
    summary = next(item for item in store.list_cached_datasets("deriv") if item.canonical_symbol == "XAUUSD" and item.timeframe == "M15")
    print(json.dumps({
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "actual_start": candles[0].time.isoformat(), "actual_end": candles[-1].time.isoformat(),
        "candle_count": len(candles), "coverage_complete": coverage.is_complete,
        "missing_expected_buckets": coverage.missing_count,
        "legitimate_closed_buckets": coverage.legitimate_closed_count,
        "dataset_hash": summary.dataset_identity, "provider": summary.provider,
        "canonical_symbol": summary.canonical_symbol, "provider_symbol": summary.provider_symbol,
        "timeframe": summary.timeframe, "volume_type": summary.volume_type.value,
        "volume_source": summary.volume_source, "catalog_dataset_count": len(store.list_cached_datasets()),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
