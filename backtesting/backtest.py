"""JQE institutional backtest runner.

Loads a fixed historical candle dataset supplied by the caller or from
the local :class:`data.storage.CandleStore`, then replays
JQE's signal -> risk -> execution pipeline candle by candle to produce
performance statistics — the same
:func:`strategy.pipeline.generate_trading_signal` and
:func:`risk.risk_controller.approve_trade` used by ``main.py``'s live
path, so backtest results reflect the actual decision logic.

Run as a script:

    $ python -m backtesting.backtest

Or call :func:`run_backtest` directly for programmatic use.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from analytics.performance import calculate_performance
from backtesting.engine import BacktestEngine
from collections.abc import Sequence

from broker.types import Candle, Timeframe
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from strategy.pipeline import generate_trading_signal
from data.dataset import CandleDatasetManifest, verify_dataset_manifest
from data.storage import CandleStore
from backtesting.models import (
    BacktestExecutionAssumptions, BacktestResult, BacktestRiskConfiguration,
    CandleDatasetSnapshot,
)

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = Timeframe.M5
DEFAULT_CANDLES = 5000

# Indicators (EMA200, rolling ATR/RSI at window 14) need this many
# leading candles before their values are meaningful — trades aren't
# evaluated before this point.
_WARMUP_CANDLES = 200


class BacktestRunner:
    """Explicit configuration wrapper around the canonical backtest entrypoint."""

    def __init__(self, *, symbol: str = DEFAULT_SYMBOL, timeframe: Timeframe = DEFAULT_TIMEFRAME,
                 initial_capital: float = 50.0, provider: str = "unknown",
                 risk_configuration: BacktestRiskConfiguration | None = None,
                 execution_assumptions: BacktestExecutionAssumptions | None = None,
                 strategy_configuration: dict | None = None) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.initial_capital = initial_capital
        self.provider = provider
        self.risk_configuration = risk_configuration
        self.execution_assumptions = execution_assumptions
        self.strategy_configuration = strategy_configuration

    async def run(self, dataset: Sequence[Candle]) -> BacktestResult:
        engine = await run_backtest(
            symbol=self.symbol, timeframe=self.timeframe,
            starting_balance=self.initial_capital, dataset=dataset,
            provider=self.provider, risk_configuration=self.risk_configuration,
            execution_assumptions=self.execution_assumptions,
            strategy_configuration=self.strategy_configuration,
        )
        assert engine.result is not None
        return engine.result


async def run_backtest(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: Timeframe = DEFAULT_TIMEFRAME,
    candles: int = DEFAULT_CANDLES,
    starting_balance: float = 50.0,
    dataset: Sequence[Candle] | None = None,
    store: CandleStore | None = None,
    manifest: CandleDatasetManifest | None = None,
    risk_configuration: BacktestRiskConfiguration | None = None,
    execution_assumptions: BacktestExecutionAssumptions | None = None,
    strategy_configuration: dict | None = None,
    provider: str | None = None,
) -> BacktestEngine:
    """Runs a full backtest and returns the engine holding its results.

    Args:
        symbol: Instrument symbol to backtest.
        timeframe: Candle timeframe.
        candles: Number of historical candles to load.
        starting_balance: Simulated starting account balance.

    Returns:
        The :class:`~backtesting.engine.BacktestEngine` used for the
        run — inspect ``.statistics()``, ``.trades``, and
        ``.equity_curve`` for results.

    Raises:
        core.exceptions.MarketDataError: If fixed historical market data
            cannot be retrieved, or there isn't enough of it to clear
            the indicator warmup period.
    """
    logger.info("JQE backtest starting for {} ({} candles)", symbol, candles)

    # Backtests consume a caller-supplied immutable dataset or the durable local
    # cache.  They never construct/connect a broker gateway.
    if dataset is None and provider is None:
        raise MarketDataError(
            "A provider is required when loading a canonical backtest dataset from cache",
            symbol=symbol,
        )
    raw_candles = list(dataset) if dataset is not None else (store or CandleStore()).load_latest(
        symbol, timeframe, candles, provider=provider
    )
    if not raw_candles:
        raise MarketDataError("No fixed historical dataset available", symbol=symbol)
    if any(current.time <= previous.time for previous, current in zip(raw_candles, raw_candles[1:])):
        raise MarketDataError("Historical dataset timestamps must be strictly increasing", symbol=symbol)

    # A supplied manifest represents a previously frozen dataset identity.
    # Verify it before indicators, strategy logic, or simulated execution run.
    if manifest is not None:
        if manifest.canonical_symbol != symbol:
            raise MarketDataError(
                "Historical dataset manifest symbol does not match backtest",
                manifest_symbol=manifest.canonical_symbol,
                backtest_symbol=symbol,
            )
        if manifest.timeframe != timeframe:
            raise MarketDataError(
                "Historical dataset manifest timeframe does not match backtest",
                manifest_timeframe=manifest.timeframe.value,
                backtest_timeframe=timeframe.value,
            )
        verify_dataset_manifest(manifest, raw_candles)

    df = pd.DataFrame([candle.model_dump() for candle in raw_candles])
    df = calculate_indicators(df)

    if len(df) <= _WARMUP_CANDLES:
        raise MarketDataError(
            "Not enough candles to clear the indicator warmup period",
            symbol=symbol,
            candles=len(df),
            warmup_required=_WARMUP_CANDLES,
        )

    dataset_provider = provider or (manifest.provider if manifest else raw_candles[0].source)
    snapshot = CandleDatasetSnapshot(
        provider=dataset_provider, symbol=symbol, timeframe=timeframe,
        candles=tuple(raw_candles),
    )
    engine = BacktestEngine(
        starting_balance=starting_balance, symbol=symbol, timeframe=timeframe,
        risk=risk_configuration, execution=execution_assumptions,
    )

    for i in range(_WARMUP_CANDLES, len(df)):
        engine.process_candle(i, df)
        history = df.iloc[: i + 1]
        regime = detect_regime(history)
        signal = generate_trading_signal(history, symbol, regime=regime)
        engine.queue_signal(signal, i, df)

    engine.finish(len(df) - 1, df)

    basic_stats = engine.statistics()
    logger.info("JQE backtest results: {}", basic_stats)

    if engine.trades:
        institutional_metrics = calculate_performance(engine.trades, engine.equity_curve)
        logger.info("Institutional metrics: {}", institutional_metrics)
    else:
        logger.warning("No trades were taken during this backtest run")

    engine.result = build_backtest_result(
        snapshot, engine,
        strategy_configuration or {"entrypoint": "strategy.pipeline.generate_trading_signal"},
    )

    return engine


def build_backtest_result(
    dataset: CandleDatasetSnapshot, engine: BacktestEngine, strategy: dict
) -> BacktestResult:
    pnls = [trade.net_pnl for trade in engine.trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    break_even = len(pnls) - len(wins) - len(losses)
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    if gross_loss:
        profit_factor, pf_status = gross_profit / gross_loss, "DEFINED"
    elif gross_profit:
        profit_factor, pf_status = None, "POSITIVE_WITHOUT_LOSSES"
    else:
        profit_factor, pf_status = None, "UNDEFINED_NO_PROFIT_OR_LOSS"
    peak = engine.equity_curve[0]
    max_dd = max_dd_pct = 0.0
    for balance in engine.equity_curve:
        peak = max(peak, balance)
        drawdown = peak - balance
        if drawdown > max_dd:
            max_dd, max_dd_pct = drawdown, (drawdown / peak * 100.0 if peak else 0.0)
    max_wins = max_losses = win_run = loss_run = 0
    for pnl in pnls:
        win_run, loss_run = ((win_run + 1, 0) if pnl > 0 else (0, loss_run + 1) if pnl < 0 else (0, 0))
        max_wins, max_losses = max(max_wins, win_run), max(max_losses, loss_run)
    count = len(pnls)
    return BacktestResult(
        provider=dataset.provider, symbol=dataset.symbol, timeframe=dataset.timeframe,
        dataset_start=dataset.start, dataset_end=dataset.end, candle_count=len(dataset.candles),
        initial_capital=engine.starting_balance, strategy=dict(strategy),
        risk=engine.risk_configuration, execution=engine.execution_assumptions,
        ending_capital=engine.balance, absolute_pnl=engine.balance-engine.starting_balance,
        return_percent=(engine.balance-engine.starting_balance)/engine.starting_balance*100,
        total_trades=count, winning_trades=len(wins), losing_trades=len(losses), break_even_trades=break_even,
        win_rate_percent=(len(wins)/count*100 if count else 0.0), gross_profit=gross_profit,
        gross_loss=gross_loss, profit_factor=profit_factor, profit_factor_status=pf_status,
        average_trade_pnl=(sum(pnls)/count if count else 0.0),
        average_winner=(sum(wins)/len(wins) if wins else None), average_loser=(sum(losses)/len(losses) if losses else None),
        largest_winner=(max(wins) if wins else None), largest_loser=(min(losses) if losses else None),
        expectancy=(sum(pnls)/count if count else 0.0), maximum_drawdown=max_dd,
        maximum_drawdown_percent=max_dd_pct, drawdown_basis="REALIZED_BALANCE",
        average_holding_candles=(sum(t.holding_candles for t in engine.trades)/count if count else 0.0),
        maximum_consecutive_wins=max_wins, maximum_consecutive_losses=max_losses,
        trades=tuple(engine.trades),
    )


if __name__ == "__main__":
    asyncio.run(run_backtest())
