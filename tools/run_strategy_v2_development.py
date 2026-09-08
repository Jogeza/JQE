"""Run the pre-registered Strategy V2 development study only.

This command intentionally does not load OOS_4 or OOS_5. Holdout validation
requires a separate, explicit final-validation command after the development
gate has been passed and a single hypothesis has been selected.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker.types import Timeframe
from data.storage import CandleStore
from research.strategy_v2 import (
    CONSERVATIVE_COST, DEVELOPMENT_WINDOWS, HYPOTHESES, ZERO_COST,
    development_registry, development_report, evaluate_hypothesis,
    holdout_registry, deterministic_hash,
)


async def main() -> None:
    store = CandleStore(read_only=True)
    datasets = {}
    for window_id, start, end in DEVELOPMENT_WINDOWS:
        datasets[window_id] = store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
    development_registry(datasets)
    results = {hypothesis.hypothesis_id: {} for hypothesis in HYPOTHESES}
    for hypothesis in HYPOTHESES:
        for window_id, candles in datasets.items():
            results[hypothesis.hypothesis_id][window_id] = {
                "IDEALIZED_ZERO_COST": await evaluate_hypothesis(hypothesis, candles, execution=ZERO_COST),
                "CONSERVATIVE_SIMULATION_COST": await evaluate_hypothesis(hypothesis, candles, execution=CONSERVATIVE_COST),
            }
    hypothesis_payload = [h.to_dict() for h in HYPOTHESES]
    hypothesis_artifact = {"hypotheses": hypothesis_payload, "artifact_hash": deterministic_hash(hypothesis_payload)}
    Path("data/research/strategy_v2_hypotheses.json").write_text(
        json.dumps(hypothesis_artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    report = {"hypotheses": hypothesis_payload, "holdout_registry": holdout_registry(),
              "development_registry": development_registry(datasets), "results": development_report(results)}
    output = Path("data/research/strategy_v2_development_results.json")
    payload = {**report, "report_hash": deterministic_hash(report)}
    output.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())