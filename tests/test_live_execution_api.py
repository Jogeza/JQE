from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import api.service as service_module
import main
from api.service import ApplicationService
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from data.watchlist import WatchlistStore


@pytest.mark.asyncio
async def test_api_live_cycle_is_read_only_even_when_confirmed() -> None:
    service = object.__new__(ApplicationService)

    with pytest.raises(ValueError, match="API is read-only"):
        await service.execute_live_cycle(confirmed=True)


@pytest.mark.asyncio
async def test_live_cycle_never_delegates_to_canonical_main_run(monkeypatch: pytest.MonkeyPatch) -> None:
    service = object.__new__(ApplicationService)
    monkeypatch.setattr(
        service_module,
        "settings",
        SimpleNamespace(effective_broker="mt5", broker_execution_enabled=True),
    )
    run = AsyncMock(
        return_value=main.CycleExecutionResult(
            status="ORDER_ACCEPTED",
            broker="mt5",
            symbol="EURUSD",
            side="BUY",
            order_id="demo-order-1",
            decision_code="ALLOWED",
            reason="Order accepted",
        )
    )
    monkeypatch.setattr(main, "run", run)

    with pytest.raises(ValueError, match="API is read-only"):
        await service.execute_live_cycle(confirmed=True)
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_watchlist_api_cannot_delegate_to_canonical_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(ApplicationService)
    monkeypatch.setattr(
        service_module, "settings",
        SimpleNamespace(effective_broker="weltrade", broker_execution_enabled=True),
    )
    runner = AsyncMock(return_value=(main.CycleExecutionResult(
        status="NO_TRADE", broker="weltrade", symbol="FX VOL 20",
        decision_code="NO_TRADE_SIGNAL",
    ),))
    monkeypatch.setattr(main, "run_watchlist", runner)

    with pytest.raises(ValueError, match="API is read-only"):
        await service.execute_watchlist_cycles(confirmed=False)
    runner.assert_not_awaited()

    with pytest.raises(ValueError, match="API is read-only"):
        await service.execute_watchlist_cycles(confirmed=True)
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_strategy_signal_is_labelled_before_risk_and_broker_checks() -> None:
    sink = SimpleNamespace(send=AsyncMock())
    events = JQENotificationEvents(NotificationService(sink))
    assert await events.strategy_signal(
        symbol="FX Vol 20", timeframe="M5", side="BUY",
        confidence=76, bar_time="2026-09-28T03:30:00+00:00",
    )
    notification = sink.send.await_args.args[0]
    assert notification.facts["Execution"] == "PENDING RISK AND BROKER CHECKS"
    assert notification.facts["Symbol"] == "FX Vol 20"


@pytest.mark.asyncio
async def test_watchlist_runner_uses_each_persisted_pair_without_changing_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    path = tmp_path / "watchlist.sqlite3"
    store = WatchlistStore(path, default_seeds=[])
    store.add_item("FX Vol 20", "M1")
    store.add_item("PainX 400", "M5")
    monkeypatch.setattr(main, "settings", SimpleNamespace(
        broker_execution_enabled=True, effective_broker="weltrade",
        market_data_source="broker", watchlist_store_path=path,
        decision_journal_path=tmp_path / "decisions.sqlite3",
    ))
    runner = AsyncMock(side_effect=lambda *, symbol, timeframe_name: main.CycleExecutionResult(
        status="NO_TRADE", broker="weltrade", symbol=symbol,
    ))
    monkeypatch.setattr(main, "run", runner)

    with main._armed_by_supervisor():
        results = await main.run_watchlist()
    assert len(results) == 2
    from monitoring.decision_journal import read_journal
    journal = read_journal(tmp_path / "decisions.sqlite3")
    assert len(journal['items']) == 2
    assert all(item['facts']['status'] == 'NO_TRADE' for item in journal['items'])
    assert [call.kwargs for call in runner.await_args_list] == [
        {"symbol": "FX VOL 20", "timeframe_name": "M1"},
        {"symbol": "PAINX 400", "timeframe_name": "M5"},
    ]
