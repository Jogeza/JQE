"""JQE Institutional Execution Simulator.

Forward-only trade simulation. No look-ahead bias: simulate_trade()
only ever looks at candles *after* the entry index when deciding the
outcome.

This module is backtest-only — simulate_trade() requires the future
price path to already be known, which is unavailable for live trading.
Live orders go through broker.BrokerGateway.submit_order() instead
(see strategy/pipeline.py and main.py).
"""

from __future__ import annotations

# Candles searched forward for a stop/target hit before giving up and
# recording a TIMEOUT. Matches the original implementation's window
# exactly: dataframe.iloc[current_index + 1 : current_index + 20] is
# 19 candles, not 20 — kept as-is rather than "rounded" to avoid
# silently changing simulation behavior.
_LOOKAHEAD_CANDLES = 19

_STOP_ATR_MULTIPLE = 1.5
_TARGET_ATR_MULTIPLE = 3.0


def calculate_stop_target(entry: float, atr: float, direction: str) -> tuple[float, float]:
    """Computes stop-loss/take-profit price levels from entry price and ATR.

    Extracted from simulate_trade()'s body so the same formula can also
    construct a live order's stop_loss/take_profit *before* simulating
    forward — simulate_trade() itself remains backtest-only, since
    determining whether the stop or target was hit first requires
    future candles.

    Args:
        entry: Entry price.
        atr: Average True Range at the entry candle.
        direction: ``"BUY"`` or ``"SELL"``.

    Returns:
        A ``(stop, target)`` tuple of absolute price levels.
    """
    stop_distance = atr * _STOP_ATR_MULTIPLE
    target_distance = atr * _TARGET_ATR_MULTIPLE

    if direction == "BUY":
        return entry - stop_distance, entry + target_distance
    return entry + stop_distance, entry - target_distance


def simulate_trade(signal: dict, current_index: int, dataframe) -> dict | None:
    """Simulates one trade forward from ``current_index``, no look-ahead bias.

    Args:
        signal: A signal dict with a ``"signal"`` key of ``"BUY"``,
            ``"SELL"``, or anything else (treated as no trade).
        current_index: Row index of the entry candle in ``dataframe``.
        dataframe: OHLC data with an ``"ATR"`` column, indexed
            positionally (``.iloc``) — candles after ``current_index``
            are used to determine the outcome.

    Returns:
        ``None`` if no trade was taken (non-BUY/SELL signal, or
        non-positive ATR). Otherwise a dict with ``"profit"`` (in
        R-multiples: -1 for a stop loss, +3 for a target hit, 0 for a
        timeout) and ``"result"`` (``"WIN"``, ``"LOSS"``, or
        ``"TIMEOUT"``).
    """
    direction = signal.get("signal")
    if direction not in ("BUY", "SELL"):
        return None

    entry = dataframe.iloc[current_index]["close"]
    atr = dataframe.iloc[current_index]["ATR"]
    if atr <= 0:
        return None

    stop, target = calculate_stop_target(entry, atr, direction)

    # ONLY future candles — no look-ahead bias.
    future = dataframe.iloc[current_index + 1 : current_index + 1 + _LOOKAHEAD_CANDLES]

    for _, candle in future.iterrows():
        if direction == "BUY":
            if candle["low"] <= stop:
                return {"profit": -1, "result": "LOSS"}
            if candle["high"] >= target:
                return {"profit": 3, "result": "WIN"}
        else:
            if candle["high"] >= stop:
                return {"profit": -1, "result": "LOSS"}
            if candle["low"] <= target:
                return {"profit": 3, "result": "WIN"}

    return {"profit": 0, "result": "TIMEOUT"}
