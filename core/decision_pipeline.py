"""JQE Decision Pipeline.

Orchestrates the market-intelligence → signal → scoring chain.

Version history
---------------
0.2.0  Original — fragile ``decide(*args)`` positional sniffing.
0.3.0  (this version) — explicit ``decide(signal, score, risk, ...)``
       interface; ``*args`` sniffing removed; values are no longer
       silently discarded.

The pipeline has two entry points:

``analyze(data, symbol)``
    Full pipeline: raw DataFrame or pre-classified intelligence dict →
    feature extraction → signal generation → scoring → result dict.
    Used by :class:`core.engine.JQEEngine` and future scan loops.

``decide(signal, score, risk, market_data, symbol)``
    Explicit interface for callers that have already generated a
    signal+score and want a final decision.  Previously accepted
    ``*args`` and positionally sniffed for a string (symbol) vs. data,
    silently discarding ``score`` and ``risk`` if passed.  This version
    requires all inputs by name.
"""

from __future__ import annotations

from typing import Any

from strategy.features.feature_engine import FeatureEngine
from strategy.scoring.signal_scorer import SignalScorer
from strategy.signal_engine import SignalEngine


class DecisionPipeline:
    """Market-intelligence → signal → scoring pipeline."""

    def __init__(self) -> None:
        self.feature_engine = FeatureEngine()
        self.signal_engine = SignalEngine()
        self.signal_scorer = SignalScorer()

    # ------------------------------------------------------------------
    # Full pipeline — DataFrame or intelligence-dict input
    # ------------------------------------------------------------------

    def analyze(self, data: Any, symbol: str = "UNKNOWN") -> dict:
        """Runs the full pipeline on raw market data or a scanner dict.

        Args:
            data: Either a pandas DataFrame (OHLC + indicator columns
                named ``EMA_50``, ``EMA_200``, ``RSI_14``, ``ATR_14``)
                or a scanner-produced intelligence dict containing
                ``"trend"``, ``"momentum"``, ``"volatility"``,
                ``"regime"``, and ``"market_score"`` keys.
            symbol: Instrument symbol for context/logging.

        Returns:
            ``{symbol, intelligence, signal, decision}``
        """
        if hasattr(data, "iloc"):
            # ---- DataFrame mode ----
            intelligence = self.feature_engine.analyze(data)

        elif isinstance(data, dict):
            # ---- Scanner intelligence mode ----
            intelligence = {
                "trend": data.get("trend", "UNKNOWN"),
                "momentum": data.get("momentum", "UNKNOWN"),
                "volatility": data.get("volatility", "UNKNOWN"),
                "regime": data.get("regime", "TRENDING"),
                "confidence": data.get("market_score", 0),
            }

        else:
            intelligence = {
                "trend": "UNKNOWN",
                "momentum": "UNKNOWN",
                "volatility": "UNKNOWN",
                "regime": "UNKNOWN",
                "confidence": 0,
            }

        signal = self.signal_engine.generate(intelligence)
        decision = self.signal_scorer.evaluate(intelligence, signal)

        return {
            "symbol": symbol,
            "intelligence": intelligence,
            "signal": signal,
            "decision": decision,
        }

    # ------------------------------------------------------------------
    # Explicit decision interface (replaces fragile *args sniffing)
    # ------------------------------------------------------------------

    def decide(
        self,
        signal: Any,
        score: Any,
        risk: Any,
        market_data: Any = None,
        symbol: str = "UNKNOWN",
    ) -> dict:
        """Evaluates a pre-generated signal through the scoring layer.

        All arguments are now explicit and named — no positional
        sniffing.  ``signal``, ``score``, and ``risk`` are all
        consumed and returned in the result so callers can verify
        they were actually used.

        Args:
            signal: Strategy signal payload (e.g. ``{"action": "BUY",
                "confidence": 80}``).
            score: Signal confidence/score payload (e.g. from
                :class:`strategy.scoring.signal_scorer.SignalScorer`).
            risk: Risk context payload (e.g. from
                :func:`risk.risk_controller.approve_trade`).
            market_data: Optional additional market data for context.
            symbol: Instrument symbol.

        Returns:
            ``{"action", "score", "quality", "confidence", "reasons",
            "signal_input", "score_input", "risk_input"}`` — the
            ``*_input`` keys let callers confirm the values were
            received rather than dropped.
        """
        if signal is None and market_data is None:
            return {
                "action": "WAIT",
                "confidence": 0,
                "score": 0,
                "quality": "POOR",
                "signal_input": None,
                "score_input": score,
                "risk_input": risk,
            }

        # If we have raw market data, run the full analysis pipeline.
        if market_data is not None:
            result = self.analyze(market_data, symbol)
            decision = result["decision"]
        else:
            # Use the pre-supplied signal directly.
            intelligence: dict = {}
            if isinstance(signal, dict):
                intelligence = {
                    "trend": signal.get("trend", "UNKNOWN"),
                    "momentum": signal.get("momentum", "UNKNOWN"),
                    "volatility": signal.get("volatility", "UNKNOWN"),
                    "regime": signal.get("regime", "UNKNOWN"),
                    "confidence": signal.get("confidence", 0),
                }
            decision = self.signal_scorer.evaluate(intelligence, signal)

        # Attach the input values so callers can verify they were consumed.
        decision["signal_input"] = signal
        decision["score_input"] = score
        decision["risk_input"] = risk

        return decision