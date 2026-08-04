"""JQE Confidence Model.

Computes a weighted institutional confidence score (0-100) from six
market-intelligence factors, per JQE's Quant Intelligence Engine
design:

    Trend       +25
    Structure   +20
    Liquidity   +20
    Momentum    +15
    Volatility  +10
    Risk        +10
    -----------------
    Total       100

A trade should only be considered when the total meets a configured
threshold (see ``config.settings.min_confidence_threshold``).

This supersedes :class:`intelligence.market_score.MarketScore`'s
older 4-factor design (trend/volatility/liquidity/momentum, no
structure or risk), which is kept only because
:class:`intelligence.market_state.MarketState` still depends on it —
see that module's docstring. Actually wiring ``ConfidenceModel`` into
the live signal-generation path (replacing
``strategy.pipeline.generate_trading_signal``'s current
``FeatureEngine``-based confidence) is Phase 5 (Strategy Engine) work,
not this milestone's.

.. important::
    ``structure`` and ``risk`` have no dedicated analyzer elsewhere in
    the codebase yet — the target architecture's ``pattern_engine.py``
    (structure/pattern detection) was explicitly deferred out of this
    milestone's scope (see docs/roadmap.md). :func:`classify_structure`
    and :func:`classify_risk_conditions` below are simple, transparent,
    rule-based proxies — not statistically validated, not chart-pattern
    aware — clearly separated into their own functions so a future
    ``pattern_engine.py``/proper risk analysis can replace just the
    classification step without touching ``ConfidenceModel`` itself.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ==========================
# WEIGHTS
# ==========================

TREND_WEIGHT = 25
STRUCTURE_WEIGHT = 20
LIQUIDITY_WEIGHT = 20
MOMENTUM_WEIGHT = 15
VOLATILITY_WEIGHT = 10
RISK_WEIGHT = 10

TOTAL_WEIGHT = (
    TREND_WEIGHT
    + STRUCTURE_WEIGHT
    + LIQUIDITY_WEIGHT
    + MOMENTUM_WEIGHT
    + VOLATILITY_WEIGHT
    + RISK_WEIGHT
)
assert TOTAL_WEIGHT == 100, "Confidence model weights must sum to 100"


class ConfidenceBreakdown(BaseModel):
    """A confidence score with its per-factor contributions.

    Attributes:
        trend_score: Points awarded for trend (0-25).
        structure_score: Points awarded for structure (0-20).
        liquidity_score: Points awarded for liquidity (0-20).
        momentum_score: Points awarded for momentum (0-15).
        volatility_score: Points awarded for volatility (0-10).
        risk_score: Points awarded for risk conditions (0-10).
        total: Sum of all factor scores (0-100).
        factors: The raw classification that produced each score
            (e.g. ``{"trend": "BULLISH", "structure": "CONFIRMED",
            ...}``) — for reporting (e.g. a future Telegram message)
            without recomputing anything.
    """

    trend_score: int
    structure_score: int
    liquidity_score: int
    momentum_score: int
    volatility_score: int
    risk_score: int
    total: int = Field(ge=0, le=100)
    factors: dict[str, str]

    def meets_threshold(self, threshold: int) -> bool:
        """Returns whether ``total`` meets or exceeds ``threshold``."""
        return self.total >= threshold


def classify_structure(candles: list[dict], lookback: int = 20) -> str:
    """Classifies market structure as a simple range-breakout proxy.

    See the module docstring's caveat: this is a placeholder-quality
    heuristic pending a real ``pattern_engine.py``, not chart-pattern
    or support/resistance analysis. It checks whether the latest close
    has broken decisively outside the high/low range of the preceding
    candles — a rough proxy for "structure confirms the move" that at
    least isn't circular with the trend/momentum factors (it looks at
    price position relative to recent range, not at EMAs or RSI).

    Args:
        candles: OHLC candles (dicts with ``"high"``/``"low"``/
            ``"close"`` keys), oldest to newest.
        lookback: Number of preceding candles defining the reference
            range (excludes the latest candle itself).

    Returns:
        ``"CONFIRMED"`` if the latest close is outside the preceding
        range, ``"WEAK"`` if it's within the range but near an edge
        (top/bottom quartile), ``"UNKNOWN"`` if there isn't enough
        data, otherwise ``"NONE"``.
    """
    if len(candles) < lookback + 1:
        return "UNKNOWN"

    reference = candles[-(lookback + 1) : -1]
    latest_close = candles[-1]["close"]
    range_high = max(candle["high"] for candle in reference)
    range_low = min(candle["low"] for candle in reference)
    range_size = range_high - range_low

    if range_size <= 0:
        return "UNKNOWN"

    if latest_close > range_high or latest_close < range_low:
        return "CONFIRMED"

    position = (latest_close - range_low) / range_size
    if position >= 0.75 or position <= 0.25:
        return "WEAK"

    return "NONE"


def classify_risk_conditions(spread: float | None, atr: float | None, price: float | None) -> str:
    """Classifies how favorable current conditions are for entering a trade.

    A simple, transparent proxy: spread as a fraction of ATR (tighter
    spread relative to current volatility = more favorable — a wide
    spread eats disproportionately into a low-volatility move, while
    the same absolute spread barely matters against a large one). This
    is not the risk *engine* (see ``risk.risk_controller`` for position
    sizing/trade approval) — it's a narrow input to the confidence
    score reflecting whether conditions are structurally favorable for
    entry at all.

    Args:
        spread: Current spread.
        atr: Current ATR.
        price: Current price (reserved for a future spread-as-
            percentage-of-price refinement; not currently used, since
            spread/ATR alone is the more directly relevant ratio for
            trade timing).

    Returns:
        ``"FAVORABLE"``, ``"MODERATE"``, or ``"UNFAVORABLE"``/
        ``"UNKNOWN"`` (missing data).
    """
    del price  # Reserved — see docstring.

    if spread is None or atr is None or atr <= 0:
        return "UNKNOWN"

    ratio = spread / atr
    if ratio < 0.15:
        return "FAVORABLE"
    if ratio < 0.35:
        return "MODERATE"
    return "UNFAVORABLE"


class ConfidenceModel:
    """Computes the weighted 6-factor institutional confidence score."""

    def calculate(
        self,
        trend: str,
        structure: str,
        liquidity: str,
        momentum: str,
        volatility: str,
        risk: str,
    ) -> ConfidenceBreakdown:
        """Scores each factor and combines them into a total confidence.

        Args:
            trend: ``"BULLISH"``/``"BEARISH"``/other (e.g.
                ``"SIDEWAYS"``, ``"UNKNOWN"``).
            structure: ``"CONFIRMED"``/``"WEAK"``/other — see
                :func:`classify_structure`.
            liquidity: ``"GOOD"``/``"MEDIUM"``/``"LOW"``/other — see
                ``intelligence.liquidity_engine.LiquidityEngine``.
            momentum: ``"STRONG"``/``"MODERATE"``/other — see
                ``intelligence.momentum_engine.MomentumEngine``.
            volatility: ``"HIGH"``/``"MEDIUM"``/``"LOW"``/other — see
                ``intelligence.volatility_engine.VolatilityEngine``.
            risk: ``"FAVORABLE"``/``"MODERATE"``/other — see
                :func:`classify_risk_conditions`.

        Returns:
            The full score breakdown.
        """
        trend_score = TREND_WEIGHT if trend in ("BULLISH", "BEARISH") else 0

        if structure == "CONFIRMED":
            structure_score = STRUCTURE_WEIGHT
        elif structure == "WEAK":
            structure_score = STRUCTURE_WEIGHT // 2
        else:
            structure_score = 0

        liquidity_score = {
            "GOOD": LIQUIDITY_WEIGHT,
            "MEDIUM": LIQUIDITY_WEIGHT // 2,
        }.get(liquidity, 0)

        momentum_score = {
            "STRONG": MOMENTUM_WEIGHT,
            "MODERATE": (MOMENTUM_WEIGHT * 2) // 3,
        }.get(momentum, 0)

        # MEDIUM scores highest: enough movement to be worth trading
        # without the whipsaw/slippage risk HIGH volatility implies.
        volatility_score = {
            "MEDIUM": VOLATILITY_WEIGHT,
            "HIGH": (VOLATILITY_WEIGHT * 2) // 3,
            "LOW": VOLATILITY_WEIGHT // 3,
        }.get(volatility, 0)

        risk_score = {
            "FAVORABLE": RISK_WEIGHT,
            "MODERATE": RISK_WEIGHT // 2,
        }.get(risk, 0)

        total = (
            trend_score
            + structure_score
            + liquidity_score
            + momentum_score
            + volatility_score
            + risk_score
        )

        return ConfidenceBreakdown(
            trend_score=trend_score,
            structure_score=structure_score,
            liquidity_score=liquidity_score,
            momentum_score=momentum_score,
            volatility_score=volatility_score,
            risk_score=risk_score,
            total=total,
            factors={
                "trend": trend,
                "structure": structure,
                "liquidity": liquidity,
                "momentum": momentum,
                "volatility": volatility,
                "risk": risk,
            },
        )
