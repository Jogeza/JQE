"""Run the broker-order-free shadow resolver and cached-history replay."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from broker.factory import get_gateway
from broker.mt5_gateway import _mt5_timeframe
from broker.types import Timeframe
from config.settings import get_settings
from data.watchlist import WatchlistStore
from research.shadow_outcomes import (
    ShadowOutcome,
    ShadowOutcomeStore,
    ShadowTick,
    bars_from_mt5_rates,
    load_live_setup_specs,
    replay_shadow_bars,
    resolve_signal,
    ticks_from_mt5_rates,
)
from research.shadow_history import ShadowHistoryStore
from monitoring.forward_shadow_sampler import ForwardShadowSamplerStore, gap_aware_resolver_kwargs


def _replay_one_series(args: tuple[str, str, str]) -> tuple[dict[str, Any], list[ShadowOutcome]]:
    """Replay one series in an isolated worker; no broker module is needed."""
    cache_path, symbol, timeframe_value = args
    timeframe = Timeframe(timeframe_value)
    history_store = ShadowHistoryStore(cache_path)
    bars = history_store.load_bars(symbol, timeframe)
    specs, bars, reason = replay_shadow_bars(
        symbol=symbol, timeframe=timeframe, bars=bars,
    )
    item: dict[str, Any] = {
        "symbol": symbol, "timeframe": timeframe.value,
        "signals": len(specs), "cached_bars": len(bars),
    }
    if reason:
        item["reason"] = reason
    outcomes: list[ShadowOutcome] = []
    split_close = None
    if bars:
        split_index = max(1, int(len(bars) * 0.60))
        step = {Timeframe.M1: 60, Timeframe.M5: 300}[timeframe]
        split_close = bars[min(split_index, len(bars)) - 1].time + timedelta(seconds=step)
    for spec in specs:
        outcome = resolve_signal(spec, bars, source="replay")
        split = "exploration" if split_close is not None and spec.signal_close <= split_close else "holdout"
        outcomes.append(replace(outcome, split=split))
    return item, outcomes


def _key(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _symbol_catalogue() -> dict[str, Any]:
    return {_key(info.name): info for info in (mt5.symbols_get() or ())}


def _resolve_terminal_name(symbol: str, catalogue: dict[str, Any]) -> str | None:
    direct = catalogue.get(_key(symbol))
    if direct is not None:
        return direct.name
    if _key(symbol) == "r75":
        for candidate in ("Volatility 75 Index", "R_75"):
            if _key(candidate) in catalogue:
                return catalogue[_key(candidate)].name
    return None


def _rates(real_symbol: str, timeframe: Timeframe, count: int = 10000) -> Any:
    return mt5.copy_rates_from_pos(real_symbol, _mt5_timeframe(timeframe), 0, count)


def _m1_by_parent(real_symbol: str, point: float) -> dict[datetime, list[Any]]:
    raw = _rates(real_symbol, Timeframe.M1)
    if raw is None:
        return {}
    detail = bars_from_mt5_rates(raw, point=point, source="mt5-m1")
    result: dict[datetime, list[Any]] = defaultdict(list)
    for bar in detail:
        parent_epoch = (int(bar.time.timestamp()) // 300) * 300
        result[datetime.fromtimestamp(parent_epoch, tz=timezone.utc)].append(bar)
    return dict(result)


def _ticks_for_parent(real_symbol: str, parent: datetime, timeframe: Timeframe) -> list[ShadowTick]:
    start = parent
    end = parent + timedelta(seconds=300 if timeframe is Timeframe.M5 else 60)
    raw = mt5.copy_ticks_range(real_symbol, start, end, mt5.COPY_TICKS_ALL)
    return ticks_from_mt5_rates(raw if raw is not None else [])


async def run_live(store: ShadowOutcomeStore) -> dict[str, Any]:
    settings = get_settings()
    if settings.broker_execution_enabled:
        raise RuntimeError("shadow resolver refuses to run with broker execution enabled")
    live_specs = load_live_setup_specs(settings.dashboard_paper_store_path)
    sampler_specs = ForwardShadowSamplerStore(
        settings.dashboard_paper_store_path.parent / "forward_shadow.sqlite3"
    ).load_specs()
    specs = [(spec, "live") for spec in live_specs] + [
        (spec, "forward_ungated") for spec in sampler_specs
    ]
    first_pass: list[ShadowOutcome] = []
    ambiguous: list[tuple[Any, str, str, datetime]] = []
    async with get_gateway(settings):
        catalogue = _symbol_catalogue()
        series: dict[tuple[str, Timeframe], tuple[list[Any], dict[datetime, list[Any]]]] = {}
        for spec, _source in specs:
            key = (spec.symbol, spec.timeframe)
            if key in series:
                continue
            real = _resolve_terminal_name(spec.symbol, catalogue)
            if real is None:
                series[key] = ([], {})
                continue
            info = catalogue.get(_key(real))
            point = float(getattr(info, "point", 0.0) or 0.0)
            raw = _rates(real, spec.timeframe)
            bars = bars_from_mt5_rates(raw if raw is not None else [], point=point, source="mt5") if raw is not None else []
            detail = _m1_by_parent(real, point) if spec.timeframe is Timeframe.M5 else {}
            series[key] = (bars, detail)
        for spec, source in specs:
            bars, detail = series[(spec.symbol, spec.timeframe)]
            resolver_kwargs = gap_aware_resolver_kwargs(spec, bars) if source == "forward_ungated" else {}
            outcome = resolve_signal(
                spec, bars, detail_bars_by_parent=detail, source=source,
                **resolver_kwargs,
            )
            first_pass.append(outcome)
            if outcome.status == "AMBIGUOUS":
                ambiguous.append((spec, source, _resolve_terminal_name(spec.symbol, catalogue) or "", outcome.outcome_time or spec.signal_close, resolver_kwargs))
        final = list(first_pass)
        for index, (spec, source, real, parent, resolver_kwargs) in enumerate(ambiguous):
            if not real:
                continue
            ticks = _ticks_for_parent(real, parent, spec.timeframe)
            bars, detail = series[(spec.symbol, spec.timeframe)]
            outcome = resolve_signal(
                spec, bars, detail_bars_by_parent=detail,
                ticks_by_parent={parent: ticks}, source=source,
                **resolver_kwargs,
            )
            for position, candidate in enumerate(final):
                if candidate.signal_id == spec.signal_id:
                    final[position] = outcome
                    break
    store.upsert(final)
    return {
        "source": "live+forward_ungated",
        "live_signals_seen": len(live_specs),
        "forward_ungated_signals_seen": len(sampler_specs),
        "outcomes_written": len(final),
        "tick_drilldowns": len(ambiguous),
    }


def run_replay(store: ShadowOutcomeStore, *, workers: int = 4) -> dict[str, Any]:
    settings = get_settings()
    cache_path = settings.cache_dir / "shadow_mt5_rates.sqlite3"
    if not cache_path.is_file():
        return {"source": "replay", "series_seen": 0, "signals_seen": 0, "outcomes_written": 0, "coverage": [], "reason": "cache unavailable"}
    history_store = ShadowHistoryStore(cache_path)
    pairs = WatchlistStore(settings.watchlist_store_path).get_watch_pairs()
    args = [(str(cache_path), pair.symbol, pair.timeframe.value) for pair in pairs]
    coverage: list[dict[str, Any]] = []
    outcomes: list[ShadowOutcome] = []
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        for item, series_outcomes in pool.map(_replay_one_series, args):
            coverage.append(item)
            outcomes.extend(series_outcomes)
    store.upsert(outcomes)
    return {"source": "replay", "series_seen": len(coverage), "signals_seen": len(outcomes), "outcomes_written": len(outcomes), "coverage": coverage}


async def run(args: argparse.Namespace) -> dict[str, Any]:
    store = ShadowOutcomeStore(args.db)
    runs: list[dict[str, Any]] = []
    if args.source in {"live", "both"}:
        runs.append(await run_live(store))
    if args.source in {"replay", "both"}:
        runs.append(run_replay(store, workers=args.workers))
    report = store.report(source=None if args.source == "both" else args.source)
    result = {"runs": runs, "report": report}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("live", "replay", "both"), default="both")
    parser.add_argument("--db", type=Path, default=Path("state/shadow_outcomes.sqlite3"))
    parser.add_argument("--report", type=Path, default=Path("state/shadow_outcome_sample_report.json"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
