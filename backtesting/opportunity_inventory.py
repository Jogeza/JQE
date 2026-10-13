"""Read-only inventory of saved canonical training decisions; never simulates trades."""
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path


def digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def aware(value):
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("Aware evidence timestamps required")
    return result


def extract(result, start, end):
    """Separate signal-close decisions from next-bar execution rejection events."""
    payload = dict(result)
    expected = payload.pop("result_hash")
    payload.pop("provider", None)  # BacktestResult's documented result-hash scope.
    if digest(payload) != expected:
        raise ValueError("Saved canonical result hash mismatch")
    if result["provider"] != "weltrade" or result["timeframe"] != "M5":
        raise ValueError("This inventory is exact-provider M5 only")
    trades = {}
    for trade in result["trades"]:
        key = (trade["signal_timestamp"], trade["direction"])
        if key in trades:
            raise ValueError("Duplicate executed signal")
        trades[key] = trade
    rows, seen = [], set()
    observations = 0
    for decision in result["decisions"]:
        # EXECUTION_REJECTED is recorded at the subsequent entry bar, not the
        # signal bar. Counting it again would invent duplicate opportunities.
        if decision["state"] == "EXECUTION_REJECTED":
            continue
        timestamp = aware(decision["timestamp"])
        if not start <= timestamp < end:
            raise ValueError("Decision outside registered training window")
        if timestamp in seen:
            raise ValueError("Duplicate canonical signal-close observation")
        seen.add(timestamp)
        observations += 1
        if decision["signal"] not in {"BUY", "SELL"}:
            continue
        trade = trades.pop((decision["timestamp"], decision["signal"]), None)
        label = None
        if trade is not None:
            available = aware(trade["exit_timestamp"]) + timedelta(minutes=5)
            risk = trade["initial_risk_account_currency"]
            if not risk or risk <= 0 or not timestamp + timedelta(minutes=5) < available <= end:
                raise ValueError("Invalid executed label chronology/risk")
            label = {"available_at": available.isoformat(), "net_modelled_usd": trade["net_pnl"],
                     "net_r": trade["net_pnl"] / risk, "trade_id": trade["trade_id"]}
        identity = {"provider": result["provider"], "symbol": result["symbol"], "timeframe": "M5",
                    "signal_bar_open": decision["timestamp"], "direction": decision["signal"]}
        rows.append({**identity, "event_id": digest(identity),
                     "decision_available_at": (timestamp + timedelta(minutes=5)).isoformat(),
                     "confidence": decision["confidence"], "state": decision["state"],
                     "reasons": decision["reasons"], "label": label,
                     "label_status": "EXECUTED_BASELINE_ONLY" if label else "UNLABELLED_COUNTERFACTUAL",
                     "source_result_hash": expected})
    if trades:
        raise ValueError("Executed trade lacks canonical signal observation")
    if "indicators" in result:
        expected_times = {aware(row["timestamp"]) for row in result["indicators"]
                          if start <= aware(row["timestamp"]) < end}
        if seen != expected_times:
            raise ValueError("Incomplete canonical decision coverage")
    return rows, observations


def inventory(training: Path, campaign: Path, output: Path):
    protocol = json.loads((training / "training-replay-protocol.json").read_text())
    if protocol["partition"] != "TRAIN_DIAGNOSTIC_ONLY":
        raise ValueError("Training-only artifacts required")
    start, end = (aware(protocol["windows"]["train"][key]) for key in ("start_inclusive", "end_exclusive"))
    output.mkdir(parents=True, exist_ok=False)
    summary = {"scope": "SAVED_CANONICAL_TRAINING_ARTIFACT_EXTRACTION_NOT_NEW_BACKTEST", "symbols": [],
               "models_fitted": 0, "candidate_configurations": 0, "holdouts_read": False}
    with (output / "opportunities.jsonl").open("x", encoding="utf-8") as stream:
        for path in sorted(training.glob("*--optimistic_zero_commission--result.json")):
            result = json.loads(path.read_text())
            rows, observations = extract(result, start, end)
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            directory = campaign / "bundles" / (result["symbol"].replace(" ", "_") + "_M5")
            manifest = json.loads((directory / "manifest.json").read_text())
            if manifest["provider"] != "weltrade" or manifest["provider_symbol"] != result["symbol"]:
                raise ValueError("History manifest identity mismatch")
            summary["symbols"].append({"symbol": result["symbol"], "observations": observations,
                "opportunities": len(rows), "executed_labels": sum(r["label"] is not None for r in rows),
                "states": dict(Counter(r["state"] for r in rows)),
                "history_first_bar": manifest["first_candle"], "history_last_bar": manifest["last_candle"],
                "history_bars": manifest["candle_count"], "history_manifest_sha256": digest(manifest),
                "source_file_sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()})
    if len(summary["symbols"]) != 10:
        raise ValueError("Expected all ten campaign symbols; incomplete inventory retained")
    summary["opportunity_file_sha256"] = "sha256:" + hashlib.sha256((output / "opportunities.jsonl").read_bytes()).hexdigest()
    summary["ml_fit_status"] = "BLOCKED: counterfactual labels, additional history, costs and fresh registration required"
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
