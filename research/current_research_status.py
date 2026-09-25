"""Current interpretation layer; does not mutate locked hypotheses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def current_research_status() -> dict[str, Any]:
    return {
        "status": "NO_DEMONSTRATED_POSITIVE_EDGE",
        "as_of": "2026-09-24",
        "family_hypothesis": {
            "scope": "PainX family ungated BUY",
            "result": "FAILED_IN_EXPLORATORY_DATA",
            "corrected_gap_aware_equal_cell_average_r": -1.343832693163576,
            "positive_instrument_timeframe_cells": 0,
            "historical_definition_changed": False,
        },
        "painx1200_m1_buy": {
            "role": "NEWLY_SELECTED_EXPLORATORY_CANDIDATE",
            "demonstrated_positive_edge": False,
            "corrected_historical_gap_aware_average_r": -1.423658976846924,
            "forward_status": "UNCONFIRMED_INSUFFICIENT_SAMPLE",
            "locked_definition_and_success_criteria_changed": False,
        },
        "exit_evidence": {
            "p95_price_units": 40.63399999999966,
            "classification": "SENSITIVITY_ASSUMPTION_NOT_OBSERVED_FILL",
            "timestamped_tick_crossings_reconstructed": 1140,
            "recorded_broker_stop_fills": 0,
        },
        "presentation_rule": "Dashboards, reports, and alerts must label this candidate unconfirmed and must not describe it as a demonstrated positive edge.",
        "execution_authority": "NONE_RESEARCH_ONLY",
    }


def write_current_research_status(path: str | Path = "state/current_research_status.json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(current_research_status(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
