"""Acquire untouched frozen validation windows OOS_4 and OOS_5 via Deriv public data."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from broker.deriv_public_data import DerivPublicMarketData
from broker.types import Timeframe
from data.coverage import validate_historical_coverage
from data.dataset import canonical_dataset_hash
from data.historical import HistoricalDataService
from data.provenance import DatasetProvenance, VolumeType
from data.storage import CandleStore
from core.exceptions import MarketDataError

VALIDATION_WINDOWS = (
    ("OOS_4", datetime(2026, 1, 15, tzinfo=timezone.utc), datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ("OOS_5", datetime(2025, 11, 1, tzinfo=timezone.utc), datetime(2025, 12, 15, tzinfo=timezone.utc)),
)


async def main() -> None:
    store = CandleStore()
    timeframe = Timeframe.M15
    print("Connecting to Deriv unauthenticated public market-data source...")
    async with DerivPublicMarketData() as source:
        service = HistoricalDataService(source, store)
        for name, start, end in VALIDATION_WINDOWS:
            print(f"Acquiring {name}: {start.isoformat()} to {end.isoformat()}...")
            cursor = start
            while cursor <= end:
                # Keep requests to one UTC day.  Deriv can return an internal
                # hole for multi-day requests even when both range endpoints
                # are present; smaller requests allow each segment to be
                # independently verified and retried.
                chunk_end = min(cursor + timedelta(hours=23, minutes=45), end)
                raw_slots = int((chunk_end - cursor).total_seconds() // 900) + 1
                # Deriv counts returned open candles, not UTC time slots.  A
                # cushion covers daily breaks, weekend/session boundaries, and
                # the API's inclusive end behavior so the range can be checked
                # fail-closed after filtering to [cursor, chunk_end].
                count = raw_slots + 32
                try:
                    await service.get_candles_range(
                        "XAUUSD", timeframe, cursor, chunk_end,
                        count=count, provider="deriv", source_symbol="frxXAUUSD",
                    )
                except MarketDataError:
                    cached = store.load_candles(
                        "XAUUSD", timeframe, cursor, chunk_end, provider="deriv"
                    )
                    coverage = validate_historical_coverage(
                        cached, provider="deriv", canonical_symbol="XAUUSD",
                        provider_symbol="frxXAUUSD", timeframe=timeframe,
                        start=cursor, end=chunk_end,
                    )
                    present = {candle.time for candle in cached}
                    missing_times = []
                    probe = cursor
                    while probe <= chunk_end:
                        if probe not in present:
                            # Only report gaps that the authoritative policy
                            # considers expected; maintenance/weekend buckets
                            # are intentionally omitted.
                            probe_coverage = validate_historical_coverage(
                                cached, provider="deriv", canonical_symbol="XAUUSD",
                                provider_symbol="frxXAUUSD", timeframe=timeframe,
                                start=probe, end=probe,
                            )
                            if probe_coverage.expected_count:
                                missing_times.append(probe.isoformat())
                        probe += timedelta(minutes=15)
                    print(
                        "Acquisition diagnostics: "
                        f"window={name}, chunk_start={cursor.isoformat()}, "
                        f"chunk_end={chunk_end.isoformat()}, returned={len(cached)}, "
                        f"expected={coverage.expected_count}, "
                        f"missing={coverage.missing_count}, "
                        f"first_missing={coverage.first_missing.isoformat() if coverage.first_missing else None}, "
                        f"first_returned={cached[0].time.isoformat() if cached else None}, "
                        f"last_returned={cached[-1].time.isoformat() if cached else None}, "
                        f"missing_timestamps={missing_times}"
                    )
                    raise
                cursor = chunk_end + timedelta(minutes=15)
                # Polite pacing between chunk queries
                await asyncio.sleep(0.1)

    store.save_provenance(DatasetProvenance(
        provider="deriv", symbol="XAUUSD", timeframe="M15",
        source="Deriv public historical WebSocket", provider_symbol="frxXAUUSD",
        volume_type=VolumeType.UNAVAILABLE, retrieved_at=datetime.now(timezone.utc),
    ))

    output = []
    for name, start, end in VALIDATION_WINDOWS:
        candles = store.load_candles("XAUUSD", timeframe, start, end, provider="deriv")
        coverage = validate_historical_coverage(
            candles, provider="deriv",
            canonical_symbol="XAUUSD", provider_symbol="frxXAUUSD", timeframe=timeframe,
            start=start, end=end,
        )
        output.append({
            "name": name,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "candles": len(candles),
            "missing_count": coverage.missing_count,
            "coverage_complete": coverage.is_complete,
            "dataset_hash": canonical_dataset_hash(candles, symbol="XAUUSD", timeframe=timeframe) if candles else None,
        })
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
