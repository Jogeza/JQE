"""Offline reproducible research batch runner for the 17 Weltrade watchlist markets.

Iterates over all 17 Weltrade synthetic index symbols across M1 and M5 timeframes,
exports immutable dataset bundles, executes deterministic training experiments via
``research.runner.run_training_experiment``, and records reproducible experiment
records to ``settings.research_experiment_path``.

Never connects to a broker or executes live trades.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from broker.types import Timeframe
from broker.weltrade_symbols import require_weltrade_synthetic
from config.settings import settings
from data.dataset import build_dataset_manifest, export_dataset_bundle
from data.storage import CandleStore
from research.experiments import ExperimentCatalog, ResearchPartition, load_experiment_record
from research.runner import run_partition_experiment, run_training_experiment

WATCHLIST_SYMBOLS = (
    "FX Vol 20", "FX Vol 40", "FX Vol 60", "FX Vol 80", "FX Vol 99",
    "SFX Vol 20", "SFX Vol 40", "SFX Vol 60", "SFX Vol 80", "SFX Vol 99",
    "PainX 400", "PainX 600", "PainX 800", "PainX 999", "PainX 1200",
    "MAX PainX 1000", "MAX PainX 2000",
)

TIMEFRAMES = (Timeframe.M1, Timeframe.M5)


def slugify(symbol: str) -> str:
    return symbol.replace(" ", "_")


async def run_batch(
    symbols: tuple[str, ...] = WATCHLIST_SYMBOLS,
    timeframes: tuple[Timeframe, ...] = TIMEFRAMES,
    starting_balance: float = 50.0,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    store = CandleStore(settings.historical_data_path, read_only=True)
    catalog = ExperimentCatalog(settings.research_experiment_path)
    bundle_root = Path("data/bundles")
    bundle_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []

    for symbol in symbols:
        # Enforce Weltrade synthetic identity
        require_weltrade_synthetic(symbol)

        for tf in timeframes:
            candles = store.load_latest(symbol, tf, 5000, provider="weltrade")
            if not candles:
                print(f"[SKIP] No cached candles for {symbol} {tf.value}")
                results.append({
                    "symbol": symbol,
                    "timeframe": tf.value,
                    "status": "NO_DATA",
                    "candle_count": 0,
                })
                continue

            manifest = build_dataset_manifest(
                candles,
                provider="weltrade",
                source="Weltrade MT5 terminal",
                provider_symbol=symbol,
                canonical_symbol=symbol,
                timeframe=tf,
                retrieved_at=datetime.now(timezone.utc),
            )

            bundle_dir = bundle_root / f"{slugify(symbol)}_{tf.value}"
            export_dataset_bundle(bundle_dir, candles, manifest)

            # 1. In-Sample Training Run (First 60% of chronological bars)
            train_run = await run_partition_experiment(
                bundle_directory=bundle_dir,
                catalog=catalog,
                strategy_name="jqe-canonical-strategy-v1",
                strategy_config={},
                partition=ResearchPartition.TRAIN,
                starting_balance=starting_balance,
                train_fraction=train_fraction,
                validation_fraction=validation_fraction,
            )

            # 2. Out-of-Sample Holdout Run (Chronological final 20% of bars)
            oos_run = await run_partition_experiment(
                bundle_directory=bundle_dir,
                catalog=catalog,
                strategy_name="jqe-canonical-strategy-v1",
                strategy_config={},
                partition=ResearchPartition.OOS,
                starting_balance=starting_balance,
                train_fraction=train_fraction,
                validation_fraction=validation_fraction,
            )

            train_rec = train_run.experiment
            oos_rec = oos_run.experiment
            split = train_run.split

            summary = {
                "symbol": symbol,
                "timeframe": tf.value,
                "total_candles": len(candles),
                "dataset_hash": train_rec.dataset_hash,
                "train_experiment": {
                    "experiment_id": train_rec.experiment_id,
                    "status": train_rec.status.value,
                    "candle_count": len(split.train),
                    "start": split.train[0].time.isoformat(),
                    "end": split.train[-1].time.isoformat(),
                    "metrics": dict(train_rec.metrics),
                },
                "oos_experiment": {
                    "experiment_id": oos_rec.experiment_id,
                    "status": oos_rec.status.value,
                    "candle_count": len(split.out_of_sample),
                    "start": split.out_of_sample[0].time.isoformat(),
                    "end": split.out_of_sample[-1].time.isoformat(),
                    "metrics": dict(oos_rec.metrics),
                },
                "degradation": {
                    "train_pnl": train_rec.metrics.get("Net P&L", 0.0),
                    "oos_pnl": oos_rec.metrics.get("Net P&L", 0.0),
                    "train_trades": train_rec.metrics.get("Total Trades", 0),
                    "oos_trades": oos_rec.metrics.get("Total Trades", 0),
                },
                "provenance": dict(train_rec.provenance),
            }
            results.append(summary)
            print(
                f"[OK] {symbol:16} {tf.value:2} | Total: {len(candles):4} | "
                f"Train PnL: {train_rec.metrics.get('Net P&L', 0.0):+6.2f} (trades: {train_rec.metrics.get('Total Trades', 0):2}) | "
                f"OOS PnL: {oos_rec.metrics.get('Net P&L', 0.0):+6.2f} (trades: {oos_rec.metrics.get('Total Trades', 0):2}) | "
                f"TrainID: {train_rec.experiment_id[:8]} OosID: {oos_rec.experiment_id[:8]}"
            )

    return results


async def main() -> None:
    print(f"Starting research batch run for {len(WATCHLIST_SYMBOLS)} symbols across M1 and M5...")
    results = await run_batch()
    output_path = Path("state/research_batch_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved {len(results)} experiment summaries to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
