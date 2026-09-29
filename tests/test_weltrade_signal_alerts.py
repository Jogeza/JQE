"""Offline quote and plan facts in Weltrade signal alerts."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import main
from broker.types import Tick
from broker.weltrade_gateway import WeltradeGateway
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from notifications.telegram import render_telegram


def _sink():
    transport = SimpleNamespace(send=AsyncMock())
    return JQENotificationEvents(NotificationService(transport)), transport


@pytest.mark.asyncio
async def test_live_quote_and_plan_render_without_fixture_prices():
    events, transport = _sink()
    tick = Tick(time=datetime.now(timezone.utc) - timedelta(seconds=2),
                symbol="FX Vol 20", bid=237.125, ask=237.375)
    gateway = SimpleNamespace(get_latest_tick=AsyncMock(return_value=tick))
    await main._emit_weltrade_signal_alert(
        events=events, gateway=gateway, symbol="FX Vol 20", timeframe="M5",
        side="BUY", confidence=90, bar_time="2026-09-28T12:00:00+00:00",
        simulated=False, planned_entry=237.25,
        planned_stop_loss=235.5, planned_take_profit=240.75,
    )
    notification = transport.send.await_args.args[0]
    rendered = render_telegram(notification)
    assert notification.facts["Tick bid"] == "237.125"
    assert notification.facts["Tick ask"] == "237.375"
    assert notification.facts["Tick time"] == tick.time.isoformat()
    assert notification.facts["Planned entry"] == "237.25"
    assert notification.facts["Planned stop loss"] == "235.5"
    assert notification.facts["TP1"] == "240.75"
    assert notification.facts["Closed bar time"] == "2026-09-28T12:00:00+00:00"
    assert "price unavailable" not in rendered
    assert "101.0" not in rendered and "99.0" not in rendered


@pytest.mark.asyncio
async def test_stale_or_missing_quote_has_no_price_placeholder_number():
    events, transport = _sink()
    stale = Tick(time=datetime.now(timezone.utc) - timedelta(seconds=16),
                 symbol="FX Vol 20", bid=101.0, ask=101.5)
    await events.strategy_signal(
        symbol="FX Vol 20", timeframe="M5", side="SELL", confidence=80,
        bar_time="2026-09-28T12:00:00+00:00", tick=stale,
    )
    facts = transport.send.await_args.args[0].facts
    assert facts["Price"] == "price unavailable"
    assert "Tick bid" not in facts and "Tick ask" not in facts
    assert "Planned entry" not in facts and "TP1" not in facts
    assert "101.0" not in render_telegram(transport.send.await_args.args[0])


@pytest.mark.asyncio
async def test_weltrade_tick_reader_only_reads_terminal(monkeypatch):
    gateway = WeltradeGateway(
        terminal_path=None, login=12345, password="offline-only", server="Weltrade-Demo",
    )
    monkeypatch.setattr(gateway, "_require_connected", lambda: None)
    raw = SimpleNamespace(
        time=int(datetime.now(timezone.utc).timestamp()) + 3 * 3600,
        bid=237.125, ask=237.375,
    )
    read = MagicMock(return_value=raw)
    monkeypatch.setattr("broker.weltrade_gateway.mt5.symbol_info_tick", read)
    tick = await gateway.get_latest_tick("FX Vol 20")
    assert tick is not None and tick.bid == 237.125 and tick.ask == 237.375
    read.assert_called_once_with("FX Vol 20")
