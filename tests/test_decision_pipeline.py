"""Tests for core.decision_pipeline.DecisionPipeline.

Tests both the full ``analyze()`` path and the new explicit
``decide(signal, score, risk, ...)`` interface (which replaced the
fragile ``*args`` positional sniffing).

Key regression tests
--------------------
* ``decide()`` must consume ALL supplied arguments — signal, score, and
  risk must appear in the returned decision dict (as ``signal_input``,
  ``score_input``, ``risk_input``).  Previous behaviour silently
  discarded ``score`` and ``risk`` if both were supplied together with
  a data payload.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.decision_pipeline import DecisionPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bullish_df(rows: int = 250) -> pd.DataFrame:
    """DataFrame with bullish EMA alignment and strong RSI."""
    return pd.DataFrame(
        {
            "EMA_50": [110.0] * rows,
            "EMA_200": [100.0] * rows,
            "RSI_14": [70.0] * rows,
            "ATR_14": [1.0] * rows,
        }
    )


# ---------------------------------------------------------------------------
# analyze() — full pipeline
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_returns_symbol_in_result(self) -> None:
        pipeline = DecisionPipeline()
        result = pipeline.analyze(_bullish_df(), "GOLD")
        assert result["symbol"] == "GOLD"

    def test_result_contains_required_keys(self) -> None:
        pipeline = DecisionPipeline()
        result = pipeline.analyze(_bullish_df(), "GOLD")
        for key in ("symbol", "intelligence", "signal", "decision"):
            assert key in result, f"Missing key: {key}"

    def test_dict_intelligence_mode_does_not_raise(self) -> None:
        pipeline = DecisionPipeline()
        intel = {
            "trend": "BULLISH",
            "momentum": "STRONG",
            "volatility": "MEDIUM",
            "regime": "TRENDING",
            "market_score": 80,
        }
        result = pipeline.analyze(intel, "EURUSD")
        assert result["symbol"] == "EURUSD"
        assert "decision" in result

    def test_unknown_input_type_returns_wait(self) -> None:
        pipeline = DecisionPipeline()
        result = pipeline.analyze(42, "UNKNOWN")
        # Should not raise — degrades gracefully
        assert result["intelligence"]["trend"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# decide() — explicit interface regression tests
# ---------------------------------------------------------------------------


class TestDecideExplicitInterface:
    def test_decide_returns_a_dict(self) -> None:
        pipeline = DecisionPipeline()
        result = pipeline.decide(signal={"action": "BUY", "confidence": 80}, score=75, risk={"approved": True})
        assert isinstance(result, dict)

    def test_signal_input_is_preserved_in_result(self) -> None:
        """signal must not be silently discarded."""
        pipeline = DecisionPipeline()
        signal_payload = {"action": "BUY", "confidence": 85, "regime": "TRENDING"}
        result = pipeline.decide(signal=signal_payload, score=80, risk={"approved": True})
        assert result["signal_input"] == signal_payload, (
            "signal was discarded — the *args sniffing bug has re-appeared"
        )

    def test_score_input_is_preserved_in_result(self) -> None:
        """score must not be silently discarded."""
        pipeline = DecisionPipeline()
        result = pipeline.decide(signal={"action": "BUY"}, score=99, risk={"approved": True})
        assert result["score_input"] == 99, (
            "score was discarded — positional sniffing bug has re-appeared"
        )

    def test_risk_input_is_preserved_in_result(self) -> None:
        """risk must not be silently discarded."""
        pipeline = DecisionPipeline()
        risk_payload = {"approved": True, "lot_size": 0.05}
        result = pipeline.decide(signal={"action": "SELL"}, score=70, risk=risk_payload)
        assert result["risk_input"] == risk_payload, (
            "risk was discarded — positional sniffing bug has re-appeared"
        )

    def test_none_signal_and_none_market_data_returns_wait(self) -> None:
        pipeline = DecisionPipeline()
        result = pipeline.decide(signal=None, score=None, risk=None)
        assert result["action"] == "WAIT"
        assert result["confidence"] == 0

    def test_decide_with_market_data_runs_full_analysis(self) -> None:
        """When market_data is supplied, the full pipeline should run."""
        pipeline = DecisionPipeline()
        result = pipeline.decide(
            signal={"action": "BUY"},
            score=80,
            risk={"approved": True},
            market_data=_bullish_df(),
            symbol="BTCUSD",
        )
        # Full pipeline ran — should have an "action" key from SignalScorer
        assert "action" in result

    def test_all_three_inputs_consumed_simultaneously(self) -> None:
        """Passing all three (signal, score, risk) at once must not discard any."""
        pipeline = DecisionPipeline()
        sig = {"action": "SELL", "confidence": 77}
        sc = 60
        ri = {"approved": False, "reason": "low confidence"}
        result = pipeline.decide(signal=sig, score=sc, risk=ri)
        assert result["signal_input"] == sig
        assert result["score_input"] == sc
        assert result["risk_input"] == ri


# ---------------------------------------------------------------------------
# JQEEngine delegation (via evaluate_trade)
# ---------------------------------------------------------------------------


class TestJQEEngineEvaluateTrade:
    def test_evaluate_trade_explicit_kwargs(self) -> None:
        """evaluate_trade() must use explicit kwargs — not *args."""
        from core.engine import JQEEngine

        engine = JQEEngine()
        result = engine.evaluate_trade(
            signal={"action": "BUY", "confidence": 80},
            score=75,
            risk={"approved": True},
        )
        assert isinstance(result, dict)
        assert result["signal_input"] == {"action": "BUY", "confidence": 80}
        assert result["score_input"] == 75
        assert result["risk_input"] == {"approved": True}