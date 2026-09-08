"""Run and persist both cost scenarios over all frozen windows twice."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone

from backtesting.backtest import run_backtest
from backtesting.models import BacktestExecutionAssumptions
from broker.types import Timeframe
from config import settings
from data.storage import CandleStore
from research.experiments import ExperimentCatalog, ResearchPartition, build_experiment_record
from research.performance_experiments import performance_metrics
from tools.acquire_diagnostic_windows import WINDOWS

ALL_WINDOWS = (("BASELINE", datetime(2026,8,24,tzinfo=timezone.utc), datetime(2026,8,31,tzinfo=timezone.utc)), *WINDOWS)
SCENARIOS = {
    "IDEALIZED_ZERO_COST": BacktestExecutionAssumptions(),
    "CONSERVATIVE_SIMULATION_COST": BacktestExecutionAssumptions(spread=0.50, slippage=0.25, fee_per_trade=0.0),
}


async def main() -> None:
    store, catalog, timeframe, output = CandleStore(read_only=True), ExperimentCatalog(settings.research_experiment_path), Timeframe.M15, []
    for window, start, end in ALL_WINDOWS:
        candles = store.load_candles("XAUUSD", timeframe, start, end, provider="deriv")
        for scenario, execution in SCENARIOS.items():
            runs = [await run_backtest(symbol="XAUUSD", timeframe=timeframe, dataset=candles,
                provider="deriv", starting_balance=50.0, execution_assumptions=execution) for _ in range(2)]
            first, second = runs[0].result, runs[1].result
            assert first is not None and second is not None
            if first.result_hash != second.result_hash or first.to_dict() != second.to_dict():
                raise RuntimeError(f"Nondeterministic result: {window} {scenario}")
            metrics = performance_metrics(first)
            experiment_id = f"simulation-{window.lower().replace('_','-')}-{scenario.lower().replace('_','-')}-{first.result_hash[7:19]}"
            record = build_experiment_record(dataset_hash=first.dataset_hash,
                run_fingerprint=first.run_fingerprint, result_hash=first.result_hash,
                engine_version=first.engine_version, identity_schema_version=first.identity_schema_version,
                symbol="XAUUSD", timeframe="M15", partition=ResearchPartition.FULL,
                partition_first_candle=start, partition_last_candle=end,
                partition_candle_count=len(candles), strategy_name="jqe-canonical-strategy-v1",
                configuration={"execution_mode":"SIMULATION","starting_balance":{"amount":50.0,"currency":"USD"},
                    "signal_logic_version":"directional-momentum-v2","cost_scenario":scenario,
                    "strategy":first.strategy,"risk":asdict(first.risk),"execution":asdict(execution)},
                metrics=metrics, provenance={"provider":"deriv","provider_symbol":"frxXAUUSD",
                    "source":"Deriv public historical WebSocket","frozen_window":window},
                created_at=end, experiment_id=experiment_id)
            catalog.save(record)
            output.append({"window":window,"scenario":scenario,"experiment_id":experiment_id,
                "dataset_hash":first.dataset_hash,"result_hash":first.result_hash,"deterministic":True,
                "metrics":metrics})
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__": asyncio.run(main())
