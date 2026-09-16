"""Offline regression tests for explicit broker-bound quantity semantics."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from broker.deriv_gateway import DerivGateway
from broker.mt5_gateway import MT5Gateway
from broker.simulation_gateway import SimulationGateway
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderRequest, OrderSide
from core.exceptions import ExecutionError
from execution.idempotency import build_execution_idempotency_key
from risk.position_sizing import authorize_execution_quantity


def _key(quantity: ExecutionQuantity) -> str:
    return build_execution_idempotency_key(
        symbol="XAUUSD", side="BUY", quantity=quantity, entry=100,
        stop_loss=98, take_profit=104, signal_time="2026-08-31T00:00:00Z",
    )


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), float("-inf")])
def test_quantity_must_be_positive_and_finite(value: float) -> None:
    with pytest.raises(ValidationError):
        ExecutionQuantity(value=value, unit=ExecutionQuantityUnit.SIMULATION_UNITS)


def test_identity_includes_quantity_value_and_unit() -> None:
    simulation = ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS)
    assert _key(simulation) != _key(ExecutionQuantity(value=2, unit=simulation.unit))
    assert _key(simulation) != _key(ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.DERIV_STAKE))


def test_simulation_sizing_proves_stop_risk_within_authorization() -> None:
    decision = authorize_execution_quantity(
        broker="simulation", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92,
    )
    assert decision.quantity == ExecutionQuantity(
        value=6.25, unit=ExecutionQuantityUnit.SIMULATION_UNITS
    )
    assert decision.risk_verifiable is True
    assert decision.expected_loss_at_stop == pytest.approx(50)
    assert decision.expected_loss_at_stop <= decision.authorized_risk_amount


def test_deriv_conversion_is_unprovable_and_fails_closed() -> None:
    decision = authorize_execution_quantity(
        broker="deriv", balance=10_000, risk_percent=0.5, entry=100, stop_loss=92,
    )
    assert decision.quantity is None
    assert decision.risk_verifiable is False
    assert "loss-model proof is not verified" in decision.reason


@pytest.mark.asyncio
async def test_simulation_rejects_deriv_stake() -> None:
    gateway = SimulationGateway()
    await gateway.connect()
    with pytest.raises(ExecutionError, match="SIMULATION_UNITS"):
        await gateway.submit_order(OrderRequest(
            symbol="XAUUSD", side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.DERIV_STAKE),
            stop_loss=1.0,
        ))


@pytest.mark.asyncio
async def test_deriv_rejects_mt5_lots_before_request() -> None:
    gateway = DerivGateway(app_id="offline", api_token="offline")
    gateway._connected = True
    gateway._request = AsyncMock()
    with pytest.raises(ExecutionError, match="DERIV_STAKE"):
        await gateway.submit_order(OrderRequest(
            symbol="R_100", side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.MT5_LOTS),
            stop_loss=1.0,
        ))
    gateway._request.assert_not_awaited()


@pytest.mark.asyncio
async def test_mt5_rejects_deriv_stake_before_sdk_use() -> None:
    gateway = MT5Gateway()
    gateway._connected = True
    with pytest.raises(ExecutionError, match="MT5_LOTS"):
        await gateway.submit_order(OrderRequest(
            symbol="XAUUSD", side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.DERIV_STAKE),
            stop_loss=1900.0,
        ))
