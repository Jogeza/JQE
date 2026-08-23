"""Bridges JQE's market-intelligence/decision layer to its risk and
execution layers.

This module provides the canonical functional entry point:
:func:`generate_trading_signal`, routing through :class:`strategy.strategy_engine.StrategyEngine`
which unifies FeatureEngine, SignalEngine, SignalScorer, ConfidenceModel (6-Factor),
Regime translation, and TradePlan generation.
"""

from __future__ import annotations

import pandas as pd

from strategy.strategy_engine import StrategyEngine

_default_engine = StrategyEngine()


def generate_trading_signal(
    df: pd.DataFrame, symbol: str = "UNKNOWN", regime: str | None = None
) -> dict:
    """Generates a risk/execution-ready trading signal from indicator data.

    Routes through the canonical :class:`strategy.strategy_engine.StrategyEngine`
    and returns the standard signal dictionary shape expected by
    :func:`risk.risk_controller.approve_trade` and
    :func:`execution.simulator.simulate_trade`.

    Args:
        df: OHLC data with indicator columns as produced by
            :func:`core.indicators.calculate_indicators` (``EMA50``,
            ``EMA200``, ``RSI``, ``ATR``).
        symbol: Instrument symbol, for logging/context only.
        regime: Pre-computed regime from :func:`core.regime.
            detect_regime`, if the caller already has one (e.g. for
            logging) — avoids detecting it twice. Computed internally
            if not given.

    Returns:
        A dict with:

        * ``signal``: ``"BUY"``, ``"SELL"``, or ``"NO_TRADE"`` — ready
          for ``approve_trade``/``simulate_trade``.
        * ``confidence``: 0-100, from ``FeatureEngine``.
        * ``quality``: ``SignalScorer``'s quality label
          (``"HIGH"``/``"GOOD"``/``"WEAK"``/``"POOR"``).
        * ``score``: ``SignalScorer``'s numeric score.
        * ``reasons``: ``SignalScorer``'s list of contributing reasons.
        * ``intelligence``: the trend/momentum/volatility/regime/
          confidence dict fed to ``SignalEngine``, for logging.

    Raises:
        KeyError: If ``df`` is missing the ``ATR`` column (i.e. wasn't
            produced by ``calculate_indicators``).
    """
    if "ATR" not in df.columns and "ATR_14" not in df.columns:
        raise KeyError("calculate_indicators() output is required (missing ATR column)")

    decision = _default_engine.evaluate(df=df, symbol=symbol, regime=regime)
    return decision.to_pipeline_dict()
