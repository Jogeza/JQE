"""Run broker-order-free PainX exit-mode and stability research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import get_settings
from research.simulator_validation import load_validation_inputs, painx_research_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=5000)
    parser.add_argument("--report", type=Path, default=Path("state/painx_research_report.json"))
    args = parser.parse_args()
    settings = get_settings()
    _, series = load_validation_inputs(settings)
    report = painx_research_report(series, samples_per_series=args.samples)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(args.report),
        "series": len(report["stability"]["by_series"]),
        "execution_enabled": settings.broker_execution_enabled,
        "r_basis": report["r_basis"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
