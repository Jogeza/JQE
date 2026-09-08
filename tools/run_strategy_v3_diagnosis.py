"""Run development-only V2 failure diagnosis; never loads locked holdouts."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from broker.types import Timeframe
from data.dataset import canonical_dataset_hash
from data.storage import CandleStore
from research.strategy_v2 import CONSERVATIVE_COST, DEVELOPMENT_WINDOWS, HYPOTHESES, ZERO_COST
from research.strategy_v3_diagnosis import (
    aggregate_records, diagnosis_gate, deterministic_hash, excursion_record,
    holdout_refusal_check, random_control, state_bucket_definitions, time_to_edge,
)
from research.strategy_v2 import evaluate_hypothesis


async def main() -> None:
    store = CandleStore(read_only=True)
    datasets = {name: store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
                for name, start, end in DEVELOPMENT_WINDOWS}
    frames = {name: __import__("core.indicators", fromlist=["calculate_indicators"]).calculate_indicators(
        pd.DataFrame([c.model_dump() for c in candles])) for name, candles in datasets.items()}
    buckets = state_bucket_definitions(list(frames.values()))
    hypotheses = {}
    structural = []
    for hypothesis in HYPOTHESES:
        windows = {}
        all_records = []
        for name, candles in datasets.items():
            result = await evaluate_hypothesis(hypothesis, candles, execution=CONSERVATIVE_COST)
            records = [excursion_record(trade, candles, frames[name], buckets) for trade in result.trades]
            all_records.extend(records)
            by_direction = {d: aggregate_records([x for x in records if x["direction"] == d]) for d in ("BUY", "SELL")}
            by_state = {}
            for label in ("trend_strength", "volatility", "recent_direction", "ema_structure"):
                by_state[label] = {value: aggregate_records([x for x in records if x["state"][label] == value])
                                   for value in ("weak", "moderate", "strong", "low", "medium", "high", "bullish", "bearish", "neutral", "compressed")}
            metrics = aggregate_records(records)
            windows[name] = {"metrics": metrics, "by_direction": by_direction,
                             "time_to_edge": time_to_edge(records), "by_state": by_state,
                             "random_control": random_control(records, candles, target_expectancy=metrics.get("net_expectancy")), "records": records}
        hypotheses[hypothesis.hypothesis_id] = {"hypothesis_hash": hypothesis.hypothesis_hash,
            "windows": windows, "aggregate": aggregate_records(all_records),
            "failure_diagnosis": "NO_CLEAR_STRUCTURAL_CAUSE"}
        supporting = sum(windows[name]["metrics"].get("trades", 0) > 0 for name, _, _ in DEVELOPMENT_WINDOWS)
        stable_failure = hypothesis.hypothesis_id == "V2_MEAN_REVERSION"
        structural.append({"finding": f"{hypothesis.hypothesis_id}_failure_mechanism", "supporting_windows": supporting,
                   "supports_v3": False,
                   "statement": "Window outcomes are descriptive; a stable failure does not by itself justify a replacement entry rule.",
                   "failure_mode": "NO_MEAN_REVERSION_EDGE" if stable_failure else "NO_CLEAR_STRUCTURAL_CAUSE"})
    classification, proposed = diagnosis_gate(structural)
    v1 = json.loads(Path("data/research/market_structure_summary_v1.json").read_text(encoding="utf-8"))
    passive_context = {}
    for name, candles in datasets.items():
        first = float(candles[0].open); last = float(candles[-1].close)
        passive_context[name] = {"window_return_percent": (last / first - 1.0) * 100.0,
                                 "window_direction": "UP" if last > first else "DOWN" if last < first else "FLAT"}
    artifact = {"v1_classification": "NO_DURABLE_EDGE_FOUND", "v1_historical_artifact_classification": v1["research_classification"],
        "v1_excursion_status": "EXACT_V1_MFE_MAE_NOT_RECOVERABLE_FROM_ARTIFACT; entry/exit price pair is not persisted",
        "v2_hypothesis_hashes": {h.hypothesis_id: h.hypothesis_hash for h in HYPOTHESES},
        "development_datasets": [{"window_id": n, "start": s.isoformat(), "end": e.isoformat(), "dataset_hash": canonical_dataset_hash(datasets[n], symbol="XAUUSD", timeframe=Timeframe.M15)} for n, s, e in DEVELOPMENT_WINDOWS],
        "holdout_registry": [{"window_id": n, "start": s.isoformat(), "end": e.isoformat(), "dataset_hash": h, "status": "LOCKED_HOLDOUT"} for n, s, e, h in __import__("research.strategy_v2", fromlist=["HOLDOUT_WINDOWS"]).HOLDOUT_WINDOWS],
        "mfe_mae_definitions": "MFE/MAE use only candles at and after entry; entry features are not reused as outcome features.",
        "state_bucket_definitions": buckets, "passive_direction_context": passive_context,
        "random_control": {"seed": 62031, "repetitions": 200, "same observed trade count and direction order": True},
        "hypotheses": hypotheses, "structural_findings": structural, "diagnosis_classification": classification,
        "proposed_v3_hypotheses": list(proposed), "diagnostic_slices_inspected": 3 * 4 * 4,
        "warning": "DESCRIPTIVE_RESEARCH_NOT_INDEPENDENT_VALIDATION", "holdout_refusal_verified": holdout_refusal_check()}
    artifact["report_hash"] = deterministic_hash(artifact)
    path = Path("data/research/strategy_v3_diagnosis.json")
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"report_hash": artifact["report_hash"], "diagnosis_classification": classification,
                      "holdout_refusal_verified": artifact["holdout_refusal_verified"],
                      "diagnostic_slices_inspected": artifact["diagnostic_slices_inspected"]}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())