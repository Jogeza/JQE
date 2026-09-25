"""Read-only MT5 history acquisition for broker-order-free shadow replay."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from broker.factory import get_gateway
from broker.mt5_gateway import _mt5_timeframe
from broker.types import Timeframe
from config.settings import get_settings
from data.watchlist import WatchlistStore
from research.shadow_history import ShadowHistoryStore


def _key(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _catalogue() -> dict[str, Any]:
    return {_key(info.name): info for info in (mt5.symbols_get() or ())}


def _resolve(symbol: str, catalogue: dict[str, Any]) -> Any | None:
    info = catalogue.get(_key(symbol))
    if info is not None:
        return info
    if _key(symbol) == "r75":
        return catalogue.get(_key("Volatility 75 Index")) or catalogue.get(_key("R_75"))
    return None


def _fetch_max_rates(real_symbol: str, timeframe: Timeframe, chunk_size: int) -> list[Any]:
    """Page backward until MT5 returns no earlier bars.

    MT5 rejects very large ``copy_rates_from_pos`` counts on this terminal, so
    the request is bounded and paged by the oldest returned timestamp.
    """
    count = min(max(1, chunk_size), 10000)
    tf = _mt5_timeframe(timeframe)
    newest = mt5.copy_rates_from_pos(real_symbol, tf, 0, count)
    if newest is None or len(newest) == 0:
        return []
    collected = list(newest)
    while len(collected) >= count:
        oldest = min(int(row["time"]) for row in collected)
        end = datetime.fromtimestamp(oldest, tz=timezone.utc) - timedelta(seconds=1)
        older = mt5.copy_rates_from(real_symbol, tf, end, count)
        if older is None or len(older) == 0:
            break
        fresh = [row for row in older if int(row["time"]) < oldest]
        if not fresh:
            break
        collected = fresh + collected
        if len(fresh) < count:
            break
    return collected


async def run(path: Path, requested_count: int) -> dict[str, Any]:
    settings = get_settings()
    if settings.broker_execution_enabled:
        raise RuntimeError("history population refuses to run with broker execution enabled")
    store = ShadowHistoryStore(path)
    reports: list[dict[str, Any]] = []
    async with get_gateway(settings):
        catalogue = _catalogue()
        for pair in WatchlistStore(settings.watchlist_store_path).get_watch_pairs():
            info = _resolve(pair.symbol, catalogue)
            if info is None:
                reports.append({
                    "symbol": pair.symbol, "timeframe": pair.timeframe.value,
                    "provider_symbol": None, "bars_fetched": 0,
                    "reason": "terminal symbol unavailable",
                })
                continue
            raw = _fetch_max_rates(info.name, pair.timeframe, requested_count)
            fetched = len(raw)
            if raw:
                store.save_rates(
                    symbol=pair.symbol, provider_symbol=info.name,
                    timeframe=pair.timeframe, rates=raw,
                    point=float(getattr(info, "point", 0.0) or 0.0),
                )
            report = store.report_series(pair.symbol, pair.timeframe).to_dict()
            report["bars_fetched"] = fetched
            report["mt5_error"] = list(mt5.last_error())
            reports.append(report)
    result = {
        "source": "MT5_READ_ONLY",
        "requested_max_bars": requested_count,
        "series": reports,
        "total_bars": sum(int(item.get("bars", 0)) for item in reports),
        "total_gaps": sum(int(item.get("gap_count", 0)) for item in reports),
        "cache": str(path),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path("cache/shadow_mt5_rates.sqlite3"))
    parser.add_argument("--max-bars", type=int, default=100000)
    parser.add_argument("--report", type=Path, default=Path("state/shadow_history_report.json"))
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    if args.report_only:
        store = ShadowHistoryStore(args.cache)
        settings = get_settings()
        series = [
            store.report_series(pair.symbol, pair.timeframe).to_dict()
            for pair in WatchlistStore(settings.watchlist_store_path).get_watch_pairs()
        ]
        result = {
            "source": "LOCAL_SHADOW_CACHE",
            "requested_max_bars": args.max_bars,
            "series": series,
            "total_bars": sum(int(item["bars"]) for item in series),
            "total_gaps": sum(int(item["gap_count"]) for item in series),
            "cache": str(args.cache),
        }
    else:
        result = asyncio.run(run(args.cache, args.max_bars))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
