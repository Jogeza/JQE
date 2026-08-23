"""JQE Canonical Strategy Engine.

Orchestrates market intelligence, institutional confidence modeling,
regime detection, signal generation, quality scoring, and trade plan
construction into a single authoritative strategy pipeline.

Flow:
    Market Data (OHLC DataFrame)
        ↓
    Feature / Technical Indicators
        ↓
    Market Intelligence (Trend, Momentum, Volatility, Liquidity, Structure, Risk Conditions)
        ↓
    Institutional ConfidenceModel (6-Factor Breakdown: 0-100)
        ↓
    Regime Alignment (Canonical Vocabulary: TRENDING, RANGING, HIGH_VOLATILITY, UNKNOWN)
        ↓
    Signal Generation & Strategy Selection (BUY / SELL / NO_TRADE)
        ↓
    Quality & Reasons Scoring (SignalScorer)
        ↓
    TradePlan Construction (Entry, ATR-based SL/TP, R:R >= 1.5, Direction Invariants)
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from config.settings import settings
from core.regime import detect_regime as detect_default_regime
from intelligence.confidence_model import (
    ConfidenceBreakdown,
    ConfidenceModel,
    classify_risk_conditions,
    classify_structure,
)
from intelligence.liquidity_engine import LiquidityEngine
from intelligence.trade_plan import TradePlan, TradePlanBuilder
from strategy.features.feature_engine import FeatureEngine
from strategy.scoring.signal_scorer import SignalScorer
from strategy.signal_engine import SignalEngine


class RegimeTranslator:
    """Translates legacy and external regime classifications to canonical vocabulary."""

    _CANONICAL_MAP: dict[str, str] = {
        "TREND_UP": "TRENDING",
        "TREND_DOWN": "TRENDING",
        "RANGE": "RANGING",
        "SIDEWAYS": "RANGING",
        "TRENDING": "TRENDING",
        "RANGING": "RANGING",
        "HIGH_VOLATILITY": "HIGH_VOLATILITY",
        "NO_TRADE": "UNKNOWN",
        "UNKNOWN": "UNKNOWN",
    }

    @classmethod
    def to_canonical(cls, raw_regime: str | None) -> str:
        """Translates any known regime representation into canonical vocabulary.

        Returns:
            One of ``"TRENDING"``, ``"RANGING"``, ``"HIGH_VOLATILITY"``, or ``"UNKNOWN"``.
        """
        if not raw_regime:
            return "UNKNOWN"
        return cls._CANONICAL_MAP.get(str(raw_regime).upper(), "UNKNOWN")


class StrategyDecision(BaseModel):
    """Authoritative strategy decision and complete context."""

    symbol: str
    signal: Literal["BUY", "SELL", "NO_TRADE"]
    confidence: int = Field(ge=0, le=100)
    quality: str = Field(default="POOR")
    score: int = Field(default=0)
    reasons: list[str] = Field(default_factory=list)
    intelligence: dict[str, Any] = Field(default_factory=dict)
    confidence_breakdown: ConfidenceBreakdown | None = None
    trade_plan: TradePlan | None = None
    strategy_name: str = "TrendContinuation"

    def to_pipeline_dict(self) -> dict[str, Any]:
        """Converts the decision to the dictionary shape expected by existing callers.

        Compatible with ``risk.risk_controller.approve_trade``,
        ``execution.simulator.simulate_trade``, and ``strategy.pipeline.generate_trading_signal``.
        """
        return {
            "signal": self.signal,
            "confidence": self.confidence,
            "quality": self.quality,
            "score": self.score,
            "reasons": self.reasons,
            "intelligence": self.intelligence,
        }


class StrategyEngine:
    """Canonical Quant Strategy Engine coordinating intelligence, confidence, and signal decisions."""

    _COLUMN_ALIASES: dict[str, str] = {
        "EMA50": "EMA_50",
        "EMA200": "EMA_200",
        "RSI": "RSI_14",
        "ATR": "ATR_14",
    }

    _ACTION_TO_SIGNAL: dict[str, Literal["BUY", "SELL", "NO_TRADE"]] = {
        "BUY": "BUY",
        "SELL": "SELL",
        "WAIT": "NO_TRADE",
    }

    def __init__(
        self,
        min_confidence: int | None = None,
        confidence_model: ConfidenceModel | None = None,
        feature_engine: FeatureEngine | None = None,
        signal_engine: SignalEngine | None = None,
        signal_scorer: SignalScorer | None = None,
        liquidity_engine: LiquidityEngine | None = None,
        trade_plan_builder: TradePlanBuilder | None = None,
    ) -> None:
        """Initializes the StrategyEngine with its dependent analyzers and models."""
        self.min_confidence = (
            min_confidence if min_confidence is not None else settings.min_confidence_threshold
        )
        self.confidence_model = confidence_model or ConfidenceModel()
        self.feature_engine = feature_engine or FeatureEngine()
        self.signal_engine = signal_engine or SignalEngine()
        self.signal_scorer = signal_scorer or SignalScorer()
        self.liquidity_engine = liquidity_engine or LiquidityEngine()
        self.trade_plan_builder = trade_plan_builder or TradePlanBuilder()

    def evaluate(
        self,
        df: pd.DataFrame,
        symbol: str = "UNKNOWN",
        regime: str | None = None,
        price: float | None = None,
        spread: float | None = None,
        account_balance: float | None = None,
    ) -> StrategyDecision:
        """Runs the canonical strategy decision pipeline.

        Args:
            df: OHLC DataFrame with indicator columns (EMA50/EMA_50, EMA200/EMA_200,
                RSI/RSI_14, ATR/ATR_14).
            symbol: Instrument symbol.
            regime: Pre-computed or caller-provided regime string.
            price: Current market price (defaults to latest close if not supplied).
            spread: Current market spread for liquidity and risk classification.
            account_balance: Optional account balance for TradePlan sizing.

        Returns:
            A populated :class:`StrategyDecision`.

        Raises:
            KeyError: If neither ``ATR`` nor ``ATR_14`` is found in ``df``.
        """
        if "ATR" not in df.columns and "ATR_14" not in df.columns:
            raise KeyError("calculate_indicators() output is required (missing ATR column)")

        # 1. Column aliasing for feature engine
        rename_map = {k: v for k, v in self._COLUMN_ALIASES.items() if v not in df.columns}
        aliased = df.rename(columns=rename_map)

        # 2. Extract base features
        intelligence = self.feature_engine.analyze(aliased)
        latest = df.iloc[-1]
        current_price = price if price is not None else float(latest["close"])
        latest_atr = float(latest.get("ATR", latest.get("ATR_14", 0.0)))
        current_spread = spread if spread is not None else float(latest.get("spread", 1.0))
        latest_rsi = float(latest.get("RSI", latest.get("RSI_14", 50.0)))

        # Enforce canonical intelligence fields for downstream consumers
        intelligence["atr"] = latest_atr
        intelligence["ATR"] = latest_atr
        intelligence["rsi"] = latest_rsi
        intelligence["price"] = current_price
        intelligence["spread"] = current_spread

        # 3. Canonical Regime Translation
        if regime is not None:
            canonical_regime = RegimeTranslator.to_canonical(regime)
        else:
            raw_detected = detect_default_regime(df)
            canonical_regime = RegimeTranslator.to_canonical(raw_detected)
        intelligence["regime"] = canonical_regime

        # 4. Multi-Factor Market Intelligence & 6-Factor Confidence Model
        trend = intelligence.get("trend", "UNKNOWN")
        momentum = intelligence.get("momentum", "UNKNOWN")
        
        volatility_raw = intelligence.get("volatility", "UNKNOWN")
        volatility_score_tier = "MEDIUM" if volatility_raw in ("NORMAL", "MEDIUM") else volatility_raw

        liq_analysis = self.liquidity_engine.analyze(current_spread)
        liquidity = liq_analysis.get("liquidity", "GOOD")
        intelligence["liquidity"] = liquidity

        # Candle format for structure classifier
        candles: list[dict[str, Any]] = [
            {"high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"])}
            for _, r in df.tail(30).iterrows()
        ]
        structure = classify_structure(candles)
        intelligence["structure"] = structure

        risk_condition = classify_risk_conditions(
            spread=current_spread, atr=latest_atr, price=current_price
        )
        intelligence["risk_condition"] = risk_condition

        # Compute 6-Factor Confidence Breakdown
        breakdown = self.confidence_model.calculate(
            trend=trend,
            structure=structure,
            liquidity=liquidity,
            momentum=momentum,
            volatility=volatility_score_tier,
            risk=risk_condition,
        )
        intelligence["confidence_breakdown"] = breakdown.model_dump()
        intelligence["institutional_confidence"] = breakdown.total

        # 5. Signal Engine & Scoring
        raw_signal = self.signal_engine.generate(intelligence)
        decision_score = self.signal_scorer.evaluate(intelligence, raw_signal)

        raw_action = raw_signal.get("action", "WAIT")
        canonical_signal = self._ACTION_TO_SIGNAL.get(raw_action, "NO_TRADE")

        # Confidence: Maintain backwards-compatible confidence score while recording institutional breakdown
        confidence_val = raw_signal.get("confidence", 0)
        quality = decision_score.get("quality", "POOR")
        score = decision_score.get("score", 0)
        reasons = decision_score.get("reasons", [])

        # 6. Trade Plan Construction
        signal_dict_for_plan = {
            "signal": canonical_signal,
            "confidence": confidence_val,
            "quality": quality,
            "score": score,
            "reasons": reasons,
        }
        trade_plan = self.trade_plan_builder.build(
            symbol=symbol,
            intelligence=intelligence,
            signal_dict=signal_dict_for_plan,
            price=current_price,
            account_balance=account_balance,
        )

        return StrategyDecision(
            symbol=symbol,
            signal=canonical_signal,
            confidence=confidence_val,
            quality=quality,
            score=score,
            reasons=reasons,
            intelligence=intelligence,
            confidence_breakdown=breakdown,
            trade_plan=trade_plan,
            strategy_name="TrendContinuation",
        )
