"""JQE Trading Engine — main entry point.

Runs one market-analysis cycle against the configured broker:

    BrokerGateway connect -> candles -> validation -> indicators ->
    regime detection

The broker is fully interchangeable — this module depends only on
:class:`broker.base.BrokerGateway`, selected at runtime by
``config.settings.broker`` (``simulation`` by default, so this runs
out of the box with no credentials). See docs/architecture.md, "Broker
layer".

Run directly to execute a single cycle:

    $ python main.py

.. important::
    Signal generation, risk evaluation, and execution are **not yet
    wired in** — see "Pipeline Integration" in docs/roadmap.md.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from broker.factory import get_gateway
from broker.types import Timeframe
from config import settings
from core.data_validator import validate_market_data
from core.exceptions import JQEError, MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime

_TIMEFRAME_BY_NAME: dict[str, Timeframe] = {tf.value: tf for tf in Timeframe}


async def run() -> None:
    """Runs a single JQE market-analysis cycle.

    Connects to the configured broker, retrieves and validates recent
    candles, computes indicators, and detects the current market
    regime. The broker connection is always closed on the way out
    (via the gateway's async context manager), whether the cycle
    succeeds or fails.

    Raises:
        core.exceptions.BrokerConnectionError: If the broker connection
            cannot be established.
        core.exceptions.MarketDataError: If market data cannot be
            retrieved or fails validation.
    """
    logger.info(
        "JQE engine online (environment={}, broker={})", settings.environment, settings.broker
    )

    timeframe = _TIMEFRAME_BY_NAME.get(settings.default_timeframe, Timeframe.H1)

    gateway = get_gateway(settings)
    async with gateway:
        candles = await gateway.get_candles(
            symbol=settings.default_symbol,
            timeframe=timeframe,
            count=settings.default_candle_count,
        )
        if not candles:
            raise MarketDataError("Market data unavailable", symbol=settings.default_symbol)

        df = pd.DataFrame([candle.model_dump() for candle in candles])

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


def main() -> None:
    """CLI entry point. Runs one cycle and logs any platform-level failure.

    Platform errors (:class:`~core.exceptions.JQEError` and subclasses)
    are caught and logged here rather than propagating as an unhandled
    traceback, since this is the outermost boundary of the application.
    Unexpected (non-platform) exceptions are intentionally left to
    propagate.
    """
    try:
        asyncio.run(run())
    except JQEError as exc:
        logger.error("JQE cycle aborted: {}", exc)


if __name__ == "__main__":
    main()
