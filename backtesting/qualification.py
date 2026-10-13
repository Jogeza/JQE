"""Offline inventory of frozen evidence, never a terminal acquisition path."""
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path

from backtesting.entry_quality import eligibility
from backtesting.provenance import source_snapshot
from data.dataset import load_dataset_bundle
from core.exceptions import JQEError


def qualify_bundles(output: Path, bundles: Path = Path("data/bundles")) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for path in sorted(bundles.glob("*_M5")):
        record = {"bundle": str(path), "promotion_status": "BLOCKED"}
        try:
            candles, manifest = load_dataset_bundle(path)
            step = timedelta(seconds=manifest.granularity_seconds)
            record.update({
                "manifest": asdict(manifest),
                "diagnostic_exclusion": eligibility(candles, manifest),
                "gap_count": sum(b.time - a.time != step for a, b in zip(candles, candles[1:])),
                "holdout_status": "UNTOUCHED_STATUS_NOT_VERIFIED",
                "account_currency_economics": "NOT_VERIFIED",
                "spread_commission_evidence": "NOT_VERIFIED",
            })
        except (JQEError, ValueError, OSError, RuntimeError) as exc:
            record["load_error"] = f"{type(exc).__name__}: {exc}"
        records.append(record)
    report = {
        "status": "BLOCKED_NEEDS_QUALIFIED_DATA",
        "source_snapshot": source_snapshot(),
        "scope": "Frozen M5 bundle inventory only; no terminal calls or replays",
        "strategy_configurations_tried": 0,
        "candidate_configurations_tried": 0,
        "bundles": records,
        "not_proven": ["Untouched holdout", "Verified account-currency sizing and costs", "Positive expectancy"],
    }
    (output / "qualification.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report
