"""Acquire predeclared, non-overlapping XAUUSD M15 diagnostic windows."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from broker.deriv_public_data import DerivPublicMarketData
from broker.types import Timeframe
from data.coverage import validate_historical_coverage
from data.dataset import canonical_dataset_hash
from data.historical import HistoricalDataService
from data.provenance import DatasetProvenance, VolumeType
from data.storage import CandleStore

WINDOWS = (
    ("OOS_1", datetime(2026, 4, 6, tzinfo=timezone.utc), datetime(2026, 5, 5, tzinfo=timezone.utc)),
    ("OOS_2", datetime(2026, 5, 26, tzinfo=timezone.utc), datetime(2026, 6, 18, tzinfo=timezone.utc)),
    ("OOS_3", datetime(2026, 7, 6, tzinfo=timezone.utc), datetime(2026, 8, 3, tzinfo=timezone.utc)),
)


async def main() -> None:
    store, timeframe = CandleStore(), Timeframe.M15
    async with DerivPublicMarketData() as source:
        service = HistoricalDataService(source, store)
        for _, start, end in WINDOWS:
            cursor = start
            while cursor <= end:
                chunk_end = min(cursor + timedelta(days=3, hours=23, minutes=45), end)
                count = int((chunk_end-cursor).total_seconds()//900)+1
                await service.get_candles_range("XAUUSD", timeframe, cursor, chunk_end,
                    count=count, provider="deriv", source_symbol="frxXAUUSD")
                cursor = chunk_end + timedelta(minutes=15)
    store.save_provenance(DatasetProvenance("deriv", "XAUUSD", "M15",
        "Deriv public historical WebSocket", "frxXAUUSD", VolumeType.UNAVAILABLE,
        datetime.now(timezone.utc)))
    output = []
    for name, start, end in WINDOWS:
        candles = store.load_candles("XAUUSD", timeframe, start, end, provider="deriv")
        coverage = validate_historical_coverage(candles, provider="deriv",
            canonical_symbol="XAUUSD", provider_symbol="frxXAUUSD", timeframe=timeframe,
            start=start, end=end)
        output.append({"name":name,"start":start.isoformat(),"end":end.isoformat(),
            "candles":len(candles),"gaps":coverage.missing_count,
            "coverage_complete":coverage.is_complete,
            "dataset_hash":canonical_dataset_hash(candles,symbol="XAUUSD",timeframe=timeframe)})
    print(json.dumps(output, indent=2))


if __name__ == "__main__": asyncio.run(main())
