"""Integration coverage for the disabled, read-only MT5 composition root."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import main
from broker.types import (
    AccountInfo,
    ExecutionQuantity,
    ExecutionQuantityUnit,
    OrderSide,
    Position,
)
from config import Settings
from execution.reconciliation import BrokerReconciliationState, MT5ReconciliationAdapter


@pytest.mark.asyncio
async def test_mt5_composition_uses_real_identity_ledger_gateway_sizing_and_lifetime_cap(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        broker="mt5",
        broker_execution_enabled=False,
        mt5_expected_environment="demo",
        default_symbol="EURUSD",
        intent_store_path=tmp_path / "intents.sqlite3",
        execution_position_ledger_path=tmp_path / "positions.sqlite3",
        execution_lifetime_store_path=tmp_path / "lifetime.sqlite3",
    )
    gateway = MagicMock()
    gateway.get_account_info = AsyncMock(return_value=AccountInfo(
        account_id="41163130", balance=10_000.0, equity=10_000.0,
        currency="USD", server="Deriv-Demo", trade_mode="demo",
    ))
    position = Position(
        position_id="9001", symbol="EURUSD", side=OrderSide.BUY,
        volume=0.01, open_price=1.1,
    )
    gateway.get_positions = AsyncMock(return_value=[position])
    gateway.get_trade_history = AsyncMock(return_value=[])
    gateway.authorize_account_currency_risk = AsyncMock(return_value=(
        ExecutionQuantity(value=0.01, unit=ExecutionQuantityUnit.MT5_LOTS),
        {"authorized_risk_amount": 5.0, "expected_loss_at_stop": 4.8},
    ))

    composition = await main.build_execution_composition(
        gateway, broker="mt5", active_settings=settings
    )

    assert settings.broker_execution_enabled is False
    assert composition.identity.account_id == "41163130"
    assert composition.identity.account_id != "SIMULATED"
    assert composition.identity.server == "Deriv-Demo"
    assert composition.identity.currency == "USD"
    assert composition.identity.trade_mode == "demo"
    assert isinstance(composition.reconciler, MT5ReconciliationAdapter)

    composition.position_ledger.record_open(
        broker="mt5", symbol="EURUSD", position_id="9001", order_id="8001",
        opened_at=datetime.now(timezone.utc),
    )
    reconciled = await composition.reconciler.reconcile(order_id="8001", symbol="EURUSD")
    assert reconciled.state is BrokerReconciliationState.CONFIRMED_MATCH
    gateway.get_positions.assert_awaited()
    gateway.get_trade_history.assert_awaited()

    sizing = await main.authorize_broker_execution_quantity(
        gateway, broker="mt5", symbol="EURUSD", side=OrderSide.BUY, balance=10_000.0,
        risk_percent=0.05, entry=1.1, stop_loss=1.095,
    )
    assert sizing.quantity == ExecutionQuantity(value=0.01, unit=ExecutionQuantityUnit.MT5_LOTS)
    assert sizing.expected_loss_at_stop == 4.8
    gateway.authorize_account_currency_risk.assert_awaited_once()

    composition.lifetime_guard.consume(composition.identity.scope)
    # A consumed submission slot must not block read-only startup composition.
    second = await main.build_execution_composition(
        gateway, broker="mt5", active_settings=settings
    )
    assert second.lifetime_guard.count(second.identity.scope) == 1


@pytest.mark.asyncio
async def test_mt5_composition_rejects_simulated_identity(tmp_path) -> None:
    settings = Settings(
        _env_file=None, broker="mt5", broker_execution_enabled=False,
        mt5_expected_environment="demo",
        intent_store_path=tmp_path / "intents.sqlite3",
        execution_position_ledger_path=tmp_path / "positions.sqlite3",
        execution_lifetime_store_path=tmp_path / "lifetime.sqlite3",
    )
    gateway = MagicMock()
    gateway.get_account_info = AsyncMock(return_value=AccountInfo(
        account_id="SIMULATED", balance=10_000.0, currency="USD",
        server="Deriv-Demo", trade_mode="demo",
    ))
    with pytest.raises(Exception, match="legacy SIMULATED"):
        await main.build_execution_composition(gateway, broker="mt5", active_settings=settings)
