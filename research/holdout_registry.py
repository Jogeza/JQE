"""Durable selection lock for the already-used replay holdout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HOLDOUT_ID = "shadow-replay-holdout-2026-09-24-v1"


class HoldoutConsumedError(RuntimeError):
    """Raised when a selection/tuning operation attempts to use the holdout."""


def consumed_record(*, report_path: str = "state/sequential_replay_report.json") -> dict[str, Any]:
    return {
        "holdout_id": HOLDOUT_ID,
        "status": "CONSUMED",
        "selection_locked": True,
        "window": "last_40_percent_time_ordered",
        "source_report": report_path,
        "selection_rule": "No model, threshold, score, horizon, cap, or parameter selection may use this window.",
        "reason": "The current holdout was inspected for the requested report and is now sealed.",
    }


def write_consumed_record(path: str | Path = "state/holdout_registry.json") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(consumed_record(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def assert_holdout_available_for_selection(path: str | Path = "state/holdout_registry.json") -> None:
    target = Path(path)
    if not target.exists():
        return
    record = json.loads(target.read_text(encoding="utf-8"))
    if record.get("holdout_id") == HOLDOUT_ID and record.get("status") == "CONSUMED":
        raise HoldoutConsumedError(f"holdout {HOLDOUT_ID} is CONSUMED and cannot be used for selection")

