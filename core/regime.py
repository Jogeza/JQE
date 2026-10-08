"""Backward-compatible re-export of the market regime detector.

The real implementation moved to :mod:`intelligence.market_regime` as
part of consolidating JQE's market-intelligence modules into the
``intelligence`` package. Kept here because ``main.py``,
``backtesting/backtest.py``, and ``strategy/pipeline.py`` already
import ``from core.regime import detect_regime`` — same
backward-compatibility approach as ``core/logger.py`` (Milestone 1):
one implementation, re-exported at the old path so existing call sites
don't need to change.

Re-exports the canonical detector (emits ``HIGH_VOLATILITY``,
``TRENDING``, ``RANGING``, ``UNKNOWN``) rather than the legacy
vocabulary so the canonical strategy path sees the high-volatility
protection branch.
"""

from intelligence.market_regime import detect_regime

__all__ = ["detect_regime"]
