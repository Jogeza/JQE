"""Run the authorized offline USD 50 simulation checkpoint twice."""
from __future__ import annotations

import asyncio
import json

from research.simulation_session import run_cached_simulation_experiment


async def main() -> None:
    first = await run_cached_simulation_experiment(starting_balance=50.0)
    second = await run_cached_simulation_experiment(starting_balance=50.0)
    result = first.result
    print(json.dumps({
        "experiment_id": first.experiment.experiment_id,
        "dataset_hash": result.dataset_hash,
        "result_hash": result.result_hash,
        "repeat_result_hash": second.result.result_hash,
        "deterministic": result.result_hash == second.result.result_hash,
        "metrics": dict(first.experiment.metrics),
        "symbol": result.symbol,
        "timeframe": result.timeframe.value,
        "dataset_start": result.dataset_start.isoformat(),
        "dataset_end": result.dataset_end.isoformat(),
        "candle_count": result.candle_count,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
