"""Explicit research/execution universe, using native Weltrade terminal names."""
from __future__ import annotations

import re

from core.exceptions import MarketDataError


def is_weltrade_synthetic(symbol: str) -> bool:
    """Reject cross-broker aliases and non-synthetic instruments fail closed.

    This is a scope check, not evidence of availability. The gateway must also
    find the exact normalized name in the connected terminal catalogue.
    """
    return re.fullmatch(
        r"(?:S?FX\s+VOL\.?\s*\d+|(?:MAX\s+)?(?:PAINX|GAINX)\s+\d+|"
        r"FLIPX\s+\d+|SWITCHX\s+\d+|BREAKX\s+\d+|FIBOX)",
        symbol.strip(), re.IGNORECASE,
    ) is not None


def require_weltrade_synthetic(symbol: str) -> str:
    if not is_weltrade_synthetic(symbol):
        raise MarketDataError("Only native Weltrade synthetic indices are supported", symbol=symbol)
    return symbol.strip()
