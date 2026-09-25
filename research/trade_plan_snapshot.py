"""Serializable trade-plan facts attached to every future SIGNAL event."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


TRADE_PLAN_SNAPSHOT_VERSION = "trade-plan-snapshot-v1"
ENTRY_BASIS = "NEXT_CANDLE_OPEN"
SPREAD_SOURCE = "MT5_RATES_PER_BAR_AT_RESOLUTION"
DEFAULT_HORIZON_BARS = 20


def _iso(value: datetime | str | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _dump_plan(plan: Any) -> dict[str, Any] | None:
    if plan is None:
        return None
    if hasattr(plan, "model_dump"):
        value = plan.model_dump(mode="json")
    elif isinstance(plan, Mapping):
        value = dict(plan)
    else:
        return None
    return value


def build_trade_plan_snapshot(
    *,
    signal: Mapping[str, Any],
    symbol: str,
    timeframe: str,
    signal_candle_open: datetime | str,
    signal_candle_close: datetime | str,
) -> dict[str, Any]:
    """Return JSON-safe plan facts without changing signal or risk decisions.

    The persisted ``entry_price`` is the planner's reference price at the
    signal candle close.  It is not presented as a fill: the authoritative
    shadow resolver uses the next candle open and obtains the per-bar spread
    from MT5 rates.
    """
    plan = _dump_plan(signal.get("trade_plan"))
    valid = bool(plan and plan.get("signal") in {"BUY", "SELL"} and plan.get("entry") is not None)
    return {
        "schema_version": TRADE_PLAN_SNAPSHOT_VERSION,
        "status": "ACTIONABLE" if valid else "NON_ACTIONABLE",
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": str(signal.get("signal", "NO_TRADE")),
        "entry_basis": {
            "kind": ENTRY_BASIS,
            "reference_price": plan.get("entry") if plan else None,
            "signal_candle_open": _iso(signal_candle_open),
            "signal_candle_close": _iso(signal_candle_close),
            "fill_price": None,
        },
        "entry_price": plan.get("entry") if plan else None,
        "stop_loss": plan.get("stop_loss") if plan else None,
        "take_profit": plan.get("take_profit") if plan else None,
        "risk_reward": plan.get("risk_reward") if plan else None,
        "atr": plan.get("atr") if plan else None,
        "spread": {
            "value": None,
            "unit": "price",
            "source": SPREAD_SOURCE,
        },
        "horizon_bars": DEFAULT_HORIZON_BARS,
        "planner": "strategy.pipeline.generate_trading_signal.trade_plan",
        "plan": plan,
        "reason": None if plan is not None else "SIGNAL_PAYLOAD_DID_NOT_INCLUDE_TRADE_PLAN",
    }
