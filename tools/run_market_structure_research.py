"""Build the deterministic Phase 6 trade-level market-structure artifact."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from backtesting.models import BacktestExecutionAssumptions

from broker.types import Timeframe
from core.indicators import calculate_indicators
from data.dataset import canonical_dataset_hash
from data.storage import CandleStore
from research.market_structure_research import (
    build_summary,
    extract_trade_records,
    serialize_records,
)
from research.regime_diagnostics import run_variant_backtest
from tools.acquire_diagnostic_windows import WINDOWS


ALL_WINDOWS = (
    ("BASELINE", datetime(2026, 8, 24, tzinfo=timezone.utc), datetime(2026, 8, 31, tzinfo=timezone.utc)),
    *WINDOWS,
)
SCENARIOS = {
    "IDEALIZED_ZERO_COST": BacktestExecutionAssumptions(),
    "CONSERVATIVE_SIMULATION_COST": BacktestExecutionAssumptions(
        spread=0.50, slippage=0.25, fee_per_trade=0.0,
    ),
}
VARIANTS = {
    "BASELINE_BILATERAL": {"sell_only": False, "require_confirmation": False},
    "BASELINE_SELL_ONLY": {"sell_only": True, "require_confirmation": False},
    "CONFIRMED_BILATERAL": {"sell_only": False, "require_confirmation": True},
    "CONFIRMED_SELL_ONLY": {"sell_only": True, "require_confirmation": True},
}


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


async def main() -> None:
    store = CandleStore(read_only=True)
    records = []
    datasets = {}
    for window_id, start, end in ALL_WINDOWS:
        candles = store.load_candles(
            "XAUUSD", Timeframe.M15, start, end, provider="deriv",
        )
        feature_frame = calculate_indicators(
            pd.DataFrame([candle.model_dump() for candle in candles])
        )
        datasets[window_id] = {
            "start": start,
            "end": end,
            "candle_count": len(candles),
            "dataset_hash": canonical_dataset_hash(
                candles, symbol="XAUUSD", timeframe=Timeframe.M15,
            ),
        }
        for variant, variant_config in VARIANTS.items():
            for scenario, execution in SCENARIOS.items():
                result = await run_variant_backtest(
                    symbol="XAUUSD",
                    timeframe=Timeframe.M15,
                    dataset=candles,
                    provider="deriv",
                    starting_balance=50.0,
                    execution_assumptions=execution,
                    sell_only=variant_config["sell_only"],
                    require_confirmation=variant_config["require_confirmation"],
                )
                records.extend(extract_trade_records(
                    result,
                    candles,
                    window_id=window_id,
                    strategy_variant=variant,
                    cost_scenario=scenario,
                    feature_frame=feature_frame,
                ))

    metadata = {
        "symbol": "XAUUSD",
        "timeframe": "M15",
        "total_candles": sum(item["candle_count"] for item in datasets.values()),
        "datasets": datasets,
        "strategy_variants": VARIANTS,
        "cost_scenarios": {
            name: asdict(configuration) for name, configuration in SCENARIOS.items()
        },
    }
    summary = build_summary(records, dataset_metadata=metadata)
    output_root = Path("data/research")
    _write_atomic(output_root / "market_structure_trades_v1.jsonl", serialize_records(records))
    _write_atomic(
        output_root / "market_structure_summary_v1.json",
        (json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8"),
    )
    print(json.dumps({
        "summary_path": str(output_root / "market_structure_summary_v1.json"),
        "records_path": str(output_root / "market_structure_trades_v1.jsonl"),
        "summary_hash": summary["summary_hash"],
        "record_dataset_hash": summary["record_dataset_hash"],
        "total_records": summary["total_records"],
        "buy_records": summary["buy_records"],
        "sell_records": summary["sell_records"],
        "primary_statistics": summary["primary_slice"]["statistics"],
        "candidate_features": summary["candidate_features"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
