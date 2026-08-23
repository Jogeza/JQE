"""JQE Institutional Risk Controller.

Maintains backward-compatible functional API while delegating to the unified
RiskEngine and PositionSizing architectures.
"""

from __future__ import annotations

from typing import Any

from risk.position_sizing import calculate_position_size as _calc_pos_size
from risk.risk_engine import (
    MAX_RISK_PERCENT,
    MAX_SPREAD,
    MIN_ATR,
    MIN_CONFIDENCE,
    RiskEngine,
)

_DEFAULT_BALANCE = 50.0

_default_engine = RiskEngine()


def approve_trade(
    signal: dict[str, Any] | None,
    market_data: Any,
    balance: float = _DEFAULT_BALANCE,
) -> dict[str, Any]:
    """Evaluates a signal against institutional risk rules.

    Delegates to :class:`~risk.risk_engine.RiskEngine`.

    Args:
        signal: A signal dict with a ``"signal"`` key (``"BUY"``/``"SELL"``)
            and a ``"confidence"`` key (0-100).
        market_data: OHLC+indicator data; the latest row (``.iloc[-1]``)
            must have ``"ATR"`` and (optionally) ``"spread"`` columns.
        balance: Account balance used for position sizing.

    Returns:
        A decision dict: ``{"approved": bool, "reason": str, "risk_percent": float, "lot_size": float}``.
    """
    return _default_engine.approve_trade(signal=signal, market_data=market_data, balance=balance)


def calculate_position_size(balance: float, risk_percent: float, stop_loss: float) -> float:
    """Calculates lot size from account risk parameters.

    Delegates to :func:`~risk.position_sizing.calculate_position_size`.
    """
    return _calc_pos_size(balance=balance, risk_percent=risk_percent, stop_loss=stop_loss)
