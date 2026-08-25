"""JQE Trading Engine — main entry point.

Runs one full JQE cycle against the configured broker:

    BrokerGateway connect -> candles -> validation -> indicators ->
    regime detection -> signal generation -> risk evaluation ->
    (if approved) order submission

The broker is fully interchangeable — this module depends only on
:class:`broker.base.BrokerGateway`, selected at runtime by
``config.settings.broker`` (``simulation`` by default, so this runs
out of the box with no credentials). See docs/architecture.md, "Broker
layer".

Run directly to execute a single cycle:

    $ python main.py
"""

from __future__ import annotations

import asyncio

import pandas as pd

from broker.factory import get_gateway
from broker.types import OrderRequest, OrderSide, Timeframe
from config import settings
from core.data_validator import validate_market_data
from core.exceptions import JQEError, MarketDataError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from intelligence.trade_plan import TradePlanBuilder
from risk.risk_controller import approve_trade, reconcile_daily_history
from strategy.pipeline import generate_trading_signal

_TIMEFRAME_BY_NAME: dict[str, Timeframe] = {tf.value: tf for tf in Timeframe}
_SIDE_BY_SIGNAL: dict[str, OrderSide] = {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}


async def run() -> None:
    """Runs a single JQE analysis-and-trade cycle end to end.

    Connects to the configured broker, retrieves and validates recent
    candles, computes indicators and regime, generates a trading
    signal, evaluates it through the risk engine, and — if approved —
    submits an order through the broker gateway. The broker connection
    is always closed on the way out (via the gateway's async context
    manager), whether the cycle succeeds or fails.

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
        signal = generate_trading_signal(df, settings.default_symbol, regime=regime)

        logger.info("Market regime: {}", regime)
        logger.info("Trading signal: {}", signal)

        account = await gateway.get_account_info()
        trades = await gateway.get_trade_history(count=500)
        reconcile_daily_history(trades, balance=account.balance)

        risk_decision = approve_trade(
            {"signal": signal["signal"], "confidence": signal["confidence"]},
            df,
            balance=account.balance,
            enforce_limits=True,
        )
        logger.info("Risk decision: {}", risk_decision)

        if not risk_decision["approved"]:
            logger.info("Cycle complete — no order submitted ({})", risk_decision["reason"])
            return

        latest = df.iloc[-1]
        builder = TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0)

        # Fallback to df for intelligence if missing ATR
        intelligence = signal.get("intelligence", {})
        if "atr" not in intelligence and "ATR" not in intelligence and "ATR_14" not in intelligence:
            intelligence["atr"] = latest.get("ATR", latest.get("ATR_14"))

        plan = builder.build(
            symbol=settings.default_symbol,
            intelligence=intelligence,
            signal_dict=signal,
            price=latest["close"],
            account_balance=account.balance,
            risk_percent=risk_decision["risk_percent"],
        )

        if not plan.is_valid():
            logger.info(
                "Cycle complete — Trade plan invalid: {}",
                ", ".join(plan.warnings) if plan.warnings else plan.invalidation,
            )
            return

        order = OrderRequest(
            symbol=plan.symbol,
            side=_SIDE_BY_SIGNAL[plan.signal],
            volume=plan.position_size,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
        )
        result = await gateway.submit_order(order)
        logger.info("Order result: {}", result)


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
