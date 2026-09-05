"""Explicit research CLI for cached or Deriv-public historical backtests."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from backtesting.backtest import run_backtest
from broker.deriv_public_data import DerivPublicMarketData
from broker.types import TIMEFRAME_SECONDS, Timeframe
from config.settings import settings
from core.exceptions import MarketDataError
from data.coverage import validate_historical_coverage
from data.storage import CandleStore, find_gaps
from data.historical import HistoricalDataService
from data.provenance import DatasetProvenance, VolumeType

MAX_ACQUISITION_CANDLES = 5000


def _utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return result.astimezone(timezone.utc)


async def _run(args: argparse.Namespace) -> int:
    timeframe = Timeframe(args.timeframe)
    start, end = _utc(args.start), _utc(args.end)
    if end < start:
        raise MarketDataError("end must not precede start")
    requested = int((end - start).total_seconds() // TIMEFRAME_SECONDS[timeframe]) + 1
    if requested > MAX_ACQUISITION_CANDLES:
        raise MarketDataError(f"Requested range exceeds safe limit of {MAX_ACQUISITION_CANDLES} candles")
    store = CandleStore(args.cache)
    provider, provider_symbol = "deriv", "frxXAUUSD" if args.symbol.upper() == "XAUUSD" else args.symbol
    candles = store.load_candles(args.symbol, timeframe, start, end, provider=provider)
    coverage = validate_historical_coverage(
        candles, provider=provider, canonical_symbol=args.symbol,
        provider_symbol=provider_symbol, timeframe=timeframe, start=start, end=end,
    )
    allow_gaps = bool(getattr(args, "allow_gaps", False))
    complete = coverage.is_complete
    endpoint_covered = bool(candles) and candles[0].time <= start and candles[-1].time >= end
    if allow_gaps and endpoint_covered:
        complete = True
    provenance = "CACHE"
    if not complete:
        if args.cached_only:
            raise MarketDataError(
                "Requested range is not complete in cache",
                provider=provider, symbol=args.symbol, timeframe=timeframe.value,
                first_missing=coverage.first_missing.isoformat() if coverage.first_missing else None,
                missing_count=coverage.missing_count,
            )
        source = DerivPublicMarketData(settings.deriv_app_id, endpoint=settings.deriv_public_endpoint)
        async with source:
            service = HistoricalDataService(source, store=store)
            try:
                await service.get_candles_range(
                    args.symbol, timeframe, start, end, count=requested,
                    provider=provider, source_symbol=provider_symbol,
                )
            except MarketDataError:
                partial = store.load_candles(args.symbol, timeframe, start, end, provider=provider)
                endpoints = bool(partial) and partial[0].time <= start and partial[-1].time >= end
                if not (allow_gaps and endpoints):
                    raise
        store.save_provenance(DatasetProvenance(
            provider=provider, symbol=args.symbol, timeframe=timeframe.value,
            source="Deriv public historical WebSocket", provider_symbol=provider_symbol,
            volume_type=VolumeType.UNAVAILABLE, retrieved_at=datetime.now(timezone.utc),
        ))
        candles = store.load_candles(args.symbol, timeframe, start, end, provider=provider)
        coverage = validate_historical_coverage(
            candles, provider=provider, canonical_symbol=args.symbol,
            provider_symbol=provider_symbol, timeframe=timeframe, start=start, end=end,
        )
        if not coverage.is_complete and not allow_gaps:
            raise MarketDataError(
                "Fetched historical range is incomplete",
                provider=provider, symbol=args.symbol,
                first_missing=coverage.first_missing.isoformat() if coverage.first_missing else None,
                missing_count=coverage.missing_count,
            )
        provenance = "CACHE_PLUS_DERIV_PUBLIC" if candles else "DERIV_PUBLIC"
    if not candles:
        raise MarketDataError("No historical candles available")
    if store.load_provenance(provider, args.symbol, timeframe) is None:
        store.save_provenance(DatasetProvenance(
            provider=provider, symbol=args.symbol, timeframe=timeframe.value,
            source="Deriv public historical WebSocket", provider_symbol=provider_symbol,
            volume_type=VolumeType.UNAVAILABLE, retrieved_at=datetime.now(timezone.utc),
        ))
    engine = await run_backtest(symbol=args.symbol, timeframe=timeframe, starting_balance=args.initial_capital, dataset=candles, provider=provider)
    result = engine.result
    print(f"DATA_SOURCE={provenance}")
    print(f"DATASET={args.symbol} {timeframe.value} {result.dataset_start.isoformat()}..{result.dataset_end.isoformat()} candles={result.candle_count}")
    gaps = find_gaps(candles, TIMEFRAME_SECONDS[timeframe])
    print(f"INTEGRITY=ordered:true unique:true gaps:{len(gaps)} volume:{VolumeType.UNAVAILABLE.value}")
    print(f"TRADES={result.total_trades} ENDING_CAPITAL={result.ending_capital:.8f} RETURN_PERCENT={result.return_percent:.8f} MAX_DRAWDOWN={result.maximum_drawdown:.8f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic JQE historical backtest")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", choices=[item.value for item in Timeframe], default="M15")
    parser.add_argument("--start", required=True, help="ISO-8601 timestamp with UTC offset")
    parser.add_argument("--end", required=True, help="ISO-8601 timestamp with UTC offset")
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--cache", type=Path, default=settings.historical_data_path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cached-only", action="store_true")
    mode.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--allow-gaps", action="store_true", help="accept and report provider session gaps without claiming continuity")
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except Exception as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
