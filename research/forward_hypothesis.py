"""Pre-declared forward hypothesis; immutable once observation begins."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HYPOTHESIS_ID = "forward-observation-v2-exploratory-origin"


def predeclared_record() -> dict[str, Any]:
    return {
        "hypothesis_id": HYPOTHESIS_ID,
        "status": "PREDECLARED",
        "data_cutoff": None,
        "origin": "exploratory-origin; predeclared before new forward data and not tunable from forward results",
        "primary_hypothesis": "H1: Ungated BUY on the PainX family has positive planner-geometry R after spread with gap-aware exits.",
        "success_criteria": {
            "minimum_resolved_trades": 500,
            "minimum_distinct_entry_days": 10,
            "net_r_after_spread_gt": 0,
            "exit_accounting": "gap-aware; worse of planned SL and executable bar open on an opening stop gap, otherwise observed-data 95th-percentile adverse overshoot",
            "r_basis": "PLAN_GEOMETRY",
            "block_bootstrap_95_ci_lower_bound_gt": 0,
            "positive_in_first_half": True,
            "positive_in_second_half": True,
        },
        "secondary_hypothesis": {
            "id": "H2",
            "statement": "The confidence gate adds value over ungated BUY on the PainX family.",
            "expected": "NO",
        },
        "control_design": {
            "stratified_buy_only": {
                "entry_counts": "match MAX PainX strategy entries by symbol|timeframe|UTC day",
                "randomization": "random eligible closed bars without replacement",
                "planner_and_resolver": "same live-fidelity planner, spread source, and resolver",
            },
            "sell_only_mirror": {
                "entry_counts": "same strata and counts as the BUY-only control",
                "purpose": "directional mirror control for resolver or market-drift bias",
            },
            "time_reversed_buy": {
                "entry_counts": "same strata and counts as the BUY-only control",
                "purpose": "temporal-order control without changing planner geometry",
            },
            "negative_controls": {
                "ungated_sell": "Same symbols, timeframes, cadence, planner geometry, and resolver; SELL direction only.",
                "ungated_fx_sfx_vol": "Ungated BUY on FX Vol and SFX Vol families with the same sampling and resolver.",
            },
        },
        "forward_shadow_sampler": {
            "mode": "READ_ONLY",
            "cadence": "one hypothetical BUY and one hypothetical SELL per symbol|timeframe after every 20 closed bars",
            "non_overlapping": True,
            "planner": "same TradePlanBuilder geometry; no confidence gate and no broker order",
            "resolver": "same shadow resolver with source=forward_ungated",
            "expected_time_to_500_painx_buy_plans": "approximately 1 continuous trading day after warm-up; 20-bar outcomes add the resolution delay",
        },
        "measurement": {
            "entry_basis": "NEXT_CANDLE_OPEN",
            "exit_accounting": "gap-aware",
            "horizon_bars": 20,
            "r_basis": "PLAN_GEOMETRY",
            "source": "forward_ungated_and_live",
            "split_policy": "forward_only; current consumed holdout excluded",
            "day_block_bootstrap_days": 3,
        },
        "selection_lock": "No forward data may be used to rewrite this hypothesis or tune its criteria.",
    }


def write_predeclared_record(path: str | Path = "state/forward_hypothesis.json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != predeclared_record():
            raise RuntimeError("forward hypothesis already exists with different contents")
        return target
    target.write_text(json.dumps(predeclared_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
