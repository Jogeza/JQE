"""Run broker-order-free simulator and resolver validation controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import get_settings
from research.simulator_validation import (
    driftless_monte_carlo,
    load_validation_inputs,
    observed_no_gate_expectancy,
    resolver_audit,
    stratified_direction_controls,
)


def run(
    *,
    report_path: Path,
    driftless_seeds: int = 50,
    driftless_samples: int = 500,
    control_seeds: int = 50,
    no_gate_samples: int = 5000,
    only_driftless: bool = False,
    only_controls: bool = False,
) -> dict:
    settings = get_settings()
    if settings.broker_execution_enabled:
        raise RuntimeError("simulator validation refuses to run with broker execution enabled")
    candidates, series = load_validation_inputs(settings)
    result = {
        "execution_enabled": False,
        "watchlist_series": len(series),
        "persisted_candidates": len(candidates),
        "horizon_bars": 20,
        "resolver_audit": resolver_audit(),
    }
    if not only_controls:
        result["driftless_monte_carlo"] = driftless_monte_carlo(
            series, seeds=driftless_seeds, samples_per_series=driftless_samples,
        )
    if not only_driftless:
        result["stratified_direction_controls"] = stratified_direction_controls(
            candidates, series, seeds=control_seeds,
        )
        result["observed_no_gate_expectancy"] = observed_no_gate_expectancy(
            series, samples_per_series=no_gate_samples,
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("state/simulator_validation_report.json"))
    parser.add_argument("--driftless-seeds", type=int, default=50)
    parser.add_argument("--driftless-samples", type=int, default=500)
    parser.add_argument("--control-seeds", type=int, default=50)
    parser.add_argument("--no-gate-samples", type=int, default=5000)
    parser.add_argument("--only-driftless", action="store_true")
    parser.add_argument("--only-controls", action="store_true")
    args = parser.parse_args()
    result = run(
        report_path=args.report, driftless_seeds=args.driftless_seeds,
        driftless_samples=args.driftless_samples, control_seeds=args.control_seeds,
        no_gate_samples=args.no_gate_samples, only_driftless=args.only_driftless,
        only_controls=args.only_controls,
    )
    print(json.dumps({
        "report": str(args.report), "execution_enabled": result["execution_enabled"],
        "watchlist_series": result["watchlist_series"],
        "sections": sorted(key for key in result if key not in {"execution_enabled", "watchlist_series", "persisted_candidates", "horizon_bars"}),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
