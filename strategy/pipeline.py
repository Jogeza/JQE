"""Bridges JQE's market-intelligence/decision layer to its risk and
execution layers.

This module exists because several pieces of pre-existing code were
written independently and never integrated — each expects a slightly
different shape:

* :class:`strategy.features.feature_engine.FeatureEngine` needs OHLC
  data with columns named ``EMA_50``, ``EMA_200``, ``RSI_14``,
  ``ATR_14``.
* :func:`core.indicators.calculate_indicators` (the indicator
  calculator actually used by ``main.py``/``backtesting/backtest.py``)
  produces columns named ``EMA50``, ``EMA200``, ``RSI``, ``ATR`` — no
  underscore, no period suffix.
* ``FeatureEngine.analyze()`` never sets a ``"regime"`` key on the
  intelligence dict it builds. :class:`strategy.signal_engine.
  SignalEngine` branches almost entirely on that key — without it,
  every signal falls through to its ``else`` branch and
  ``SignalEngine`` can only ever return ``"WAIT"``, regardless of
  trend/momentum. This module fills it in using the already-tested
  :func:`core.regime.detect_regime` (the same function ``main.py``
  already calls), mapped onto the vocabulary ``SignalEngine`` expects
  (``"TRENDING"``/``"RANGING"``/``"UNKNOWN"``) — reusing existing,
  tested regime-detection logic rather than inventing new
  classification rules.
* :class:`strategy.signal_engine.SignalEngine` returns a signal dict
  keyed ``"action"`` (``"BUY"``/``"SELL"``/``"WAIT"``);
  :func:`risk.risk_controller.approve_trade` and
  :func:`execution.simulator.simulate_trade` both expect a signal dict
  keyed ``"signal"`` (``"BUY"``/``"SELL"``/``"NO_TRADE"``).

Given all of the above, :func:`generate_trading_signal` calls
``FeatureEngine``, ``SignalEngine``, and ``SignalScorer`` directly
rather than through :class:`core.decision_pipeline.DecisionPipeline` —
``DecisionPipeline``'s own "scanner intelligence" (dict) branch expects
yet another, different confidence key (``"market_score"``) than
``FeatureEngine`` produces (``"confidence"``), which would silently
zero out confidence if routed through it. This is a known, documented
inconsistency — see "Deliberately not touched" in docs/architecture.md
for the status of ``DecisionPipeline`` itself.
"""

from __future__ import annotations

import pandas as pd

from core.regime import detect_regime
from strategy.features.feature_engine import FeatureEngine
from strategy.scoring.signal_scorer import SignalScorer
from strategy.signal_engine import SignalEngine

#: Maps calculate_indicators()'s column names to the names
#: FeatureEngine.analyze() expects.
_INDICATOR_COLUMN_ALIASES: dict[str, str] = {
    "EMA50": "EMA_50",
    "EMA200": "EMA_200",
    "RSI": "RSI_14",
    "ATR": "ATR_14",
}

#: Maps core.regime.detect_regime()'s output to the regime vocabulary
#: SignalEngine.generate() branches on.
_REGIME_MAP: dict[str, str] = {
    "TREND_UP": "TRENDING",
    "TREND_DOWN": "TRENDING",
    "RANGE": "RANGING",
    "NO_TRADE": "UNKNOWN",
}

#: Maps SignalEngine's "action" values to the "signal" values
#: risk_controller/simulator expect. WAIT has no direct equivalent in
#: their vocabulary; NO_TRADE is the sentinel both already treat as
#: "do nothing" (risk_controller via its BUY/SELL membership check,
#: simulator identically, and BacktestEngine via an explicit early
#: return on this exact value).
_ACTION_TO_SIGNAL: dict[str, str] = {
    "BUY": "BUY",
    "SELL": "SELL",
    "WAIT": "NO_TRADE",
}


def generate_trading_signal(
    df: pd.DataFrame, symbol: str = "UNKNOWN", regime: str | None = None
) -> dict:
    """Generates a risk/execution-ready trading signal from indicator data.

    Runs the existing market-intelligence pipeline (``FeatureEngine``
    -> ``SignalEngine`` -> ``SignalScorer``) and translates its output
    into the shape :func:`risk.risk_controller.approve_trade` and
    :func:`execution.simulator.simulate_trade` already expect. See the
    module docstring for why each translation is needed.

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
    if "ATR" not in df.columns:
        raise KeyError("calculate_indicators() output is required (missing ATR column)")

    rename_map = {k: v for k, v in _INDICATOR_COLUMN_ALIASES.items() if v not in df.columns}
    aliased = df.rename(columns=rename_map)
    intelligence = FeatureEngine().analyze(aliased)

    raw_regime = regime if regime is not None else detect_regime(df)
    intelligence["regime"] = _REGIME_MAP.get(raw_regime, "UNKNOWN")

    signal = SignalEngine().generate(intelligence)
    decision = SignalScorer().evaluate(intelligence, signal)

    action = signal.get("action", "WAIT")
    return {
        "signal": _ACTION_TO_SIGNAL.get(action, "NO_TRADE"),
        "confidence": signal.get("confidence", 0),
        "quality": decision.get("quality", "POOR"),
        "score": decision.get("score", 0),
        "reasons": decision.get("reasons", []),
        "intelligence": intelligence,
    }
