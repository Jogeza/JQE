"""Offline proof that Weltrade preflight has no order path."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.service as service_module
from api.service import ApplicationService
from config.settings import Settings
from data.watchlist import WatchlistStore
from execution.daily_instrument_guard import DailyInstrumentTradeGuard
from execution.persistence import SQLiteIntentRecordStore
from execution.safety import (
    DailyStateAuthority, EmergencyStopState, ExecutionAuthorization,
    ExecutionMode, ExecutionSafetySnapshot, SQLiteExecutionSafetyStore,
)
from tools import evaluate_execution_safety as preflight


class ReadOnlyTerminal:
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_TYPE_COMMISSION = 3
    DEAL_TYPE_INTEREST = 4
    DEAL_TYPE_BALANCE = 5
    DEAL_TYPE_CREDIT = 6
    DEAL_TYPE_BONUS = 7

    def __init__(self, path: Path, *, mode: int = 0, trade_allowed: bool = True) -> None:
        self.path = path
        self.mode = mode
        self.trade_allowed = trade_allowed
        self.calls: list[str] = []

    def initialize(self, path: str) -> bool:
        self.calls.append("initialize")
        return path == str(self.path.resolve())

    def login(self, login: int, *, password: str, server: str) -> bool:
        self.calls.append("login")
        return login == 12345 and password == "test-only" and server == "Weltrade-Demo"

    def account_info(self):
        self.calls.append("account_info")
        return SimpleNamespace(login=12345, server="Weltrade-Demo", trade_mode=self.mode,
                               balance=100.0, equity=100.0, currency="USD")

    def terminal_info(self):
        self.calls.append("terminal_info")
        return SimpleNamespace(connected=True, path=str(self.path.parent),
                               trade_allowed=self.trade_allowed, tradeapi_disabled=False)

    def history_deals_get(self, start, end):
        self.calls.append("history_deals_get")
        return ()

    def symbol_info_tick(self, symbol):
        self.calls.append("symbol_info_tick")
        return SimpleNamespace(time=int(datetime.now(timezone.utc).timestamp()) + 3 * 3600)

    def positions_get(self):
        self.calls.append("positions_get")
        return ()

    def shutdown(self) -> None:
        self.calls.append("shutdown")


def _settings(tmp_path: Path) -> Settings:
    terminal_path = tmp_path / "terminal64.exe"
    terminal_path.touch()
    watchlist = tmp_path / "watchlist.sqlite3"
    WatchlistStore(watchlist, default_seeds=[]).add_item("FX Vol 20", "M5")
    daily = tmp_path / "daily.sqlite3"
    DailyInstrumentTradeGuard(daily, limit=20)
    intents = tmp_path / "intents.sqlite3"
    SQLiteIntentRecordStore(intents)
    return Settings(
        _env_file=None, broker="weltrade", market_data_source="broker",
        broker_execution_enabled=False, emergency_stop=EmergencyStopState.CLEAR,
        weltrade_terminal_path=terminal_path, weltrade_demo_login=12345,
        weltrade_demo_password="test-only", weltrade_demo_server="Weltrade-Demo",
        execution_safety_store_path=tmp_path / "safety.sqlite3",
        watchlist_store_path=watchlist, daily_instrument_trade_store_path=daily,
        intent_store_path=intents,
    )


def test_evaluator_has_no_order_gateway_or_mutation_call() -> None:
    tree = ast.parse(Path(preflight.__file__).read_text(encoding="utf-8"))
    banned = {"order_send", "order_check", "submit_order", "get_gateway", "AsyncTradeExecutor"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not banned.intersection(names | attrs)
    assert "broker.factory" not in Path(preflight.__file__).read_text(encoding="utf-8")


def test_read_only_run_replaces_stale_snapshot_with_fresh_blocked_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    store = SQLiteExecutionSafetyStore(settings.execution_safety_store_path, initialize=True)
    store.publish(ExecutionSafetySnapshot(
        observed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        emergency_stop_state=EmergencyStopState.CLEAR,
        execution_mode=ExecutionMode.DURABLE, broker="weltrade",
        environment=settings.environment, durable_executor_enabled=True,
        daily_state_authority=DailyStateAuthority.NOT_EVALUATED,
        unresolved_intent_count=0, unresolved_intent_blocked=False,
        execution_authorization=ExecutionAuthorization.NOT_EVALUATED,
        reason_codes=("NOT_EVALUATED",),
    ))
    guard = []
    monkeypatch.setattr(preflight.DemoOnlyGuard, "assert_demo_account",
                        lambda broker, raw: guard.append((broker, raw.trade_mode)))
    terminal = ReadOnlyTerminal(settings.weltrade_terminal_path)
    assert not hasattr(terminal, "order_send")
    assert not hasattr(terminal, "submit_order")

    result = preflight.evaluate(settings, terminal=terminal)
    assert guard == [("weltrade", 0)]
    assert terminal.calls == ["initialize", "login", "account_info", "terminal_info",
                              "symbol_info_tick", "history_deals_get", "positions_get", "shutdown"]
    assert result.execution_authorization is ExecutionAuthorization.BLOCKED
    assert result.daily_state_authority is DailyStateAuthority.AUTHORITATIVE
    assert (datetime.now(timezone.utc) - result.observed_at).total_seconds() < 5
    assert store.read() == result
    risk = store.read_risk()
    assert risk is not None and risk.balance == 100.0
    assert risk.execution_quantity_available is False
    monkeypatch.setattr(service_module, "settings", settings)
    api_snapshot = object.__new__(ApplicationService).get_execution_safety()
    assert api_snapshot.observation_state == "OBSERVED"
    assert api_snapshot.execution_authorization == "BLOCKED"


def test_disabled_terminal_remains_blocked_without_order_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(preflight.DemoOnlyGuard, "assert_demo_account", lambda broker, raw: None)
    terminal = ReadOnlyTerminal(settings.weltrade_terminal_path, trade_allowed=False)
    result = preflight.evaluate(settings, terminal=terminal)
    assert "TERMINAL_TRADING_DISABLED" in result.reason_codes
    assert result.execution_authorization is ExecutionAuthorization.BLOCKED
    assert terminal.calls[-1] == "shutdown"
