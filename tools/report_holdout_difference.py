"""Report the sealed holdout strategy-minus-control block bootstrap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import get_settings
from research.simulator_validation import holdout_strategy_minus_control, load_validation_inputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-report", type=Path, default=Path("state/sequential_replay_stratified_report.json"))
    parser.add_argument("--output", type=Path, default=Path("state/holdout_control_difference.json"))
    args = parser.parse_args()
    settings = get_settings()
    if settings.broker_execution_enabled:
        raise RuntimeError("holdout report refuses to run with broker execution enabled")
    candidates, series = load_validation_inputs(settings)
    result = holdout_strategy_minus_control(candidates, series, str(args.replay_report))
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
