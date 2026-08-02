"""JQE Trading Engine — main entry point.

Runs one market-analysis cycle:

    MT5 connection -> market data -> validation -> indicators ->
    regime detection

Run directly to execute a single cycle:

    $ python main.py

.. important::
    Signal generation, risk evaluation, and execution are **not yet
    wired in** here. The functions this module historically called
    (``generate_signal``, ``evaluate_trade``, ``ExecutionSimulator``)
    do not exist anywhere in the current codebase — the real
    equivalents (``strategy.signal_engine.SignalEngine.generate``,
    ``risk.risk_controller.approve_trade``,
    ``execution.simulator.simulate_trade``) take different arguments
    entirely (an "intelligence" dict, not a DataFrame + regime
    string). Wiring these together correctly is a trading-logic
    integration decision, not a Foundation-milestone concern — see
    "Pipeline Integration" in docs/roadmap.md.
"""

from __future__ import annotations

import pandas as pd

from config import settings
from core.data_validator import validate_market_data
from core.exceptions import BrokerConnectionError, JQEError, MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.market_data import MarketData
from core.mt5_connection import connect, disconnect
from core.regime import detect_regime


def run() -> None:
    """Runs a single JQE market-analysis cycle.

    Connects to the MT5 terminal, retrieves and validates recent
    candles, computes indicators, and detects the current market
    regime. The MT5 connection is always closed on the way out,
    whether the cycle succeeds or fails.

    Raises:
        BrokerConnectionError: If the MT5 terminal connection cannot be
            established.
        MarketDataError: If market data cannot be retrieved or fails
            validation.
    """
    logger.info("JQE engine online (environment={})", settings.environment)

    if not connect():
        raise BrokerConnectionError("Failed to connect to MT5 terminal")

    try:
        # NOTE: MarketData currently fetches on a fixed H1 timeframe
        # internally and does not yet accept settings.default_timeframe.
        # Making the timeframe configurable is tracked for Milestone 2
        # (Broker Abstraction) — see docs/roadmap.md.
        market_data_provider = MarketData()
        candles = market_data_provider.get_candles(
            symbol=settings.default_symbol,
            count=settings.default_candle_count,
        )
        if not candles:
            raise MarketDataError("Market data unavailable", symbol=settings.default_symbol)

        df = pd.DataFrame(candles)

        if not validate_market_data(df):
            raise MarketDataError("Market data failed validation", symbol=settings.default_symbol)

        df = calculate_indicators(df)
        regime = detect_regime(df)

        logger.info("Market regime: {}", regime)
        logger.info("Latest candle: {}", df.iloc[-1].to_dict())
        logger.warning(
            "Signal generation, risk evaluation, and execution are not yet "
            "wired to the current module APIs — see 'Pipeline Integration' "
            "in docs/roadmap.md. Cycle stops after market analysis."
        )
    finally:
        disconnect()


def main() -> None:
    """CLI entry point. Runs one cycle and logs any platform-level failure.

    Platform errors (:class:`~core.exceptions.JQEError` and subclasses)
    are caught and logged here rather than propagating as an unhandled
    traceback, since this is the outermost boundary of the application.
    Unexpected (non-platform) exceptions are intentionally left to
    propagate.
    """
    try:
        run()
    except JQEError as exc:
        logger.error("JQE cycle aborted: {}", exc)


if __name__ == "__main__":
    main()
