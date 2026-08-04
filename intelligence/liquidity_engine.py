"""JQE Liquidity Engine.

Classifies market liquidity from spread — a simple, transparent proxy
in the absence of order-book depth data (JQE trades CFDs/synthetic
indices via MT5/Deriv, neither of which exposes order-book depth
through the APIs this platform integrates with).
"""

from __future__ import annotations

#: Spread thresholds (in price/pip units, consistent with how the rest
#: of the codebase already treats spread — see risk.risk_controller's
#: MAX_SPREAD). Tunable; not derived from any statistical study.
_GOOD_SPREAD_THRESHOLD = 3.0
_MEDIUM_SPREAD_THRESHOLD = 8.0


class LiquidityEngine:
    """Classifies liquidity from spread.

    Promoted out of ``core.market_state.MarketState`` (Milestone:
    Phase 3), which previously only distinguished ``"GOOD"``/``"LOW"``
    from a single threshold — a binary split that left
    ``analytics.market_score.MarketScore``'s ``"MEDIUM"`` liquidity
    scoring branch permanently unreachable. This engine's three tiers
    make that branch reachable/correct without changing
    ``MarketScore``'s own scoring logic.
    """

    def analyze(self, spread: float | None) -> dict:
        """Classifies liquidity from spread.

        Args:
            spread: Current spread, in the same units used elsewhere
                in this codebase (e.g. ``risk.risk_controller``'s
                ``MAX_SPREAD``). ``None`` or missing data is treated
                as unknown/worst-case, not assumed favorable.

        Returns:
            A dict with ``"liquidity"`` (``"GOOD"``/``"MEDIUM"``/
            ``"LOW"``/``"UNKNOWN"``) and ``"spread"``.
        """
        if spread is None:
            return {"liquidity": "UNKNOWN", "spread": None}

        if spread < _GOOD_SPREAD_THRESHOLD:
            liquidity = "GOOD"
        elif spread < _MEDIUM_SPREAD_THRESHOLD:
            liquidity = "MEDIUM"
        else:
            liquidity = "LOW"

        return {"liquidity": liquidity, "spread": spread}
