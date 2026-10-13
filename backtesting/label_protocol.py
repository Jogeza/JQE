"""Freeze training-only counterfactual-label semantics without computing outcomes."""
from collections import Counter
from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path

from backtesting.economics import FrozenCostPolicy
from backtesting.models import BacktestExecutionAssumptions
from backtesting.opportunity_inventory import aware, digest, extract
from backtesting.provenance import source_snapshot
from data.dataset import load_dataset_bundle


def eligibility(times, index, end):
    """Pre-outcome censoring: three prior bars and all nineteen entry bars."""
    if index < 3 or index + 19 >= len(times):
        return "CENSORED_INCOMPLETE_HORIZON"
    if times[index + 19] + timedelta(minutes=5) > end:
        return "CENSORED_PARTITION_BOUNDARY"
    window = times[index - 3:index + 20]
    if any(b - a != timedelta(minutes=5) for a, b in zip(window, window[1:])):
        return "CENSORED_GAP"
    return "ELIGIBLE_FOR_CANONICAL_REPLAY_NOT_YET_LABELLED"


def file_hash(path):
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def register(training: Path, campaign: Path, terms: Path, output: Path):
    """Single fixed symbol chosen for documented execution feasibility, not ML fit."""
    output.mkdir(parents=True, exist_ok=False)
    parent = json.loads((campaign / "protocol.json").read_text())
    parent_hash = json.loads((campaign / "protocol.sha256.json").read_text())["sha256"]
    # Parent uses ordinary canonical JSON, without our sha256: prefix.
    if digest(parent).removeprefix("sha256:") != parent_hash:
        raise ValueError("Parent registration hash mismatch")
    replay_path = training / "training-replay-protocol.json"
    replay = json.loads(replay_path.read_text())
    if replay["partition"] != "TRAIN_DIAGNOSTIC_ONLY" or replay["windows"] != parent["windows"]:
        raise ValueError("Frozen training protocol mismatch")
    start, end = (aware(parent["windows"]["train"][key]) for key in ("start_inclusive", "end_exclusive"))
    symbol = "SFX Vol 99"
    result_path = training / "SFX_Vol_99--optimistic_zero_commission--result.json"
    result = json.loads(result_path.read_text())
    if result["symbol"] != symbol or result["strategy"]["strategy_id"] != "jqe-canonical-strategy-v2":
        raise ValueError("Canonical baseline identity mismatch")
    opportunities, observations = extract(result, start, end)
    bundle = campaign / "bundles" / "SFX_Vol_99_M5"
    candles, manifest = load_dataset_bundle(bundle)
    if manifest.provider != "weltrade" or manifest.provider_symbol != symbol or manifest.timeframe.value != "M5":
        raise ValueError("Exact native provider/symbol/timeframe required")
    if any(c.time + timedelta(minutes=5) > manifest.retrieved_at for c in candles):
        raise ValueError("Unclosed source bars")
    positions = {c.time: i for i, c in enumerate(candles)}
    times = tuple(c.time for c in candles)
    events = []
    for opportunity in opportunities:
        index = positions[aware(opportunity["signal_bar_open"])]
        events.append({"event_id": opportunity["event_id"], "signal_bar_open": opportunity["signal_bar_open"],
                       "direction": opportunity["direction"], "source_candle_index": index,
                       "status": eligibility(times, index, end)})
    # Frozen model evidence is bound, not upgraded to verified historical terms.
    evidence = json.loads(terms.read_text())
    if evidence["account_currency"] != "USD" or symbol not in {r["symbol"] for r in evidence["symbols"]}:
        raise ValueError("Matching USD contract evidence required")
    costs = {"optimistic_zero_commission": asdict(FrozenCostPolicy(0)),
             "assumed_3usd_per_lot_per_side": asdict(FrozenCostPolicy(3)),
             "double_spread_commission": asdict(FrozenCostPolicy(6, spread_multiplier=2))}
    protocol = {"schema_version": 1, "protocol_id": "jqe-counterfactual-training-labels-v1",
        "status": "REGISTERED_LABEL_DESIGN_ONLY_NO_OUTCOMES", "symbol": symbol, "provider": "weltrade",
        "timeframe": "M5", "training_window": parent["windows"]["train"],
        "registration_scope": "Past training signals and baseline outcomes already inspected; not an OOS strategy preregistration",
        "strategy": "jqe-canonical-strategy-v2", "market_model": "frozen-weltrade-cfd-v2",
        "initial_capital_per_opportunity_usd": 50.0, "risk_percent": 1.0,
        "execution": asdict(BacktestExecutionAssumptions()), "cost_cases": costs,
        "signal_generation": "Only strategy.pipeline.generate_trading_signal within canonical run_backtest",
        "replay_semantics": "Preserve full original training-prefix indicator history, queue only the target signal; no subsequent signals queued",
        "entry_semantics": "Signal bar i closed; next observed contiguous bar i+1 open; horizon includes i+1 through i+19",
        "account_semantics": "Reset 50 USD, no position/pending state for each event; retain all native stop/lot/margin/cost constraints",
        "censor_semantics": "Pre-outcome exclusion if last three history bars through full nineteen-entry-bar horizon have gaps or cross train end; no early-exit rescue",
        "labels": {"EXECUTED": "Net modelled USD and net R divided by rounded planned stop cash; available only at exit-bar close",
                   "NON_EXECUTABLE": "Explicit canonical risk/execution rejection; return label null, never zero or synthetic unit return",
                   "CENSORED": "Null return and documented pre-outcome reason; never truncate into END_OF_DATA return"},
        "features": "Eight-feature allowlist in research.ml_validation; causal implementation and equivalence still required",
        "inference_scope": "Conditional single-opportunity return at fixed capital, not stateful strategy expectancy or portfolio P&L",
        "dependence": "Overlapping labels are not independent; purge actual label availability, keep synchronized time folds and three-day block uncertainty",
        "cost_pairing": "One event identity across all three cases; preserve cost-specific execution rejects, never pool repeated labels",
        "equivalence_requirements": ["Target signal matches original canonical decision before queueing",
            "Same candles, full indicator prefix, contract hashes and fill logic",
            "At most one trade per event, no post-target entry, no production-path changes",
            "Final candidate evaluated separately as a stateful canonical baseline comparison"],
        "models_fitted": 0, "candidate_configurations": 0, "label_design_configurations": 1,
        "census": dict(Counter(e["status"] for e in events)), "canonical_observations": observations,
        "opportunities": len(events), "outcomes_computed": 0, "ml_fit_authorized": False,
        "holdouts_read": False, "source_snapshot": source_snapshot(),
        "inputs": {str(p): file_hash(p) for p in [campaign / "protocol.json", replay_path, result_path,
            terms, campaign / "acquisition.json", bundle / "manifest.json", bundle / "recorded-spread.json"]}}
    write_new(output / "events.json", events)
    protocol["events_sha256"] = file_hash(output / "events.json")
    write_new(output / "protocol.json", protocol)
    write_new(output / "protocol.sha256.json", {"sha256": file_hash(output / "protocol.json")})
    return protocol
