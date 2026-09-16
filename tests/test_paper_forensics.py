"""Forensic invariants for the committed paper campaign baseline."""

from pathlib import Path

from config import EmergencyStopState, settings
from tools.paper_forensics import BASELINE_SHA256, analyze


ARTIFACT = Path("state/paper_campaigns/xauusd_m15_5000_final.json")


def test_baseline_hash_and_emergency_stop_provenance(monkeypatch) -> None:
    monkeypatch.setattr(settings, "emergency_stop", EmergencyStopState.UNKNOWN)
    report = analyze(ARTIFACT)
    assert report["artifact_sha256"] == BASELINE_SHA256
    emergency = report["emergency_stop"]
    assert emergency["configured_state"] == "UNKNOWN"
    assert emergency["policy_context_value"] is True
    assert emergency["count"] == 620
    assert emergency["risk_before_policy"] == {"Institutional risk passed": 620}


def test_trend_down_sell_gate_and_rsi_accounting() -> None:
    trend_down = analyze(ARTIFACT)["trend_down"]
    assert trend_down["observations"] == 672
    assert trend_down["trend"] == {"BEARISH": 672}
    assert trend_down["momentum"] == {"NEUTRAL": 257, "WEAK": 415}
    assert trend_down["rsi"]["strong_eligible"] == 0
    assert trend_down["signals"] == {"NO_TRADE": 672}


def test_buy_origin_and_confirmation_are_observationally_explicit() -> None:
    report = analyze(ARTIFACT)
    assert report["buy_origin"]["count"] == 1198
    assert report["buy_origin"]["record_regime"] == {"TREND_UP": 1198}
    assert report["buy_origin"]["momentum"] == {"STRONG": 1198}
    assert report["confirmation"] == {
        "pipeline_key_present": False,
        "record_confirmation_states": {"NOT_EVALUATED": 5000},
        "pending_state_in_campaign": False,
        "chronology_authority": "research.regime_diagnostics.ConfirmedEntryBacktestEngine",
    }
