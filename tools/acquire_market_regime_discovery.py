"""Acquire pre-registered market-only discovery windows via public Deriv data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker.deriv_public_data import DerivPublicMarketData
from broker.types import Timeframe
from data.coverage import validate_historical_coverage
from data.historical import HistoricalDataService
from data.storage import CandleStore
from research.market_regime_corpus import candidate_windows


async def main() -> None:
    store = CandleStore()
    timeframe = Timeframe.M15
    async with DerivPublicMarketData() as source:
        service = HistoricalDataService(source, store)
        for name, start, end in candidate_windows():
            print(f"Acquiring {name}: {start.isoformat()} to {end.isoformat()}...")
            cursor = start
            while cursor <= end:
                chunk_end = min(cursor + timedelta(hours=23, minutes=45), end)
                await service.get_candles_range("XAUUSD", timeframe, cursor, chunk_end,
                    count=int((chunk_end - cursor).total_seconds() // 900) + 32,
                    provider="deriv", source_symbol="frxXAUUSD")
                cached = store.load_candles("XAUUSD", timeframe, cursor, chunk_end, provider="deriv")
                coverage = validate_historical_coverage(cached, provider="deriv", canonical_symbol="XAUUSD",
                    provider_symbol="frxXAUUSD", timeframe=timeframe, start=cursor, end=chunk_end)
                if coverage.missing_count or coverage.unexpected_returned_count:
                    raise RuntimeError(f"Calendar mismatch {name} {cursor.date()}: {coverage}")
                cursor = chunk_end + timedelta(minutes=15)
                await asyncio.sleep(0.1)
    print(json.dumps({"windows": [name for name, _, _ in candidate_windows()], "public_data_only": True}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())