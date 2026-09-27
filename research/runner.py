"""Offline deterministic JQE research orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from analytics.performance import calculate_performance
from backtesting.backtest import run_backtest
from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExecutionAssumptions
from broker.types import Timeframe
from config.settings import settings
from data.dataset import CandleDatasetManifest, load_dataset_bundle
from research.experiments import (
    ExperimentCatalog,
    ExperimentRecord,
    ResearchPartition,
    build_experiment_record,
)
from research.splits import DatasetSplit, chronological_split


@dataclass(frozen=True, slots=True)
class ResearchRun:
    """Completed deterministic research run for a specific dataset partition."""

    manifest: CandleDatasetManifest
    split: DatasetSplit
    engine: BacktestEngine
    experiment: ExperimentRecord


async def run_partition_experiment(
    *,
    bundle_directory: Path,
    catalog: ExperimentCatalog | None = None,
    strategy_name: str,
    strategy_config: Mapping[str, Any],
    partition: ResearchPartition = ResearchPartition.TRAIN,
    starting_balance: float = 50.0,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    execution_assumptions: BacktestExecutionAssumptions | None = None,
    created_at: datetime | None = None,
) -> ResearchRun:
    """Run an experiment against a specific partition (TRAIN, VALIDATION, OOS, or FULL).

    The frozen dataset bundle is verified during loading. The dataset is then
    split chronologically, and only the target partition is supplied to the
    existing deterministic backtester.
    """
    candles, manifest = load_dataset_bundle(bundle_directory)

    split = chronological_split(
        candles,
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
    )

    train_len = len(split.train)
    val_len = len(split.validation)
    total_len = len(candles)

    if partition == ResearchPartition.TRAIN:
        target_candles = split.train
        engine = await run_backtest(
            symbol=manifest.canonical_symbol,
            timeframe=manifest.timeframe,
            candles=len(split.train),
            starting_balance=starting_balance,
            dataset=split.train,
            strategy_configuration=dict(strategy_config),
            execution_assumptions=execution_assumptions,
        )
    elif partition == ResearchPartition.VALIDATION:
        target_candles = split.validation
        engine = await run_backtest(
            symbol=manifest.canonical_symbol,
            timeframe=manifest.timeframe,
            candles=total_len,
            starting_balance=starting_balance,
            dataset=candles,
            start_index=train_len,
            end_index=train_len + val_len,
            strategy_configuration=dict(strategy_config),
            execution_assumptions=execution_assumptions,
        )
    elif partition == ResearchPartition.OOS:
        target_candles = split.out_of_sample
        engine = await run_backtest(
            symbol=manifest.canonical_symbol,
            timeframe=manifest.timeframe,
            candles=total_len,
            starting_balance=starting_balance,
            dataset=candles,
            start_index=train_len + val_len,
            end_index=total_len,
            strategy_configuration=dict(strategy_config),
            execution_assumptions=execution_assumptions,
        )
    elif partition == ResearchPartition.FULL:
        target_candles = tuple(candles)
        engine = await run_backtest(
            symbol=manifest.canonical_symbol,
            timeframe=manifest.timeframe,
            candles=total_len,
            starting_balance=starting_balance,
            dataset=candles,
            strategy_configuration=dict(strategy_config),
            execution_assumptions=execution_assumptions,
        )
    else:
        raise ValueError(f"Unsupported research partition: {partition}")

    if engine.trades:
        metrics = calculate_performance(
            engine.trades,
            engine.equity_curve,
        )
    else:
        metrics = {
            **engine.statistics(),
            "Total Trades": 0,
            "Net P&L": round(
                engine.balance - engine.starting_balance,
                2,
            ),
        }

    assert engine.result is not None
    backtest_result = engine.result
    experiment = build_experiment_record(
        dataset_hash=backtest_result.dataset_hash,
        run_fingerprint=backtest_result.run_fingerprint,
        result_hash=backtest_result.result_hash,
        engine_version=backtest_result.engine_version,
        identity_schema_version=backtest_result.identity_schema_version,
        symbol=manifest.canonical_symbol,
        timeframe=manifest.timeframe.value,
        partition=partition,
        partition_first_candle=target_candles[0].time,
        partition_last_candle=target_candles[-1].time,
        partition_candle_count=len(target_candles),
        strategy_name=strategy_name,
        configuration={
            "strategy": backtest_result.strategy,
            "risk": asdict(backtest_result.risk),
            "execution": asdict(backtest_result.execution),
            "initial_capital": backtest_result.initial_capital,
        },
        metrics=metrics,
        provenance={
            "provider": manifest.provider,
            "source": manifest.source,
            "provider_symbol": manifest.provider_symbol,
            "frozen_manifest_content_hash": manifest.content_hash,
        },
        created_at=created_at,
    )

    (catalog or ExperimentCatalog(settings.research_experiment_path)).save(experiment)

    return ResearchRun(
        manifest=manifest,
        split=split,
        engine=engine,
        experiment=experiment,
    )


async def run_training_experiment(
    *,
    bundle_directory: Path,
    catalog: ExperimentCatalog | None = None,
    strategy_name: str,
    strategy_config: Mapping[str, Any],
    starting_balance: float = 50.0,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    created_at: datetime | None = None,
) -> ResearchRun:
    """Run one experiment against only the TRAIN partition."""
    return await run_partition_experiment(
        bundle_directory=bundle_directory,
        catalog=catalog,
        strategy_name=strategy_name,
        strategy_config=strategy_config,
        partition=ResearchPartition.TRAIN,
        starting_balance=starting_balance,
        train_fraction=train_fraction,
        validation_fraction=validation_fraction,
        created_at=created_at,
    )
