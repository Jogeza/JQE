"""JQE Market Score Engine.

Calculates a legacy institutional market confidence score (0-100).

.. note::
    This is the original 4-factor scorer (trend/volatility/liquidity/
    momentum). :class:`intelligence.confidence_model.ConfidenceModel`
    (Phase 3) supersedes it with the full 6-factor design (adding
    structure and risk) — kept here only because
    :class:`intelligence.market_state.MarketState` still depends on
    it. Wiring ``MarketState``/``MarketScanner`` onto
    ``ConfidenceModel`` instead is deferred to Phase 5 (Strategy
    Engine), alongside the rest of that pathway's rebuild — see
    docs/architecture.md.

Weights:

    Trend       40%
    Volatility  25%
    Liquidity   20%
    Momentum    15%
"""

from __future__ import annotations


class MarketScore:
    """Legacy 4-factor weighted market confidence scorer."""

    def calculate(
        self,
        trend: str,
        volatility: str,
        liquidity: str,
        momentum: str = "NEUTRAL",
    ) -> int:
        """Calculates a 0-100 confidence score.

        Args:
            trend: ``"BULLISH"``, ``"BEARISH"``, or anything else
                (treated as no trend).
            volatility: ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``, or anything
                else (treated as unknown).
            liquidity: ``"GOOD"``, ``"MEDIUM"``, ``"LOW"``, or anything
                else (treated as unknown).
            momentum: ``"STRONG"``, ``"MODERATE"``, or anything else
                (treated as unknown).

        Returns:
            A score from 0 to 100.
        """
        score = 0

        # Trend Score (40)
        if trend in ("BULLISH", "BEARISH"):
            score += 40

        # Volatility Score (25)
        if volatility == "HIGH":
            score += 25
        elif volatility == "MEDIUM":
            score += 15
        elif volatility == "LOW":
            score += 10

        # Liquidity Score (20)
        if liquidity == "GOOD":
            score += 20
        elif liquidity == "MEDIUM":
            score += 10

        # Momentum Score (15)
        if momentum == "STRONG":
            score += 15
        elif momentum == "MODERATE":
            score += 10

        return score
