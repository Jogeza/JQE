"""Paper observation diagnostics remain factual, durable, and Decimal-exact."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from api.research import get_paper_diagnostics
from config import settings
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from research.paper_diagnostics import (
    STRATEGY_ID,
    PaperDiagnosticsStore,
    PaperObservationRecord,
    PaperObservationSession,
    configuration_hash,
    summarize,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def session(**changes):
    values = dict(
        session_id="session-one", started_at=NOW, ended_at=None,
        git_commit="abc123", strategy_id=STRATEGY_ID,
        configuration_hash=configuration_hash({"symbol": "XAUUSD", "risk": "1.0"}),
        runtime_mode="paper_continuous", source_mode="SYNTHETIC_OBSERVATION",
        symbols=("XAUUSD",), timeframes=("M5",), dataset_identity="dataset-one",
    )
    values.update(changes)
    return PaperObservationSession(**values)


def record(index=1, **changes):
    values = dict(
        session_id="session-one", observed_at=NOW + timedelta(minutes=5 * index),
        symbol="XAUUSD", timeframe="M5",
        candle_close_time=NOW + timedelta(minutes=5 * index),
        source_mode="SYNTHETIC_OBSERVATION", dataset_identity="dataset-one",
        cycle_number=index,
    )
    values.update(changes)
    return PaperObservationRecord(**values)


def test_typed_observation_and_decimal_authority():
    item = record(realized_pnl=Decimal("0.100000000000000001"), realized_r=Decimal("0.1"))
    assert item.realized_pnl == Decimal("0.100000000000000001")
    with pytest.raises(ValueError, match="Decimal"):
        record(realized_pnl=0.1)


def test_no_signal_raw_signal_confirmation_and_authorization_funnel():
    items = [
        record(1, block_reason="NO_SIGNAL"),
        record(2, signal_direction="BUY", confirmation_state="FAILED", block_reason="CONFIRMATION_FAILED"),
        record(3, signal_direction="SELL", confirmation_state="CONFIRMED", execution_decision="ALLOWED", entry_event="OPENED"),
    ]
    result = summarize(items)
    assert result["observations"] == 3
    assert result["signals"] == 2 and result["confirmations"] == 1
    assert result["authorized_entries"] == 1 and result["opened_positions"] == 1
    assert result["directions"] == {"NO_SIGNAL": 1, "BUY": 1, "SELL": 1}
    assert result["block_reasons"]["CONFIRMATION_FAILED"] == 1


def test_performance_r_drawdown_profit_factor_expectancy_and_streaks():
    items = [
        record(1, signal_direction="BUY", regime="TREND_UP", exit_event="CLOSED", exit_reason="TAKE_PROFIT", realized_pnl=Decimal("2"), realized_r=Decimal("2")),
        record(2, signal_direction="BUY", regime="TREND_UP", exit_event="CLOSED", exit_reason="TAKE_PROFIT", realized_pnl=Decimal("1"), realized_r=Decimal("1")),
        record(3, signal_direction="SELL", regime="RANGE", exit_event="CLOSED", exit_reason="STOP_LOSS", realized_pnl=Decimal("-1"), realized_r=Decimal("-1")),
        record(4, signal_direction="SELL", regime="RANGE", exit_event="CLOSED", exit_reason="STOP_LOSS", realized_pnl=Decimal("-2"), realized_r=Decimal("-2")),
    ]
    result = summarize(items)
    assert result["net_pnl"] == "0" and result["profit_factor"] == "1"
    assert result["expectancy"] == "0" and result["average_r"] == "0"
    assert result["max_drawdown"] == "3"
    assert result["consecutive_wins"] == result["consecutive_losses"] == 2
    assert result["exit_distribution"]["TAKE_PROFIT"]["count"] == 2
    assert result["exit_distribution"]["STOP_LOSS"]["median_r"] == "-1.5"
    assert result["by_direction"]["BUY"]["closed_trades"] == 2
    assert result["by_regime"]["RANGE"]["net_pnl"] == "-3"


def test_stale_event_and_sample_size_guard():
    result = summarize([record(block_reason="STALE_DATA")], minimum_sample=2)
    assert result["stale_data_events"] == 1
    assert result["sample_size_insufficient"] is True


def test_storage_deduplicates_restart_and_keeps_source_modes_separate(tmp_path):
    store = PaperDiagnosticsStore(tmp_path / "diagnostics.sqlite3")
    store.start(session())
    assert store.append(record()) is True
    assert store.append(record()) is False
    restarted = PaperDiagnosticsStore(tmp_path / "diagnostics.sqlite3")
    assert len(restarted.records("session-one")) == 1
    other = session(session_id="historical", source_mode="HISTORICAL_REPLAY")
    restarted.start(other)
    restarted.append(record(session_id="historical", source_mode="HISTORICAL_REPLAY"))
    assert summarize(restarted.records())["source_modes"] == {
        "SYNTHETIC_OBSERVATION": 1, "HISTORICAL_REPLAY": 1
    }


def test_campaign_summary_reports_funnel_regime_direction_and_layer_breakdown():
    items = [
        record(1, regime="TREND_UP", signal_direction="BUY", signal_confidence=Decimal("65"), confirmation_state="CONFIRMED", execution_decision="ALLOWED", entry_event="OPENED", block_reason=None),
        record(2, regime="TREND_UP", signal_direction="BUY", signal_confidence=Decimal("75"), confirmation_state="CONFIRMED", execution_decision="ALLOWED", entry_event="OPENED", exit_event="CLOSED", exit_reason="TAKE_PROFIT", realized_pnl=Decimal("2"), realized_r=Decimal("2")),
        record(3, regime="RANGE", signal_direction="NO_SIGNAL", signal_confidence=Decimal("35"), block_reason="LOW_VOLATILITY"),
        record(4, regime="LOW_VOLATILITY", signal_direction="SELL", signal_confidence=Decimal("80"), confirmation_state="FAILED", block_reason="CONFIRMATION_FAILED"),
    ]
    result = summarize(items, minimum_sample=2)
    assert result["funnel"]["raw_signals"] == 3
    assert result["by_regime"]["TREND_UP"]["signals"] == 2
    assert result["by_direction"]["BUY"]["observations"] == 2
    assert result["confidence_distribution"]["61-80"]["count"] == 3
    assert result["rejection_layers"]["STRATEGY_FILTERS"] == 1
    assert result["rejection_layers"]["CONFIRMATION_FILTERS"] == 1
    assert result["sample_sufficiency"]["observations_sufficient"] is True
    assert result["sample_sufficiency"]["signals_sufficient"] is True


def test_get_paper_diagnostics_accepts_explicit_session_id(tmp_path, monkeypatch):
    first = PaperDiagnosticsStore(tmp_path / "diagnostics.sqlite3")
    first.start(session(session_id="session-a"))
    first.append(record(session_id="session-a"))
    second = session(session_id="session-b", started_at=NOW + timedelta(hours=1))
    first.start(second)
    first.append(record(session_id="session-b", cycle_number=2, signal_direction="SELL", confirmation_state="CONFIRMED"))
    first.finish(replace(second, ended_at=NOW + timedelta(hours=2), status="COMPLETED"))
    monkeypatch.setattr(settings, "paper_diagnostics_path", tmp_path / "diagnostics.sqlite3")
    response = get_paper_diagnostics(session_id="session-b")
    assert response["status"] == "COMPLETED"
    assert response["metrics"]["signals"] == 1
    assert response["session"]["session_id"] == "session-b"


def test_incompatible_session_context_cannot_be_merged(tmp_path):
    store = PaperDiagnosticsStore(tmp_path / "diagnostics.sqlite3")
    store.start(session())
    with pytest.raises(ValueError, match="incompatible"):
        store.start(session(configuration_hash="different"))


def test_api_diagnostics_is_read_only(tmp_path, monkeypatch):
    path = tmp_path / "diagnostics.sqlite3"
    store = PaperDiagnosticsStore(path)
    store.start(session())
    store.append(record())
    store.finish(replace(session(), ended_at=NOW + timedelta(hours=1), status="COMPLETED"))
    monkeypatch.setattr(settings, "paper_diagnostics_path", path)
    response = get_paper_diagnostics()
    assert response["metrics"]["observations"] == 1
    assert len(store.records()) == 1


@pytest.mark.asyncio
async def test_private_and_public_summary_payloads_are_sanitized():
    class Gateway:
        send = AsyncMock()

    gateway = Gateway()
    events = JQENotificationEvents(NotificationService(gateway))
    facts = {"Observations": "96", "Trades": "3", "Account": "private", "Internal Path": "hidden"}
    await events.paper_summary(facts=facts, public=False)
    await events.paper_summary(facts=facts, public=True)
    private, public = [call.args[0] for call in gateway.send.await_args_list]
    assert private.facts["Audience"] == "PRIVATE_OPERATIONAL" and private.facts["Account"] == "private"
    assert public.facts["Audience"] == "PUBLIC_SANITIZED"
    assert "Account" not in public.facts and "Internal Path" not in public.facts
