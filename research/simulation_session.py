"""Deterministic, offline simulation-account experiments.

This adapter deliberately reuses the chronological BacktestEngine because it
is JQE's existing forward-only simulated position lifecycle.  It does not
construct a broker gateway or contact any external service.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from backtesting.backtest import run_backtest
from backtesting.models import BacktestExecutionAssumptions, BacktestResult
from config import settings
from data.storage import CandleStore
from research.experiments import ExperimentCatalog, ExperimentRecord, ResearchPartition, build_experiment_record


@dataclass(frozen=True, slots=True)
class SimulationExperimentRun:
    result: BacktestResult
    experiment: ExperimentRecord


def _metrics(result: BacktestResult) -> dict[str, Any]:
    costs = sum(trade.costs for trade in result.trades)
    no_signal = sum(decision.signal not in ("BUY", "SELL") for decision in result.decisions)
    rejected = sum(decision.state in {"RISK_BLOCKED", "REJECTED_CANDIDATE", "EXECUTION_REJECTED"} for decision in result.decisions)
    peak = max((trade.balance_after for trade in result.trades), default=result.initial_capital)
    return {
        "Starting Balance": result.initial_capital,
        "Ending Balance": result.ending_capital,
        "Net P&L": result.absolute_pnl,
        "Return %": result.return_percent,
        "Peak Balance": max(result.initial_capital, peak),
        "Maximum Drawdown": result.maximum_drawdown,
        "Maximum Drawdown %": result.maximum_drawdown_percent,
        "Total Trades": result.total_trades,
        "Winning Trades": result.winning_trades,
        "Losing Trades": result.losing_trades,
        "Win Rate %": result.win_rate_percent,
        "Gross Profit": result.gross_profit,
        "Gross Loss": result.gross_loss,
        "Average Winner": result.average_winner,
        "Average Loser": result.average_loser,
        "Profit Factor": result.profit_factor,
        "Profit Factor Status": result.profit_factor_status,
        "Expectancy": result.expectancy,
        "Largest Winner": result.largest_winner,
        "Largest Loser": result.largest_loser,
        "Maximum Consecutive Wins": result.maximum_consecutive_wins,
        "Maximum Consecutive Losses": result.maximum_consecutive_losses,
        "Risk Authorization Rejections": rejected,
        "No-signal Candles": no_signal,
        "Transaction Costs": costs,
        "Cost Model Status": "COST_MODEL_INCOMPLETE",
        "Equity Curve": [result.initial_capital, *[trade.balance_after for trade in result.trades]],
    }


async def run_cached_simulation_experiment(
    *, store: CandleStore | None = None, catalog: ExperimentCatalog | None = None,
    starting_balance: float = 50.0,
    execution_assumptions: BacktestExecutionAssumptions | None = None,
) -> SimulationExperimentRun:
    """Run the largest deterministic local dataset; never fetch market data."""
    candle_store = store or CandleStore(read_only=True)
    available = sorted(
        candle_store.list_cached_datasets(),
        key=lambda item: (-item.candle_count, item.provider, item.canonical_symbol, item.timeframe),
    )
    if not available:
        raise ValueError("No locally cached historical dataset is available")
    selected = available[0]
    from broker.types import Timeframe
    timeframe = Timeframe(selected.timeframe)
    candles = candle_store.load_candles(selected.canonical_symbol, timeframe, provider=selected.provider)
    execution = execution_assumptions or BacktestExecutionAssumptions(
        spread=0.0, slippage=0.0, fee_per_trade=0.0
    )
    engine = await run_backtest(
        symbol=selected.canonical_symbol, timeframe=timeframe,
        starting_balance=starting_balance, dataset=candles,
        provider=selected.provider, execution_assumptions=execution,
    )
    assert engine.result is not None
    result = engine.result
    experiment_id = f"simulation-{result.result_hash[7:23]}"
    experiment = build_experiment_record(
        dataset_hash=result.dataset_hash, run_fingerprint=result.run_fingerprint,
        result_hash=result.result_hash, engine_version=result.engine_version,
        identity_schema_version=result.identity_schema_version,
        symbol=result.symbol, timeframe=result.timeframe.value,
        partition=ResearchPartition.FULL,
        partition_first_candle=result.dataset_start, partition_last_candle=result.dataset_end,
        partition_candle_count=result.candle_count,
        strategy_name=str(result.strategy.get("strategy_id", "jqe-canonical-strategy")),
        configuration={
            "execution_mode": "SIMULATION", "starting_balance": {"amount": starting_balance, "currency": "USD"},
            "strategy": result.strategy, "risk": asdict(result.risk), "execution": asdict(result.execution),
        },
        metrics=_metrics(result),
        provenance={"provider": selected.provider, "source": selected.volume_source,
                    "provider_symbol": selected.provider_symbol, "selection_policy": "largest_local_cache_then_lexical",
                    "cost_model_status": "COST_MODEL_INCOMPLETE"},
        created_at=result.dataset_end, experiment_id=experiment_id,
    )
    (catalog or ExperimentCatalog(settings.research_experiment_path)).save(experiment)
    return SimulationExperimentRun(result, experiment)
