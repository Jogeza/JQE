"""JQE institutional backtest runner.

Loads historical candle data via the configured
:class:`broker.base.BrokerGateway` (``simulation`` by default, so this
runs with no credentials or live broker connection), then replays
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
from broker.factory import get_gateway
from broker.types import Timeframe
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from strategy.pipeline import generate_trading_signal

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = Timeframe.M5
DEFAULT_CANDLES = 5000

# Indicators (EMA200, rolling ATR/RSI at window 14) need this many
# leading candles before their values are meaningful — trades aren't
# evaluated before this point.
_WARMUP_CANDLES = 200


async def run_backtest(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: Timeframe = DEFAULT_TIMEFRAME,
    candles: int = DEFAULT_CANDLES,
    starting_balance: float = 50.0,
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
        core.exceptions.BrokerConnectionError: If the broker connection
            cannot be established.
        core.exceptions.MarketDataError: If historical market data
            cannot be retrieved, or there isn't enough of it to clear
            the indicator warmup period.
    """
    logger.info("JQE backtest starting for {} ({} candles)", symbol, candles)

    gateway = get_gateway()
    async with gateway:
        raw_candles = await gateway.get_candles(symbol=symbol, timeframe=timeframe, count=candles)
        if not raw_candles:
            raise MarketDataError("No market data returned", symbol=symbol)

        df = pd.DataFrame([candle.model_dump() for candle in raw_candles])
        df = calculate_indicators(df)

        if len(df) <= _WARMUP_CANDLES:
            raise MarketDataError(
                "Not enough candles to clear the indicator warmup period",
                symbol=symbol,
                candles=len(df),
                warmup_required=_WARMUP_CANDLES,
            )

        engine = BacktestEngine(starting_balance=starting_balance)

        for i in range(_WARMUP_CANDLES, len(df)):
            history = df.iloc[: i + 1]
            regime = detect_regime(history)
            signal = generate_trading_signal(history, symbol, regime=regime)
            engine.execute_trade(signal, i, df)

        basic_stats = engine.statistics()
        logger.info("JQE backtest results: {}", basic_stats)

        if engine.trades:
            institutional_metrics = calculate_performance(engine.trades, engine.equity_curve)
            logger.info("Institutional metrics: {}", institutional_metrics)
        else:
            logger.warning("No trades were taken during this backtest run")

        return engine


if __name__ == "__main__":
    asyncio.run(run_backtest())
