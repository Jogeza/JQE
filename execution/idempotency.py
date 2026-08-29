"""Stable identity for one canonical execution intent."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


def build_execution_idempotency_key(
    *,
    symbol: str,
    side: str,
    volume: float,
    entry: float,
    stop_loss: float,
    take_profit: float,
    signal_time: Any,
) -> str:
    """Return a deterministic key for the exact signal and planned order."""
    if isinstance(signal_time, datetime):
        timestamp = signal_time.isoformat()
    else:
        isoformat = getattr(signal_time, "isoformat", None)
        timestamp = isoformat() if callable(isoformat) else str(signal_time)
    payload = {
        "entry": format(float(entry), ".17g"),
        "side": side.strip().upper(),
        "signal_time": timestamp,
        "stop_loss": format(float(stop_loss), ".17g"),
        "symbol": symbol.strip().upper(),
        "take_profit": format(float(take_profit), ".17g"),
        "volume": format(float(volume), ".17g"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"jqe-sim-{digest}"
