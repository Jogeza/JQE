from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from broker.demo_guard import DemoOnlyGuard
from broker.types import AccountInfo
from execution.daily_instrument_guard import (
    DAILY_INSTRUMENT_CAP_REACHED,
    DailyInstrumentCapReached,
    DailyInstrumentTradeGuard,
)
from execution.persistence import SQLiteOneShotExecutionGuard
from main import build_execution_composition


def test_atomic_consume_under_race(tmp_path) -> None:
    guard = DailyInstrumentTradeGuard(tmp_path / "daily.sqlite3", limit=20)

    def consume() -> str:
        try:
            guard.consume("mt5:42", "R_75")
            return "allowed"
        except DailyInstrumentCapReached as exc:
            assert exc.reason_code == DAILY_INSTRUMENT_CAP_REACHED
            return "blocked"

    with ThreadPoolExecutor(max_workers=32) as pool:
        outcomes = list(pool.map(lambda _: consume(), range(64)))

    assert outcomes.count("allowed") == 20
    assert outcomes.count("blocked") == 44
    assert guard.usage("mt5:42", "R_75").count == 20


def test_utc_midnight_resets_counter(tmp_path) -> None:
    guard = DailyInstrumentTradeGuard(tmp_path / "daily.sqlite3", limit=1)
    before = datetime(2026, 9, 16, 23, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 9, 17, 0, 0, 0, tzinfo=timezone.utc)
    guard.consume("mt5:42", "R_75", at=before)
    with pytest.raises(DailyInstrumentCapReached):
        guard.consume("mt5:42", "R_75", at=before)
    assert guard.consume("mt5:42", "R_75", at=after).count == 1


def test_instrument_and_scope_are_isolated(tmp_path) -> None:
    guard = DailyInstrumentTradeGuard(tmp_path / "daily.sqlite3", limit=1)
    guard.consume("weltrade:1", "R_75")
    with pytest.raises(DailyInstrumentCapReached):
        guard.consume("weltrade:1", "R_75")
    assert guard.consume("weltrade:1", "FX VOL.50").count == 1
    assert guard.consume("weltrade:2", "R_75").count == 1


def test_remains_blocked_after_exhaustion(tmp_path) -> None:
    guard = DailyInstrumentTradeGuard(tmp_path / "daily.sqlite3", limit=2)
    guard.consume("mt5:42", "R_75")
    guard.consume("mt5:42", "R_75")
    for _ in range(3):
        with pytest.raises(DailyInstrumentCapReached):
            guard.consume("mt5:42", "R_75")
    assert guard.usage("mt5:42", "R_75").count == 2


@pytest.mark.asyncio
async def test_live_composition_uses_daily_guard_alongside_demo_guard(tmp_path) -> None:
    class Gateway:
        async def get_account_info(self):
            return AccountInfo(
                account_id="42", balance=1000, currency="USD",
                server="Weltrade-Demo", trade_mode="demo",
            )

        async def get_positions(self):
            return []

        async def get_trade_history(self, count=100):
            return []

    settings = type("Settings", (), {
        "execution_position_ledger_path": tmp_path / "positions.sqlite3",
        "daily_instrument_trade_store_path": tmp_path / "daily.sqlite3",
        "max_daily_trades_per_instrument": 20,
        "intent_store_path": tmp_path / "intents.sqlite3",
    })()

    composition = await build_execution_composition(
        Gateway(), broker="weltrade_demo", active_settings=settings,
    )
    verification = DemoOnlyGuard.assert_demo_account(
        "mt5", {"login": 42, "trade_mode": 0},
        evidence_store_path=tmp_path / "evidence.sqlite3",
    )

    assert isinstance(composition.daily_instrument_guard, DailyInstrumentTradeGuard)
    assert not isinstance(composition.daily_instrument_guard, SQLiteOneShotExecutionGuard)
    assert verification.status == "PASSED"
    assert composition.daily_instrument_guard.consume(
        composition.identity.scope, "R_75"
    ).count == 1
