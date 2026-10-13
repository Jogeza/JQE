from copy import deepcopy
from datetime import datetime, timezone

import pytest

from backtesting.opportunity_inventory import digest, extract


def evidence():
    decision = {"timestamp": "2026-09-08T00:00:00+00:00", "signal": "SELL", "confidence": 75,
                "state": "REJECTED_CANDIDATE", "reasons": ["Position already open"]}
    return {"provider": "weltrade", "symbol": "SFX Vol 99", "timeframe": "M5", "trades": [],
            "decisions": [decision, {**decision, "state": "EXECUTION_REJECTED"}]}


def seal(result):
    result = deepcopy(result)
    payload = {k: v for k, v in result.items() if k != "provider"}
    result["result_hash"] = digest(payload)
    return result


def run(result):
    return extract(result, datetime(2026, 9, 8, tzinfo=timezone.utc), datetime(2026, 10, 8, tzinfo=timezone.utc))


def test_blocked_signal_preserved_and_execution_event_not_double_counted():
    rows, observations = run(seal(evidence()))
    assert observations == len(rows) == 1
    assert rows[0]["label"] is None
    assert rows[0]["label_status"] == "UNLABELLED_COUNTERFACTUAL"
    assert rows[0]["decision_available_at"] == "2026-09-08T00:05:00+00:00"


def test_corruption_rejected():
    result = seal(evidence())
    result["decisions"][0]["confidence"] = 100
    with pytest.raises(ValueError, match="hash mismatch"):
        run(result)


def test_duplicate_canonical_observation_rejected():
    result = evidence()
    result["decisions"].append(result["decisions"][0])
    with pytest.raises(ValueError, match="Duplicate canonical"):
        run(seal(result))


def test_executed_label_available_only_after_exit_bar_close():
    result = evidence()
    result["trades"] = [{"signal_timestamp": result["decisions"][0]["timestamp"], "direction": "SELL",
                         "exit_timestamp": "2026-09-08T00:10:00+00:00", "initial_risk_account_currency": .5,
                         "net_pnl": -.25, "trade_id": 1}]
    label = run(seal(result))[0][0]["label"]
    assert label["available_at"] == "2026-09-08T00:15:00+00:00"
    assert label["net_r"] == -.5


def test_sealed_holdout_decisions_rejected():
    result = evidence()
    result["decisions"][0]["timestamp"] = "2026-10-16T00:00:00+00:00"
    with pytest.raises(ValueError, match="outside registered training"):
        run(seal(result))


def test_missing_signal_close_observation_rejected():
    result = evidence()
    result["indicators"] = [{"timestamp": "2026-09-08T00:00:00+00:00"},
                            {"timestamp": "2026-09-08T00:05:00+00:00"}]
    with pytest.raises(ValueError, match="Incomplete canonical"):
        run(seal(result))
