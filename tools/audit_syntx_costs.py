"""Cost-aware comparison of cached Weltrade SyntX datasets.

Read-only. Loads each cached dataset from data/historical.sqlite3 and replays it
through the canonical BacktestEngine at several microstructure cost levels, so a
zero-cost result can be separated from one that survives realistic spread and
adverse slippage.

Costs are expressed as fractions of the candle ATR because the terminal's quoted
spread, tick value and commission are not cached anywhere in this repository.
These are therefore sensitivity scenarios, not measured Weltrade costs.

Sample sizes here are tiny (cached history is hours, not months). A positive
expectancy at this size is not evidence of an edge.
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path

from backtesting.backtest import run_backtest
from backtesting.models import BacktestExecutionAssumptions
from analytics.performance import calculate_performance
from broker.types import Timeframe
from config.settings import settings
from data.storage import CandleStore
from core.logging_config import configure_logging

SYNTX_PREFIXES = ("FX VOL", "SFX VOL", "PAINX", "MAX PAINX")

SCENARIOS = {
    "zero_cost": BacktestExecutionAssumptions(),
    "realistic_atr10": BacktestExecutionAssumptions(spread_atr_fraction=0.10, adverse_slippage_atr_fraction=0.10),
    "stressed_atr15_20": BacktestExecutionAssumptions(spread_atr_fraction=0.15, adverse_slippage_atr_fraction=0.20),
}


def cached_datasets(db: Path, provider: str, timeframes: list[str], min_bars: int) -> list[tuple[str, str, int]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT symbol, timeframe, COUNT(*) FROM candles WHERE provider = ? GROUP BY symbol, timeframe",
            (provider,),
        ).fetchall()
    finally:
        con.close()
    out = []
    for symbol, timeframe, bars in rows:
        if str(timeframe) not in timeframes or int(bars) < min_bars:
            continue
        if not str(symbol).upper().startswith(SYNTX_PREFIXES):
            continue
        out.append((str(symbol), str(timeframe), int(bars)))
    return sorted(out)


async def evaluate(store: CandleStore, symbol: str, timeframe_value: str, provider: str) -> list[dict]:
    timeframe = Timeframe(timeframe_value)
    candles = store.load_candles(symbol, timeframe, provider=provider)
    if len(candles) < 200:
        return []
    rows = []
    for name, assumptions in SCENARIOS.items():
        engine = await run_backtest(
            symbol=symbol, timeframe=timeframe, starting_balance=10000.0,
            dataset=candles, provider=provider, execution_assumptions=assumptions,
        )
        stats = calculate_performance(engine.trades, engine.equity_curve) if engine.trades else {}
        rows.append({
            "symbol": symbol, "timeframe": timeframe_value, "scenario": name,
            "candles": len(candles), "trades": len(engine.trades),
            "win_rate": stats.get("Win Rate %", 0.0), "profit_factor": stats.get("Profit Factor", 0.0),
            "expectancy": stats.get("Expectancy", 0.0),
            "net": stats.get("Net P&L", engine.result.ending_capital - 10000.0),
            "return_pct": engine.result.return_percent, "max_dd": stats.get("Maximum Drawdown", 0.0),
        })
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(settings.historical_data_path))
    parser.add_argument("--provider", default="weltrade")
    parser.add_argument("--timeframes", default="M1,M5")
    parser.add_argument("--min-bars", type=int, default=200)
    args = parser.parse_args()

    configure_logging()
    db = Path(args.db)
    store = CandleStore(db, read_only=True)
    timeframes = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
    datasets = cached_datasets(db, args.provider, timeframes, args.min_bars)
    print(f"COSTAUDIT|datasets={len(datasets)} scenarios={len(SCENARIOS)}")
    for symbol, timeframe, bars in datasets:
        for row in await evaluate(store, symbol, timeframe, args.provider):
            print(
                f"COSTAUDIT|{row['symbol']:<14}|{row['timeframe']:<3}|{row['scenario']:<16}"
                f"|bars={row['candles']:<5}|trades={row['trades']:<4}|win%={row['win_rate']:<6.1f}"
                f"|pf={row['profit_factor']:<6.2f}|exp={row['expectancy']:<9.2f}"
                f"|net={row['net']:<10.2f}|ret%={row['return_pct']:<7.3f}|maxDD={row['max_dd']:.2f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
