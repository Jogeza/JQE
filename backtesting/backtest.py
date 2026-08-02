"""JQE institutional backtest runner.

Loads historical candle data and computes indicators, as a foundation
for backtesting.

Run as a script:

    $ python -m backtesting.backtest

Or call :func:`run_backtest` directly for programmatic use.

.. important::
    The trade-simulation loop is **not yet wired in**. It previously
    called ``generate_signal(history, regime)``, a function that does
    not exist anywhere in the codebase — the real signal generator is
    ``strategy.signal_engine.SignalEngine.generate(intelligence)``,
    which takes a different kind of input entirely. Additionally,
    ``BacktestEngine.execute_trade`` itself calls
    ``risk.risk_controller.approve_trade`` and
    ``execution.simulator.simulate_trade`` with the wrong number of
    arguments for their current signatures. None of this is
    Foundation-milestone work; see "Pipeline Integration" in
    docs/roadmap.md.
"""

from __future__ import annotations

import MetaTrader5 as mt5
import pandas as pd

from core.exceptions import BrokerConnectionError, MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.market_data import MarketData

DEFAULT_SYMBOL = "XAUUSD"
DEFAULT_TIMEFRAME = mt5.TIMEFRAME_M5
DEFAULT_CANDLES = 5000


def run_backtest(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: int = DEFAULT_TIMEFRAME,
    candles: int = DEFAULT_CANDLES,
    starting_balance: float = 50.0,
) -> pd.DataFrame:
    """Loads historical data and computes indicators for backtesting.

    Args:
        symbol: Instrument symbol to backtest.
        timeframe: MT5 timeframe constant (e.g. ``mt5.TIMEFRAME_M5``).
            Accepted for API stability; not yet honored — see the
            module docstring.
        candles: Number of historical candles to load.
        starting_balance: Simulated starting account balance. Accepted
            for API stability; not yet used until the trade-simulation
            loop is wired in.

    Returns:
        The historical candle data with indicators applied.

    Raises:
        BrokerConnectionError: If the MT5 terminal connection cannot be
            established.
        MarketDataError: If historical market data cannot be retrieved.
    """
    del starting_balance  # Reserved for the trade-simulation loop (not yet wired in).

    logger.info("JQE backtest data load starting for {} ({} candles)", symbol, candles)

    if not mt5.initialize():
        raise BrokerConnectionError("MT5 connection failed")

    try:
        # NOTE: MarketData currently fetches on a fixed H1 timeframe
        # internally and does not yet accept a `timeframe` argument.
        # Tracked for Milestone 2 (Broker Abstraction).
        market_data_provider = MarketData()
        raw_candles = market_data_provider.get_candles(symbol, count=candles)
        if not raw_candles:
            raise MarketDataError("No market data returned", symbol=symbol)

        df = pd.DataFrame(raw_candles)
        df = calculate_indicators(df)

        logger.info("Loaded {} candles with indicators for {}", len(df), symbol)
        logger.warning(
            "Trade-simulation loop is not yet wired to the current "
            "strategy/risk/execution APIs — see 'Pipeline Integration' "
            "in docs/roadmap.md. Returning indicator data only."
        )
        return df
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    run_backtest()
