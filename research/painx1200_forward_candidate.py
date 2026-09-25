"""Immutable prospective record for the selected PainX 1200 M1 candidate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CANDIDATE_ID = "painx1200-m1-buy-forward-v1"


def family_conclusion() -> dict[str, Any]:
    return {
        "record_type": "historical_exploratory_conclusion",
        "recorded_on": "2026-09-24",
        "historical_hypothesis_id": "forward-observation-v2-exploratory-origin",
        "historical_definition_unchanged": True,
        "conclusion": "FAILED_IN_EXPLORATORY_DATA",
        "scope": "ungated BUY on the PainX family",
        "gap_aware_equal_cell_average_r_before_overshoot_audit": -0.4476752472811577,
        "note": "This conclusion is retained separately and is not narrowed to the selected candidate.",
    }


def candidate_record() -> dict[str, Any]:
    return {
        "candidate_id": CANDIDATE_ID,
        "status": "PROSPECTIVELY_LOCKED",
        "origin": "new exploratory candidate selected from consumed exploratory data; requires untouched forward confirmation",
        "selection_date": "2026-09-24",
        "exploratory_data_cutoff": "2026-09-24T11:39:00+00:00",
        "instrument": "PAINX 1200",
        "timeframe": "M1",
        "primary_side": "BUY",
        "control_side": "SELL",
        "sampling": {
            "interval_closed_bars": 20,
            "entry": "next closed candle's following open; BUY enters at ask and SELL at bid",
            "non_overlapping_per_side": True,
            "horizon_bars": 20,
        },
        "plan_geometry": {
            "planner": "TradePlanBuilder",
            "stop": "1.5 * ATR at sampled signal close",
            "target": "2.0R (3.0 * ATR) from plan entry basis",
            "r_basis": "PLAN_GEOMETRY",
            "signal_gate": "ungated hypothetical plan; no strategy or confidence change",
        },
        "exit_model": {
            "name": "gap_aware",
            "opening_gap": "worse of planned SL and executable bar open",
            "intrabar_stop": "planned SL plus adverse positive-excursion p95 estimated only from bars preceding the signal",
            "spread": "per-bar MT5 spread; side-aware entry/exit and widening where applicable",
            "ambiguity": "tick/M1 drill-down when available; otherwise unresolved ambiguity is reported",
        },
        "success_criteria": {
            "minimum_resolved_non_overlapping_buy_entries": 500,
            "minimum_distinct_entry_days": 10,
            "positive_expectancy_first_half": True,
            "positive_expectancy_second_half": True,
            "three_utc_day_block_bootstrap_95_ci_lower_bound_gt_zero": True,
        },
        "selection_warning": "The overshoot audit corrected the exploratory exit accounting after selection. The candidate remains a prospective test, not evidence or permission to trade.",
        "execution": "READ_ONLY; broker execution must resolve false; no orders",
    }


def _write_immutable(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeError(f"locked record differs: {path}")
        return path
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_locked_records(root: str | Path = "state") -> tuple[Path, Path]:
    base = Path(root)
    family = _write_immutable(base / "painx_family_exploratory_conclusion.json", family_conclusion())
    candidate = _write_immutable(base / "painx1200_m1_forward_candidate.json", candidate_record())
    return family, candidate
