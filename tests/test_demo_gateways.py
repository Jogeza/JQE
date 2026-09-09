"""Tests for DerivDemoGateway and MT5DemoGateway.

Validates that both gateways strictly forbid non-demo operations and fail closed
on any real-money account data or malformed response.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from broker.deriv_demo import DerivDemoGateway
from broker.mt5_demo import MT5DemoGateway
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderRequest, OrderSide, OrderStatus
from core.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    ExecutionError,
    UnsafeBrokerAccountError,
)
from tests.test_deriv_gateway import FakeDerivConnection


class TestDerivDemoGateway:
    @pytest.mark.asyncio
    async def test_connect_with_demo_account_succeeds(self) -> None:
        fake_conn = FakeDerivConnection({
            "authorize": {
                "authorize": {
                    "loginid": "VRTC12345",
                    "currency": "USD",
                    "is_virtual": 1,
                }
            }
        })
        gateway = DerivDemoGateway(api_token="test-token", app_id="1089")
        with patch("broker.deriv_gateway.websockets.connect", new=AsyncMock(return_value=fake_conn)):
            await gateway.connect()
            assert gateway.is_connected is True
            assert gateway._demo_verified is True
            await gateway.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_real_account_fails_closed(self) -> None:
        fake_conn = FakeDerivConnection({
            "authorize": {
                "authorize": {
                    "loginid": "CR12345",
                    "currency": "USD",
                    "is_virtual": 0,
                }
            }
        })
        gateway = DerivDemoGateway(api_token="test-token", app_id="1089")
        with patch("broker.deriv_gateway.websockets.connect", new=AsyncMock(return_value=fake_conn)):
            with pytest.raises(BrokerAuthenticationError):
                await gateway.connect()
            assert gateway.is_connected is False

    @pytest.mark.asyncio
    async def test_submit_order_on_verified_demo_succeeds(self) -> None:
        fake_conn = FakeDerivConnection({
            "authorize": {
                "authorize": {
                    "loginid": "VRTC12345",
                    "currency": "USD",
                    "is_virtual": 1,
                }
            },
            "proposal": {
                "proposal": {
                    "id": "prop-demo-1",
                    "ask_price": 10.0,
                }
            },
            "buy": {
                "buy": {
                    "contract_id": 9990001,
                    "buy_price": 10.0,
                    "transaction_id": 8880001,
                }
            },
        })
        gateway = DerivDemoGateway(api_token="test-token", app_id="1089")
        with patch("broker.deriv_gateway.websockets.connect", new=AsyncMock(return_value=fake_conn)):
            await gateway.connect()

            order = OrderRequest(
                symbol="R_100",
                side=OrderSide.BUY,
                quantity=ExecutionQuantity(value=10.0, unit=ExecutionQuantityUnit.DERIV_STAKE),
                idempotency_key="idemp-deriv-1",
            )
            result = await gateway.submit_order(order)
            assert result.status is OrderStatus.FILLED
            assert result.order_id == "9990001"
            assert result.filled_price == 10.0
            await gateway.disconnect()

    @pytest.mark.asyncio
    async def test_submit_order_fails_closed_if_demo_not_verified(self) -> None:
        gateway = DerivDemoGateway(api_token="test-token", app_id="1089")
        gateway._connected = True
        gateway._demo_verified = False
        gateway._account_id = "CR_UNVERIFIED"

        order = OrderRequest(
            symbol="R_100",
            side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=10.0, unit=ExecutionQuantityUnit.DERIV_STAKE),
            idempotency_key="idemp-deriv-2",
        )
        with pytest.raises(UnsafeBrokerAccountError):
            await gateway.submit_order(order)


class TestMT5DemoGateway:
    @pytest.mark.asyncio
    async def test_connect_with_demo_trade_mode_succeeds(self) -> None:
        mock_info = MagicMock(login=12345, server="DemoServer", trade_mode=0)
        mock_term = MagicMock(connected=True, trade_allowed=True, tradeapi_disabled=False)

        gateway = MT5DemoGateway(login=12345, server="DemoServer")
        with patch("broker.mt5_gateway.mt5_connect", return_value=True), \
             patch("broker.mt5_gateway.mt5.account_info", return_value=mock_info), \
             patch("broker.mt5_gateway.mt5.terminal_info", return_value=mock_term), \
             patch("broker.mt5_demo.mt5.account_info", return_value=mock_info):
            await gateway.connect()
            assert gateway.is_connected is True
            assert gateway._demo_verified is True
            await gateway.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_real_trade_mode_fails_closed(self) -> None:
        mock_info = MagicMock(login=12345, server="LiveServer", trade_mode=2)
        mock_term = MagicMock(connected=True, trade_allowed=True, tradeapi_disabled=False)

        gateway = MT5DemoGateway(login=12345, server="LiveServer")
        with patch("broker.mt5_gateway.mt5_connect", return_value=True), \
             patch("broker.mt5_gateway.mt5_disconnect") as mock_disc, \
             patch("broker.mt5_gateway.mt5.account_info", return_value=mock_info), \
             patch("broker.mt5_gateway.mt5.terminal_info", return_value=mock_term), \
             patch("broker.mt5_demo.mt5.account_info", return_value=mock_info):
            with pytest.raises((BrokerConnectionError, UnsafeBrokerAccountError)):
                await gateway.connect()
            assert gateway.is_connected is False
            mock_disc.assert_called()

    @pytest.mark.asyncio
    async def test_submit_order_verifies_demo_before_send(self) -> None:
        mock_info_demo = MagicMock(login=12345, server="DemoServer", trade_mode=0)
        mock_term = MagicMock(connected=True, trade_allowed=True, tradeapi_disabled=False)
        mock_order_send_result = MagicMock(
            retcode=10009,  # TRADE_RETCODE_DONE
            order=77777,
            price=1900.5,
        )

        gateway = MT5DemoGateway(login=12345, server="DemoServer")
        gateway._connected = True

        order = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=0.01, unit=ExecutionQuantityUnit.MT5_LOTS),
            idempotency_key="idemp-mt5-1",
        )

        mock_sym_info = MagicMock(digits=2, point=0.01, trade_stops_level=0)
        with patch("broker.mt5_demo.mt5.account_info", return_value=mock_info_demo), \
             patch("broker.mt5_gateway.mt5.account_info", return_value=mock_info_demo), \
             patch("broker.mt5_gateway.mt5.terminal_info", return_value=mock_term), \
             patch("broker.mt5_gateway.mt5.symbol_select", return_value=True), \
             patch("broker.mt5_gateway.mt5.symbol_info", return_value=mock_sym_info), \
             patch("broker.mt5_gateway.mt5.symbol_info_tick", return_value=MagicMock(ask=1900.5, bid=1900.3)), \
             patch("broker.mt5_gateway.mt5.order_send", return_value=mock_order_send_result) as mock_send, \
             patch.object(gateway, "_resolve_symbol", return_value="XAUUSD"):
            result = await gateway.submit_order(order)
            assert result.status is OrderStatus.FILLED
            assert result.order_id == "77777"
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_order_aborts_if_account_is_real(self) -> None:
        # If terminal account is real (trade_mode=2), submit_order MUST raise UnsafeBrokerAccountError
        # and NEVER call order_send!
        mock_info_real = MagicMock(login=99999, trade_mode=2)

        gateway = MT5DemoGateway(login=99999)
        gateway._connected = True

        order = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=0.01, unit=ExecutionQuantityUnit.MT5_LOTS),
            idempotency_key="idemp-mt5-real",
        )

        with patch("broker.mt5_demo.mt5.account_info", return_value=mock_info_real), \
             patch("broker.mt5_gateway.mt5.order_send") as mock_send:
            with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
                await gateway.submit_order(order)
            mock_send.assert_not_called()
