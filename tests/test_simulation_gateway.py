"""Tests for broker.simulation_gateway.SimulationGateway."""

from __future__ import annotations

import pytest

from broker.simulation_gateway import SimulationGateway
from broker.types import OrderRequest, OrderSide, OrderStatus, Timeframe
from core.exceptions import BrokerConnectionError


@pytest.fixture
def gateway() -> SimulationGateway:
    return SimulationGateway(starting_balance=5_000.0, seed=1)


class TestConnectionLifecycle:
    async def test_not_connected_before_connect(self, gateway: SimulationGateway) -> None:
        assert gateway.is_connected is False

    async def test_connected_after_connect(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        assert gateway.is_connected is True

    async def test_disconnected_after_disconnect(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        await gateway.disconnect()
        assert gateway.is_connected is False

    async def test_async_context_manager_connects_and_disconnects(
        self, gateway: SimulationGateway
    ) -> None:
        async with gateway as ctx:
            assert ctx.is_connected is True
        assert gateway.is_connected is False

    @pytest.mark.parametrize(
        "method_name,args",
        [
            ("get_account_info", ()),
            ("get_positions", ()),
            ("get_trade_history", ()),
        ],
    )
    async def test_methods_raise_when_not_connected(
        self, gateway: SimulationGateway, method_name: str, args: tuple
    ) -> None:
        method = getattr(gateway, method_name)
        with pytest.raises(BrokerConnectionError):
            await method(*args)


class TestAccountInfo:
    async def test_reports_starting_balance(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        account = await gateway.get_account_info()
        assert account.balance == 5_000.0
        assert account.account_id == "SIMULATED"


class TestCandles:
    async def test_returns_requested_count(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        candles = await gateway.get_candles("R_100", Timeframe.M5, 50)
        assert len(candles) == 50

    async def test_is_deterministic_for_a_given_seed(self) -> None:
        gateway_a = SimulationGateway(seed=7)
        gateway_b = SimulationGateway(seed=7)
        await gateway_a.connect()
        await gateway_b.connect()
        candles_a = await gateway_a.get_candles("R_100", Timeframe.M1, 10)
        candles_b = await gateway_b.get_candles("R_100", Timeframe.M1, 10)
        assert [c.close for c in candles_a] == [c.close for c in candles_b]

    async def test_candle_prices_are_positive(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        candles = await gateway.get_candles("R_100", Timeframe.H1, 20)
        assert all(c.open > 0 and c.close > 0 and c.high > 0 and c.low > 0 for c in candles)


class TestTickStream:
    async def test_yields_ticks_for_the_requested_symbol(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        ticks = []
        async for tick in gateway.stream_ticks("R_100"):
            ticks.append(tick)
            if len(ticks) == 3:
                break
        assert len(ticks) == 3
        assert all(t.symbol == "R_100" for t in ticks)
        assert all(t.ask > t.bid for t in ticks)


class TestSubmitOrder:
    async def test_order_fills_immediately(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        result = await gateway.submit_order(
            OrderRequest(symbol="R_100", side=OrderSide.BUY, volume=1.0)
        )
        assert result.status is OrderStatus.FILLED
        assert result.order_id.startswith("SIM-")
        assert result.filled_price is not None

    async def test_filled_order_appears_in_positions(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        result = await gateway.submit_order(
            OrderRequest(symbol="R_100", side=OrderSide.SELL, volume=2.0)
        )
        positions = await gateway.get_positions()
        assert any(p.position_id == result.order_id for p in positions)

    async def test_order_ids_are_unique(self, gateway: SimulationGateway) -> None:
        await gateway.connect()
        first = await gateway.submit_order(
            OrderRequest(symbol="R_100", side=OrderSide.BUY, volume=1.0)
        )
        second = await gateway.submit_order(
            OrderRequest(symbol="R_100", side=OrderSide.BUY, volume=1.0)
        )
        assert first.order_id != second.order_id
