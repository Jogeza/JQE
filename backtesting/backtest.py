"""JQE institutional backtest runner.

Loads historical candle data and computes indicators, as a foundation
for backtesting — via the configured :class:`broker.base.BrokerGateway`
(``simulation`` by default, so this runs with no credentials or live
broker connection at all).

Run as a script:

    $ python -m backtesting.backtest

Or call :func:`run_backtest` directly for programmatic use.

.. important::
    The trade-simulation loop is **not yet wired in** — see "Pipeline
    Integration" in docs/roadmap.md.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from broker.factory import get_gateway
from broker.types import Timeframe
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = Timeframe.M5
DEFAULT_CANDLES = 5000


async def run_backtest(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: Timeframe = DEFAULT_TIMEFRAME,
    candles: int = DEFAULT_CANDLES,
    starting_balance: float = 50.0,
) -> pd.DataFrame:
    """Loads historical data and computes indicators for backtesting.

    Args:
        symbol: Instrument symbol to backtest.
        timeframe: Candle timeframe.
        candles: Number of historical candles to load.
        starting_balance: Simulated starting account balance. Accepted
            for API stability; not yet used until the trade-simulation
            loop is wired in.

    Returns:
        The historical candle data with indicators applied.

    Raises:
        core.exceptions.BrokerConnectionError: If the broker connection
            cannot be established.
        core.exceptions.MarketDataError: If historical market data
            cannot be retrieved.
    """
    del starting_balance  # Reserved for the trade-simulation loop (not yet wired in).

    logger.info("JQE backtest data load starting for {} ({} candles)", symbol, candles)

    gateway = get_gateway()
    async with gateway:
        raw_candles = await gateway.get_candles(symbol=symbol, timeframe=timeframe, count=candles)
        if not raw_candles:
            raise MarketDataError("No market data returned", symbol=symbol)

        df = pd.DataFrame([candle.model_dump() for candle in raw_candles])
        df = calculate_indicators(df)

        logger.info("Loaded {} candles with indicators for {}", len(df), symbol)
        logger.warning(
            "Trade-simulation loop is not yet wired to the current "
            "strategy/risk/execution APIs — see 'Pipeline Integration' "
            "in docs/roadmap.md. Returning indicator data only."
        )
        return df


if __name__ == "__main__":
    asyncio.run(run_backtest())
