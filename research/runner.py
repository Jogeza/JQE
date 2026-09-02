"""Offline deterministic JQE research orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from analytics.performance import calculate_performance
from backtesting.backtest import run_backtest
from backtesting.engine import BacktestEngine
from broker.types import Timeframe
from data.dataset import (
    CandleDatasetManifest,
    candle_content_hash,
    load_dataset_bundle,
)
from research.experiments import (
    ExperimentRecord,
    ResearchPartition,
    build_experiment_record,
    save_experiment_record,
)
from research.splits import DatasetSplit, chronological_split


@dataclass(frozen=True, slots=True)
class ResearchRun:
    """Completed TRAIN-only deterministic research run."""

    manifest: CandleDatasetManifest
    split: DatasetSplit
    engine: BacktestEngine
    experiment: ExperimentRecord


async def run_training_experiment(
    *,
    bundle_directory: Path,
    experiment_path: Path,
    strategy_name: str,
    strategy_config: Mapping[str, Any],
    starting_balance: float = 50.0,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    created_at: datetime | None = None,
) -> ResearchRun:
    """Run one experiment against only the TRAIN partition.

    The frozen dataset bundle is verified during loading. The dataset is then
    split chronologically, and only the TRAIN partition is supplied to the
    existing deterministic backtester. Validation and OOS candles are never
    passed to ``run_backtest`` by this function.
    """
    candles, manifest = load_dataset_bundle(bundle_directory)

    split = chronological_split(
        candles,
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
    )

    train = split.train
    partition_hash = candle_content_hash(train)

    # A partition is itself a different candle sequence from the complete
    # frozen dataset, so the full-dataset manifest must not be supplied to
    # run_backtest(). The complete bundle has already been integrity-verified
    # by load_dataset_bundle().
    engine = await run_backtest(
        symbol=manifest.canonical_symbol,
        timeframe=manifest.timeframe,
        candles=len(train),
        starting_balance=starting_balance,
        dataset=train,
    )

    if engine.trades:
        metrics = calculate_performance(
            engine.trades,
            engine.equity_curve,
        )
    else:
        # Preserve useful deterministic metrics even when a strategy takes
        # no trades on the TRAIN partition.
        metrics = {
            **engine.statistics(),
            "Total Trades": 0,
            "Net P&L": round(
                engine.balance - engine.starting_balance,
                2,
            ),
        }

    experiment = build_experiment_record(
        dataset_hash=manifest.content_hash,
        partition_hash=partition_hash,
        symbol=manifest.canonical_symbol,
        timeframe=manifest.timeframe.value,
        partition=ResearchPartition.TRAIN,
        partition_first_candle=train[0].time,
        partition_last_candle=train[-1].time,
        partition_candle_count=len(train),
        strategy_name=strategy_name,
        strategy_config=strategy_config,
        starting_balance=starting_balance,
        metrics=metrics,
        created_at=created_at,
    )

    save_experiment_record(experiment_path, experiment)

    return ResearchRun(
        manifest=manifest,
        split=split,
        engine=engine,
        experiment=experiment,
    )
