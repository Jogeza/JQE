"""CLI runner for regime and directional diagnostics across frozen datasets."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import sys
from typing import Any

from backtesting.backtest import run_backtest
from backtesting.models import BacktestExecutionAssumptions, BacktestResult
from broker.types import Timeframe
from data.storage import CandleStore
from research.regime_diagnostics import (
    aggregate_window_diagnostics,
    evaluate_hypothesis_1_directional_asymmetry,
    evaluate_hypothesis_2_regime_drift,
)
from tools.acquire_diagnostic_windows import WINDOWS

ALL_WINDOWS = (
    ("BASELINE", datetime(2026, 8, 24, tzinfo=timezone.utc), datetime(2026, 8, 31, tzinfo=timezone.utc)),
    *WINDOWS,
)

SCENARIOS = {
    "IDEALIZED_ZERO_COST": BacktestExecutionAssumptions(),
    "CONSERVATIVE_SIMULATION_COST": BacktestExecutionAssumptions(spread=0.50, slippage=0.25, fee_per_trade=0.0),
}


async def run_diagnostics() -> dict[str, Any]:
    store = CandleStore(read_only=True)
    window_results: dict[str, dict[str, BacktestResult]] = {}

    for window_name, start, end in ALL_WINDOWS:
        candles = store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
        window_results[window_name] = {}
        for scen_name, execution in SCENARIOS.items():
            run = await run_backtest(
                symbol="XAUUSD", timeframe=Timeframe.M15, dataset=candles,
                provider="deriv", starting_balance=50.0, execution_assumptions=execution,
            )
            assert run.result is not None
            window_results[window_name][scen_name] = run.result

    diagnostics = aggregate_window_diagnostics(window_results)
    h1 = evaluate_hypothesis_1_directional_asymmetry(window_results)
    h2 = evaluate_hypothesis_2_regime_drift(window_results)

    return {
        "diagnostics": diagnostics,
        "hypotheses": {
            "hypothesis_1": h1,
            "hypothesis_2": h2,
        },
    }


def main() -> None:
    results = asyncio.run(run_diagnostics())
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
