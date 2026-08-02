"""JQE Institutional Risk Controller.

Responsibilities:

- Protect account capital
- Filter weak signals
- Control risk exposure
- Calculate position size
- Prevent overtrading
"""

from __future__ import annotations

# ==========================
# INSTITUTIONAL PARAMETERS
# ==========================

MIN_CONFIDENCE = 75
MAX_RISK_PERCENT = 0.5
MIN_ATR = 1.0
MAX_SPREAD = 30

_DEFAULT_BALANCE = 50  # NOTE: only a fallback — see approve_trade()'s `balance` param.


# ==========================
# MAIN RISK ENGINE
# ==========================


def approve_trade(signal: dict, market_data, balance: float = _DEFAULT_BALANCE) -> dict:
    """Evaluates a signal against institutional risk rules.

    Args:
        signal: A signal dict with a ``"signal"`` key (``"BUY"``/
            ``"SELL"``) and a ``"confidence"`` key (0-100).
        market_data: OHLC+indicator data; the latest row (``.iloc[-1]``)
            must have ``"ATR"`` and (optionally) ``"spread"`` columns.
        balance: Account balance used for position sizing. Defaults to
            a placeholder value for backward compatibility with
            existing callers that don't yet pass a real balance — new
            callers should always pass the actual account balance
            (e.g. from ``BrokerGateway.get_account_info()``).

    Returns:
        A decision dict: ``{"approved": bool, "reason": str,
        "risk_percent": float, "lot_size": float}``.
    """
    decision = {"approved": False, "reason": "", "risk_percent": 0, "lot_size": 0}

    # --------------------------
    # Check signal existence
    # --------------------------
    if signal is None:
        decision["reason"] = "Missing signal"
        return decision

    direction = signal.get("signal")
    if direction not in ("BUY", "SELL"):
        decision["reason"] = "No trade signal"
        return decision

    # --------------------------
    # Confidence filter
    # --------------------------
    confidence = signal.get("confidence", 0)
    if confidence < MIN_CONFIDENCE:
        decision["reason"] = "Confidence too low"
        return decision

    # --------------------------
    # Market validation
    # --------------------------
    try:
        candle = market_data.iloc[-1]
    except (AttributeError, IndexError, TypeError):
        decision["reason"] = "Invalid market data"
        return decision

    # ATR filter
    atr = candle.get("ATR", 0)
    if atr < MIN_ATR:
        decision["reason"] = "Low volatility"
        return decision

    # Spread protection
    spread = candle.get("spread", 0)
    if spread > MAX_SPREAD:
        decision["reason"] = "Spread too high"
        return decision

    # --------------------------
    # APPROVE TRADE
    # --------------------------
    decision["approved"] = True
    decision["reason"] = "Institutional risk passed"
    decision["risk_percent"] = MAX_RISK_PERCENT
    decision["lot_size"] = calculate_position_size(
        balance=balance,
        risk_percent=MAX_RISK_PERCENT,
        stop_loss=atr,
    )

    return decision


# ==========================
# POSITION SIZE ENGINE
# ==========================


def calculate_position_size(balance: float, risk_percent: float, stop_loss: float) -> float:
    """Calculates lot size from account risk parameters.

    Args:
        balance: Account balance.
        risk_percent: Percentage of balance to risk on this trade.
        stop_loss: Stop distance (e.g. ATR) used to size the position.

    Returns:
        Lot size, floored at MT5's 0.01 minimum lot.
    """
    if stop_loss <= 0:
        return 0.01

    risk_amount = balance * risk_percent / 100
    lot = risk_amount / (stop_loss * 10)

    # MT5 minimum lot protection
    lot = max(lot, 0.01)

    return round(lot, 2)
