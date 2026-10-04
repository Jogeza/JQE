"""Offline checks for the separately armed Weltrade supervisor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from execution.safety import DailyStateAuthority, EmergencyStopState
import monitoring.weltrade_execution_supervisor as supervisor
import main


def _settings():
    return SimpleNamespace(
        broker_execution_enabled=True, effective_broker="weltrade",
        market_data_source="broker", emergency_stop=EmergencyStopState.CLEAR,
    )


def test_stopped_heartbeat_has_timestamp(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(supervisor, "HEARTBEAT_PATH", path)
    monkeypatch.setattr(supervisor, "settings", _settings())
    supervisor._publish(cycle=1, status="STOPPED", reason="CancelledError")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["status"] == "STOPPED"
    assert payload["reason"] == "CancelledError"
    assert datetime.now(timezone.utc) - datetime.fromisoformat(payload["updated_at"]) < timedelta(seconds=5)


@pytest.mark.asyncio
async def test_shared_env_cannot_arm_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "settings", _settings())
    monkeypatch.delenv("JQE_BROKER_EXECUTION_ENABLED", raising=False)
    runner = AsyncMock()
    monkeypatch.setattr(supervisor, "run_watchlist", runner)
    with pytest.raises(RuntimeError, match="process-local true flag"):
        await supervisor.run_cycle_once()
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_blocks_before_canonical_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "settings", _settings())
    monkeypatch.setenv("JQE_BROKER_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", AsyncMock())
    monkeypatch.setattr(supervisor, "evaluate", lambda settings: SimpleNamespace(
        daily_state_authority=DailyStateAuthority.NOT_AUTHORITATIVE,
        reason_codes=("DAILY_HISTORY_UNAVAILABLE", "READ_ONLY_PREFLIGHT_NO_ORDER_INTENT"),
    ))
    runner = AsyncMock()
    monkeypatch.setattr(supervisor, "run_watchlist", runner)
    with pytest.raises(RuntimeError, match="preflight blocked"):
        await supervisor.run_cycle_once()
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_halt_blocks_preflight_and_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(supervisor, "settings", _settings())
    monkeypatch.setenv("JQE_BROKER_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(
        supervisor, "monitor_weltrade_closes",
        AsyncMock(side_effect=RuntimeError("CLOSE_UNCONFIRMED")),
    )
    preflight = AsyncMock()
    runner = AsyncMock()
    monkeypatch.setattr(supervisor, "evaluate", preflight)
    monkeypatch.setattr(supervisor, "run_watchlist", runner)
    with pytest.raises(RuntimeError, match="CLOSE_UNCONFIRMED"):
        await supervisor.run_cycle_once()
    preflight.assert_not_awaited()
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_preflight_uses_only_canonical_watchlist_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "settings", _settings())
    monkeypatch.setenv("JQE_BROKER_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", AsyncMock())
    monkeypatch.setattr(supervisor, "evaluate", lambda settings: SimpleNamespace(
        daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
        reason_codes=("READ_ONLY_PREFLIGHT_NO_ORDER_INTENT",),
    ))
    runner = AsyncMock(return_value=("NO_TRADE",))
    monkeypatch.setattr(supervisor, "run_watchlist", runner)
    assert await supervisor.run_cycle_once() == ("NO_TRADE",)
    runner.assert_awaited_once_with()


def test_bare_main_refuses_enabled_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setattr(main.sys, "argv", ["main.py"])
    runner = AsyncMock()
    monkeypatch.setattr(main.asyncio, "run", runner)
    with pytest.raises(SystemExit, match="bare main.py is disabled"):
        main.main()
    runner.assert_not_called()


@pytest.mark.asyncio
async def test_direct_live_run_refuses_without_supervisor_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", _settings())
    gateway = AsyncMock()
    monkeypatch.setattr(main, "get_gateway", gateway)
    with pytest.raises(Exception, match="requires the Weltrade execution supervisor"):
        await main.run(symbol="FX VOL 20", timeframe_name="M1")
    gateway.assert_not_called()


@pytest.mark.asyncio
async def test_supervisor_scope_is_active_only_during_approved_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "settings", _settings())
    monkeypatch.setattr(main, "settings", _settings())
    monkeypatch.setenv("JQE_BROKER_EXECUTION_ENABLED", "true")
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", AsyncMock())
    monkeypatch.setattr(supervisor, "evaluate", lambda settings: SimpleNamespace(
        daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
        reason_codes=("READ_ONLY_PREFLIGHT_NO_ORDER_INTENT",),
    ))

    async def runner():
        main._require_supervisor_for_live_execution()
        return ("NO_TRADE",)

    monkeypatch.setattr(supervisor, "run_watchlist", runner)
    assert await supervisor.run_cycle_once() == ("NO_TRADE",)
    with pytest.raises(Exception, match="requires the Weltrade execution supervisor"):
        main._require_supervisor_for_live_execution()


@pytest.mark.asyncio
async def test_heartbeat_stops_on_cancelled_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mutex:
        def __init__(self, path):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    statuses = []
    monkeypatch.setattr(supervisor, "_require_process_authorization", lambda: None)
    close_monitor = AsyncMock()
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", close_monitor)
    monkeypatch.setattr(supervisor, "ObservationMutex", Mutex)
    monkeypatch.setattr(supervisor, "_publish", lambda **kwargs: statuses.append(kwargs))
    monkeypatch.setattr(supervisor.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await supervisor.run_forever()
    assert [item["status"] for item in statuses] == ["STARTING", "STOPPED"]
    assert statuses[-1]["reason"] == "CancelledError"
    close_monitor.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_stops_after_cycle_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mutex:
        def __init__(self, path):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    statuses = []
    monkeypatch.setattr(supervisor, "_require_process_authorization", lambda: None)
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", AsyncMock())
    monkeypatch.setattr(supervisor, "ObservationMutex", Mutex)
    monkeypatch.setattr(supervisor, "_publish", lambda **kwargs: statuses.append(kwargs))
    monkeypatch.setattr(supervisor.asyncio, "sleep", AsyncMock(return_value=None))
    monkeypatch.setattr(supervisor, "_wait_for_cycle", AsyncMock())
    monkeypatch.setattr(supervisor, "run_cycle_once", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        await supervisor.run_forever()
    assert [item["status"] for item in statuses] == ["STARTING", "BLOCKED", "STOPPED"]
    assert statuses[-1]["reason"] == "RuntimeError"


@pytest.mark.asyncio
async def test_position_limit_keeps_monitor_alive_without_running_signals(monkeypatch):
    class Mutex:
        def __init__(self, path): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
    blocked = supervisor.PreflightBlocked(SimpleNamespace(
        daily_state_authority=DailyStateAuthority.AUTHORITATIVE,
        reason_codes=("OPEN_POSITION_LIMIT_REACHED", "READ_ONLY_PREFLIGHT_NO_ORDER_INTENT"),
    ))
    statuses = []
    monkeypatch.setattr(supervisor, "_require_process_authorization", lambda: None)
    monkeypatch.setattr(supervisor, "monitor_weltrade_closes", AsyncMock())
    monkeypatch.setattr(supervisor, "ObservationMutex", Mutex)
    monkeypatch.setattr(supervisor, "_publish", lambda **kw: statuses.append(kw))
    monkeypatch.setattr(supervisor, "_wait_for_cycle", AsyncMock(side_effect=[None, asyncio.CancelledError()]))
    monkeypatch.setattr(supervisor, "run_cycle_once", AsyncMock(side_effect=blocked))
    runner = AsyncMock()
    monkeypatch.setattr(supervisor, "run_watchlist", runner)
    with pytest.raises(asyncio.CancelledError):
        await supervisor.run_forever()
    assert [s["status"] for s in statuses] == ["STARTING", "BLOCKED", "STOPPED"]
    assert statuses[1]["reason"] == "OPEN_POSITION_LIMIT_REACHED"
    runner.assert_not_awaited()


def test_position_retry_requires_only_known_limit_and_authoritative_history():
    for authority, reasons in [
        (DailyStateAuthority.NOT_AUTHORITATIVE, ("OPEN_POSITION_LIMIT_REACHED", "READ_ONLY_PREFLIGHT_NO_ORDER_INTENT")),
        (DailyStateAuthority.AUTHORITATIVE, ("OPEN_POSITION_LIMIT_REACHED", "POST_FILL_INTEGRITY_HALT", "READ_ONLY_PREFLIGHT_NO_ORDER_INTENT")),
    ]:
        assert not supervisor.PreflightBlocked(SimpleNamespace(
            daily_state_authority=authority, reason_codes=reasons)).retry_position_limit
