"""JQE's market-intelligence layer: trend, volatility, momentum,
liquidity, and regime classification, plus the weighted confidence
model that combines them.

Consolidated (Phase 3) from ``core/regime.py``, ``core/market_state.py``,
``analytics/trend_analysis.py``, ``analytics/volatility.py``,
``analytics/momentum.py``, and ``analytics/market_score.py`` — see
docs/architecture.md, "Intelligence layer", for what changed during the
move and why. ``core/regime.py`` remains as a backward-compatible
re-export (three live call sites depend on that import path); the rest
were moved without a compatibility shim (only ``core.market_scanner``
and a few tests imported them, both updated directly).
"""

from intelligence.confidence_model import ConfidenceBreakdown, ConfidenceModel
from intelligence.liquidity_engine import LiquidityEngine
from intelligence.market_regime import detect_regime
from intelligence.market_score import MarketScore
from intelligence.market_state import MarketState
from intelligence.momentum_engine import MomentumEngine
from intelligence.trend_engine import TrendEngine
from intelligence.volatility_engine import VolatilityEngine

__all__ = [
    "ConfidenceBreakdown",
    "ConfidenceModel",
    "LiquidityEngine",
    "MarketScore",
    "MarketState",
    "MomentumEngine",
    "TrendEngine",
    "VolatilityEngine",
    "detect_regime",
]
