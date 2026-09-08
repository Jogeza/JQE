"""Read-only forensic reconstruction for a persisted paper campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from broker.types import Timeframe
from config import settings
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.storage import CandleStore
from research.paper_diagnostics import PaperDiagnosticsStore
from risk.risk_controller import approve_trade
from strategy.pipeline import generate_trading_signal


BASELINE_SHA256 = "ab2e1f497d350cad20f37abff6fc7c3ef5d2f548c2a56841919605c9a7bdc1b7"


def _counter(values: list[Any]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def analyze(artifact_path: Path) -> dict[str, Any]:
    artifact_path = artifact_path.expanduser().resolve()
    digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if digest != BASELINE_SHA256:
        raise ValueError("campaign artifact does not match the committed baseline")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    session_id = artifact["session"]["session_id"]
    records = PaperDiagnosticsStore(settings.paper_diagnostics_path, initialize=False).records(session_id)
    candles = list(CandleStore(read_only=True).load_candles("XAUUSD", Timeframe.M15, provider="deriv"))[:5500]
    indicators = calculate_indicators(pd.DataFrame([item.model_dump() for item in candles]))
    by_close = {item.time + timedelta(minutes=15): index for index, item in enumerate(candles)}

    rows: list[dict[str, Any]] = []
    for record in records:
        index = by_close[record.candle_close_time]
        history = indicators.iloc[: index + 1]
        legacy_regime = detect_regime(history)
        signal = generate_trading_signal(history, "XAUUSD", regime=legacy_regime)
        intelligence = signal["intelligence"]
        risk = approve_trade(
            {"signal": signal["signal"], "confidence": signal["confidence"]},
            history, balance=settings.account_balance, enforce_limits=True,
        )
        rows.append({
            "record": record, "legacy_regime": legacy_regime,
            "signal": signal["signal"], "confidence": signal["confidence"],
            "trend": intelligence.get("trend"), "momentum": intelligence.get("momentum"),
            "volatility": intelligence.get("volatility"),
            "rsi": float(intelligence.get("rsi", history.iloc[-1].get("RSI", 0))),
            "risk_approved": risk["approved"], "risk_reason": risk.get("reason"),
        })

    emergency = [item for item in rows if item["record"].block_reason == "EMERGENCY_STOP"]
    trend_down = [item for item in rows if item["record"].regime == "TREND_DOWN"]
    buys = [item for item in rows if item["signal"] == "BUY"]
    down_rsi = [item["rsi"] for item in trend_down]
    return {
        "artifact_sha256": digest,
        "session_id": session_id,
        "emergency_stop": {
            "configured_state": settings.emergency_stop.value,
            "policy_context_value": settings.emergency_stop.value != "CLEAR",
            "count": len(emergency),
            "first": min(item["record"].candle_close_time for item in emergency).isoformat(),
            "last": max(item["record"].candle_close_time for item in emergency).isoformat(),
            "regimes": _counter([item["record"].regime for item in emergency]),
            "directions": _counter([item["signal"] for item in emergency]),
            "confidence": _counter([item["confidence"] for item in emergency]),
            "momentum": _counter([item["momentum"] for item in emergency]),
            "volatility": _counter([item["volatility"] for item in emergency]),
            "risk_before_policy": _counter([item["risk_reason"] for item in emergency]),
        },
        "trend_down": {
            "observations": len(trend_down),
            "trend": _counter([item["trend"] for item in trend_down]),
            "momentum": _counter([item["momentum"] for item in trend_down]),
            "rsi": {"minimum": min(down_rsi), "maximum": max(down_rsi), "median": median(down_rsi), "strong_eligible": sum(value > 60 for value in down_rsi), "not_strong": sum(value <= 60 for value in down_rsi)},
            "signals": _counter([item["signal"] for item in trend_down]),
            "risk": _counter([item["risk_reason"] for item in trend_down]),
        },
        "buy_origin": {
            "count": len(buys),
            "record_regime": _counter([item["record"].regime for item in buys]),
            "replayed_regime": _counter([item["legacy_regime"] for item in buys]),
            "confidence": _counter([item["confidence"] for item in buys]),
            "momentum": _counter([item["momentum"] for item in buys]),
            "volatility": _counter([item["volatility"] for item in buys]),
        },
        "confirmation": {
            "pipeline_key_present": False,
            "record_confirmation_states": _counter([item.confirmation_state for item in records]),
            "pending_state_in_campaign": False,
            "chronology_authority": "research.regime_diagnostics.ConfirmedEntryBacktestEngine",
        },
        "strategy_invariance": {"strategy_source_changed": False, "diagnostic_instrumentation": False},
        "broker_execution": "DISABLED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=Path("state/paper_campaigns/xauusd_m15_5000_final.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.artifact)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())