"""Focused tests for the bounded local paper campaign runner."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest

from broker.types import ClosedMarketObservation, Timeframe
from tools import paper_campaign
from research.paper_diagnostics import PaperDiagnosticsStore
from research.historical_safety import ExecutionContextKind, HistoricalResearchSafetyContext


def _safety():
    return HistoricalResearchSafetyContext(
        kind=ExecutionContextKind.HISTORICAL_RESEARCH, symbol="XAUUSD",
        max_daily_loss_percent=5.0, max_daily_trades=20,
    )


def _observations(count: int) -> list[ClosedMarketObservation]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [ClosedMarketObservation(
        canonical_symbol="XAUUSD", source="test", provider_symbol="XAUUSD",
        timeframe=Timeframe.M15, candle_opened_at=start + timedelta(minutes=15 * index),
        closed_at=start + timedelta(minutes=15 * (index + 1)), open=100.0,
        high=101.0, low=99.0, close=100.0, volume=1.0,
    ) for index in range(count)]


def test_campaign_is_local_only_and_writes_atomic_summary(monkeypatch, tmp_path, capsys):
    observations = _observations(503)
    monkeypatch.setattr(paper_campaign, "_campaign_observations", lambda symbol, timeframe, count: (observations, "sha256:test", []))
    async def decide(_window, **_kwargs):
        return None, {"signal_direction": "NO_TRADE", "regime": "TEST"}
    monkeypatch.setattr(paper_campaign, "evaluate_production_decision", decide)

    output = tmp_path / "campaign.json"
    summary = asyncio.run(paper_campaign.run_campaign(
        symbol="XAUUSD", timeframe=Timeframe.M15, max_observations=3,
        output=output, safety_context=_safety(), diagnostics_path=tmp_path / "diagnostics.sqlite3", quiet=True,
    ))

    assert summary["session"]["status"] == "COMPLETED"
    assert summary["session"]["processed_observations"] == 3
    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["metrics"]["observations"] == 3
    assert capsys.readouterr().out == ""


def test_campaign_resume_does_not_duplicate_records(monkeypatch, tmp_path):
    observations = _observations(503)
    monkeypatch.setattr(paper_campaign, "_campaign_observations", lambda symbol, timeframe, count: (observations, "sha256:test", []))
    async def decide(_window, **_kwargs):
        return None, {"signal_direction": "NO_TRADE", "regime": "TEST"}
    monkeypatch.setattr(paper_campaign, "evaluate_production_decision", decide)

    output = tmp_path / "campaign.json"
    first = asyncio.run(paper_campaign.run_campaign(
        symbol="XAUUSD", timeframe=Timeframe.M15, max_observations=3,
        output=output, safety_context=_safety(), diagnostics_path=tmp_path / "diagnostics.sqlite3", quiet=True,
    ))
    store = PaperDiagnosticsStore(tmp_path / "diagnostics.sqlite3")
    session = store.session(first["session"]["session_id"])
    assert session is not None
    store.finish(replace(session, ended_at=None, status="RUNNING", termination_reason=None))
    with pytest.raises(ValueError, match="immutable"):
        asyncio.run(paper_campaign.run_campaign(
            symbol="XAUUSD", timeframe=Timeframe.M15, max_observations=3,
            output=output, safety_context=_safety(), diagnostics_path=tmp_path / "diagnostics.sqlite3", session_id=first["session"]["session_id"], resume=True, quiet=True,
        ))


def test_new_campaign_session_does_not_reuse_prior_runtime_state(monkeypatch, tmp_path):
    observations = _observations(503)
    monkeypatch.setattr(paper_campaign, "_campaign_observations", lambda symbol, timeframe, count: (observations, "sha256:test", []))
    async def decide(_window, **_kwargs):
        return None, {"signal_direction": "NO_TRADE", "regime": "TEST"}
    monkeypatch.setattr(paper_campaign, "evaluate_production_decision", decide)

    output = tmp_path / "campaign.json"
    first = asyncio.run(paper_campaign.run_campaign(
        symbol="XAUUSD", timeframe=Timeframe.M15, max_observations=3,
        output=output, safety_context=_safety(), diagnostics_path=tmp_path / "diagnostics.sqlite3", quiet=True,
    ))
    second = asyncio.run(paper_campaign.run_campaign(
        symbol="XAUUSD", timeframe=Timeframe.M15, max_observations=3,
        output=tmp_path / "second.json", safety_context=_safety(), diagnostics_path=tmp_path / "diagnostics.sqlite3", quiet=True,
    ))

    assert first["session"]["session_id"] != second["session"]["session_id"]
    assert second["metrics"]["observations"] == 3


def test_campaign_failure_marks_session_failed(monkeypatch, tmp_path):
    observations = _observations(501)
    monkeypatch.setattr(paper_campaign, "_campaign_observations", lambda symbol, timeframe, count: (observations, "sha256:test", []))
    async def decide(_window, **_kwargs):
        return None, {"signal_direction": "NO_TRADE", "regime": "TEST"}
    monkeypatch.setattr(paper_campaign, "evaluate_production_decision", decide)
    def fail_append(_store, _record):
        raise RuntimeError("fixture persistence failure")
    monkeypatch.setattr(PaperDiagnosticsStore, "append", fail_append)

    output = tmp_path / "campaign.json"
    try:
        asyncio.run(paper_campaign.run_campaign(
            symbol="XAUUSD", timeframe=Timeframe.M15, max_observations=1,
            output=output, safety_context=_safety(), diagnostics_path=tmp_path / "diagnostics.sqlite3", quiet=True,
        ))
    except RuntimeError:
        pass
    else:
        raise AssertionError("campaign should fail")

    session = PaperDiagnosticsStore(tmp_path / "diagnostics.sqlite3").latest_session()
    assert session is not None
    assert session.status == "FAILED"
    assert not output.exists()
