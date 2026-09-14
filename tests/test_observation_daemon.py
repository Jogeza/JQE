"""Safety and lifecycle tests for the read-only observation daemon."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from broker.types import AccountInfo, Candle, Timeframe
from config.settings import Settings
from monitoring import observation_daemon
from monitoring.observation_daemon import (
    DaemonConfig,
    ObservationDaemon,
    WatchPair,
    parse_watch_list,
)
from monitoring.observation_window import read_observation_cycles, read_observation_health


def _candles(close_at: datetime, count: int = 501) -> list[Candle]:
    start = close_at - timedelta(hours=count)
    return [Candle(
        time=start + timedelta(hours=index), open=100 + index,
        high=102 + index, low=99 + index, close=101 + index,
        volume=10, source="mt5_demo",
    ) for index in range(count)]


class FakeTelemetry:
    def __init__(self, candles: list[Candle]) -> None:
        self.connect = AsyncMock()
        self.disconnect = AsyncMock()
        self.get_account_info = AsyncMock(return_value=AccountInfo(
            account_id="41163130", balance=10_000, equity=10_000,
            currency="USD", trade_mode="demo",
        ))
        self.get_candles = AsyncMock(return_value=candles)
        self.get_positions = AsyncMock(return_value=[])
        self.submit_order = AsyncMock(side_effect=AssertionError("forbidden capability"))


def test_dedicated_watch_list_ignores_default_timeframe_and_execution_flag(tmp_path) -> None:
    common = {
        "observation_symbols": "R_75:H1,EURUSD:M15",
        "observation_evidence_path": tmp_path / "observations.evidence.sqlite3",
        "default_timeframe": "M5",
        "_env_file": None,
    }
    disabled = DaemonConfig.from_settings(Settings(**common, broker_execution_enabled=False))
    enabled = DaemonConfig.from_settings(Settings(**common, broker_execution_enabled=True))
    assert disabled == enabled
    assert disabled.watches == (
        WatchPair("R_75", Timeframe.H1), WatchPair("EURUSD", Timeframe.M15)
    )
    assert parse_watch_list("R_75:H1")[0].timeframe is Timeframe.H1


def test_daemon_module_has_no_mutating_architecture_dependencies() -> None:
    source = inspect.getsource(observation_daemon)
    forbidden = (
        "AsyncTradeExecutor", "execution.policy", "ExecutionIntent",
        "OrderRequest", "OrderSide", "submit_order", "order_send",
        "SQLiteOneShotExecutionGuard",
    )
    assert all(value not in source for value in forbidden)
    assert "OBSERVATION_HEARTBEAT" in source


@pytest.mark.asyncio
async def test_one_signal_per_close_dedupes_and_never_uses_fake_mutator(tmp_path, monkeypatch) -> None:
    now = datetime(2026, 9, 14, 12, 0, 5, tzinfo=timezone.utc)
    telemetry = FakeTelemetry(_candles(now.replace(second=0, microsecond=0)))
    config = DaemonConfig(
        (WatchPair("R_75", Timeframe.H1),),
        tmp_path / "daemon.evidence.sqlite3", 5, 30, 2,
    )
    daemon = ObservationDaemon(config, lambda: telemetry)
    monkeypatch.setattr(
        observation_daemon, "_evaluate",
        lambda observations, symbol: ({"signal": "NO_TRADE", "confidence": 71}, "RANGE"),
    )
    assert await daemon.observe_pair(telemetry, config.watches[0], now)
    assert not await daemon.observe_pair(telemetry, config.watches[0], now)
    cycles = read_observation_cycles([config.evidence_path])
    assert len(cycles) == 1
    assert cycles[0].symbol == "R_75"
    assert cycles[0].data_freshness == "fresh"
    telemetry.submit_order.assert_not_awaited()


def test_stale_heartbeat_is_reported_unhealthy(tmp_path) -> None:
    config = DaemonConfig(
        (WatchPair("R_75", Timeframe.H1),),
        tmp_path / "daemon.evidence.sqlite3", 5, 30, 2,
    )
    daemon = ObservationDaemon(config, lambda: FakeTelemetry([]))
    old = datetime(2026, 9, 14, 1, tzinfo=timezone.utc)
    daemon._heartbeat(old, healthy=True, error=None)
    health = read_observation_health(
        config.evidence_path,
        now=old + timedelta(hours=3),
        maximum_age=timedelta(hours=2),
    )
    assert health["running"] is False
    assert health["healthy"] is False
    assert health["last_error"] == "STALE_HEARTBEAT"
