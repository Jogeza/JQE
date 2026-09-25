"""Safety and lifecycle tests for the read-only observation daemon."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json
import sqlite3
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
from data.market_observation import closed_observations_from_candles, provider_symbol_for


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
    with sqlite3.connect(config.evidence_path) as connection:
        payload = json.loads(connection.execute("SELECT payload FROM evidence").fetchone()[0])
    assert payload["facts"]["trade_plan"]["schema_version"] == "trade-plan-snapshot-v1"
    telemetry.submit_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_m1_catch_up_processes_every_closed_bar_since_cursor(tmp_path, monkeypatch) -> None:
    start = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    candles = [Candle(
        time=start + timedelta(minutes=index), open=100 + index,
        high=102 + index, low=99 + index, close=101 + index,
        volume=10, source="mt5_demo",
    ) for index in range(6)]
    now = start + timedelta(minutes=7, seconds=5)
    telemetry = FakeTelemetry(candles)
    pair = WatchPair("R_75", Timeframe.M1)
    config = DaemonConfig((pair,), tmp_path / "m1-catch-up.sqlite3", 5, 30, 2)
    daemon = ObservationDaemon(config, lambda: telemetry)
    observations = closed_observations_from_candles(
        candles=candles, canonical_symbol=pair.symbol,
        provider_symbol=provider_symbol_for(canonical_symbol=pair.symbol, source="mt5"),
        source="mt5_demo", timeframe=pair.timeframe, observed_at=now,
    )
    daemon.store.append_signal(pair, observations[0], {"seed": True})
    monkeypatch.setattr(
        observation_daemon, "_evaluate",
        lambda observations, symbol: ({"signal": "NO_TRADE", "confidence": 71}, "RANGE"),
    )
    assert await daemon.observe_pair(telemetry, pair, now)
    with sqlite3.connect(config.evidence_path) as connection:
        rows = connection.execute("SELECT payload FROM evidence ORDER BY rowid").fetchall()
    payloads = [json.loads(row[0]) for row in rows]
    signals = [item for item in payloads if item["event_type"] == "SIGNAL"]
    assert len(signals) == len(observations)
    assert all(item["facts"].get("catch_up") is True for item in signals[1:])
    assert daemon.store.last_close(pair.scope) == observations[-1].closed_at


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
