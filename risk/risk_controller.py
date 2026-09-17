"""JQE Institutional Risk Controller.

Execution authorization delegates to ``RiskEngine``. The raw-float position
helper remains solely for backtesting compatibility.
"""

from __future__ import annotations

from typing import Any

from risk.position_sizing import calculate_position_size as _calc_pos_size
from risk.position_sizing import (
    ExecutionSizingDecision,
    authorize_execution_quantity as _authorize_execution_quantity,
)
from risk.risk_engine import (
    MAX_RISK_PERCENT,
    MAX_SPREAD,
    MIN_ATR,
    MIN_CONFIDENCE,
    RiskDecisionCode,
    RiskEngine,
)

_DEFAULT_BALANCE = 50.0

_default_engine = RiskEngine()


def approve_trade(
    signal: dict[str, Any] | None,
    market_data: Any,
    balance: float = _DEFAULT_BALANCE,
    enforce_limits: bool = False,
) -> dict[str, Any]:
    """Evaluates a signal against institutional risk rules.

    Delegates to :class:`~risk.risk_engine.RiskEngine`.

    Args:
        signal: A signal dict with a ``"signal"`` key (``"BUY"``/``"SELL"``)
            and a ``"confidence"`` key (0-100).
        market_data: OHLC+indicator data; the latest row (``.iloc[-1]``)
            must have ``"ATR"`` and (optionally) ``"spread"`` columns.
        balance: Account balance used to authorize account-currency risk.

    Returns:
        A decision containing approval, reason, risk percentage, and
        authorized account-currency risk amount. It does not authorize lots.
    """
    return _default_engine.approve_trade(
        signal=signal, market_data=market_data, balance=balance, enforce_limits=enforce_limits
    )


def calculate_position_size(balance: float, risk_percent: float, stop_loss: float) -> float:
    """Deprecated noncanonical raw lot helper for backtesting only.

    Never use its float result to construct a broker order. Broker-bound code
    must use :func:`authorize_execution_quantity`.
    """
    return _calc_pos_size(balance=balance, risk_percent=risk_percent, stop_loss=stop_loss)


def authorize_execution_quantity(
    *, broker: str, balance: float, risk_percent: float, entry: float, stop_loss: float
) -> ExecutionSizingDecision:
    return _authorize_execution_quantity(
        broker=broker,
        balance=balance,
        risk_percent=risk_percent,
        entry=entry,
        stop_loss=stop_loss,
    )

def reconcile_daily_history(trades: list[Any], balance: float) -> None:
    """Rebuilds daily state statelessly from the broker's closed-trade history.

    Delegates to :class:`~risk.risk_engine.RiskEngine`.
    """
    _default_engine.reconcile_daily_history(trades=trades, balance=balance)


def get_reconciled_daily_state() -> tuple[float, int, float, int]:
    """Return the authoritative counters populated by reconciliation."""
    state = _default_engine.get_daily_state()
    return (
        state.daily_realized_loss_percent,
        state.daily_trades_count,
        state.max_daily_loss,
        state.max_trades_daily,
    )
