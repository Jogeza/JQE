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
            "contracts_for": {
                "contracts_for": {
                    "available": [
                        {
                            "contract_type": "MULTUP",
                            "multiplier_range": [100, 200],
                        },
                        {
                            "contract_type": "MULTDOWN",
                            "multiplier_range": [100, 200],
                        },
                    ]
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
                stop_loss=5.0,
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
            stop_loss=5.0,
            idempotency_key="idemp-deriv-2",
        )
        with pytest.raises(UnsafeBrokerAccountError):
            await gateway.submit_order(order)


class TestMT5DemoGateway:
    @pytest.mark.asyncio
    async def test_read_only_demo_connection_does_not_require_terminal_trading_permission(self) -> None:
        mock_info = MagicMock(login=12345, server="DemoServer", trade_mode=0)
        mock_term = MagicMock(connected=True, trade_allowed=False, tradeapi_disabled=False)
        gateway = MT5DemoGateway()
        with patch("broker.mt5_gateway.mt5_connect", return_value=True), \
             patch("broker.mt5_gateway.mt5.account_info", return_value=mock_info), \
             patch("broker.mt5_gateway.mt5.terminal_info", return_value=mock_term), \
             patch("broker.mt5_demo.mt5.account_info", return_value=mock_info):
            await gateway.connect()
            assert gateway.is_connected is True
            assert gateway._verify_connection_identity(require_trading=True) is False

    @pytest.mark.asyncio
    async def test_submit_never_reaches_order_send_when_terminal_trading_is_disabled(self) -> None:
        account = MagicMock(login=12345, server="DemoServer", trade_mode=0)
        terminal = MagicMock(connected=True, trade_allowed=False, tradeapi_disabled=False)
        gateway = MT5DemoGateway()
        gateway._connected = True
        order = OrderRequest(
            symbol="XAUUSD", side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=0.01, unit=ExecutionQuantityUnit.MT5_LOTS),
            stop_loss=1900.0,
        )
        with patch("broker.mt5_demo.mt5.account_info", return_value=account), \
             patch("broker.mt5_gateway.mt5.account_info", return_value=account), \
             patch("broker.mt5_gateway.mt5.terminal_info", return_value=terminal), \
             patch("broker.mt5_gateway.mt5.order_send") as order_send:
            with pytest.raises(BrokerConnectionError, match="pre-submit readiness"):
                await gateway.submit_order(order)
            order_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_account_currency_risk_uses_broker_profit_and_margin(self) -> None:
        gateway = MT5DemoGateway()
        gateway._connected = True
        info = MagicMock(
            trade_contract_size=100.0, trade_tick_size=0.01, trade_tick_value=1.0,
            trade_tick_value_profit=1.0, trade_tick_value_loss=1.0, point=0.01,
            volume_min=0.01, volume_step=0.01, volume_max=100.0,
        )
        account = MagicMock(currency="USD", margin_free=5000.0)
        with patch.object(gateway, "_resolve_symbol", return_value="XAUUSD"), \
             patch("broker.mt5_demo.mt5.symbol_info", return_value=info), \
             patch("broker.mt5_demo.mt5.symbol_info_tick", return_value=MagicMock(ask=2000.0)), \
             patch("broker.mt5_demo.mt5.account_info", return_value=account), \
             patch("broker.mt5_demo.mt5.order_calc_margin", return_value=50.0), \
             patch("broker.mt5_demo.mt5.order_calc_profit", side_effect=[-1000.0, -100.0]):
            quantity, facts = await gateway.authorize_account_currency_risk(
                symbol="XAUUSD", side=OrderSide.BUY, balance=10000.0,
                risk_percent=1.0, entry=2000.0, stop_loss=1990.0,
            )
        assert quantity.value == 0.1
        assert facts["authorized_risk_amount"] == 100.0
        assert facts["expected_loss_at_stop"] == 100.0
        assert facts["margin_requirement"] == 50.0

    @pytest.mark.asyncio
    async def test_instrument_preflight_fails_closed_on_missing_tick_value(self) -> None:
        gateway = MT5DemoGateway()
        gateway._connected = True
        info = MagicMock(
            trade_contract_size=100.0, trade_tick_size=0.01, trade_tick_value=0.0,
            trade_tick_value_profit=0.0, trade_tick_value_loss=0.0, point=0.01,
            volume_min=0.01,
        )
        with patch.object(gateway, "_resolve_symbol", return_value="XAUUSD"), \
             patch("broker.mt5_demo.mt5.symbol_info", return_value=info), \
             patch("broker.mt5_demo.mt5.symbol_info_tick", return_value=MagicMock(ask=2000.0)), \
             patch("broker.mt5_demo.mt5.account_info", return_value=MagicMock(currency="USD")):
            with pytest.raises(BrokerConnectionError, match="invalid specifications"):
                await gateway.verify_instrument_risk_spec("XAUUSD")

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
            stop_loss=1890.0,
            idempotency_key="idemp-mt5-1",
        )

        mock_sym_info = MagicMock(digits=2, point=0.01, trade_stops_level=0, trade_mode=4,
                                  volume_min=0.01, volume_max=10.0, volume_step=0.01, filling_mode=1)
        with patch("broker.mt5_demo.mt5.account_info", return_value=mock_info_demo), \
             patch("broker.mt5_gateway.mt5.account_info", return_value=mock_info_demo), \
             patch("broker.mt5_gateway.mt5.terminal_info", return_value=mock_term), \
             patch("broker.mt5_gateway.mt5.symbol_select", return_value=True), \
             patch("broker.mt5_gateway.mt5.symbol_info", return_value=mock_sym_info), \
             patch("broker.mt5_gateway.mt5.symbol_info_tick", return_value=MagicMock(ask=1900.5, bid=1900.3)), \
             patch("broker.mt5_gateway.mt5.order_check", return_value=MagicMock(retcode=0, comment="Done")), \
             patch("broker.mt5_gateway.mt5.SYMBOL_TRADE_MODE_DISABLED", 0), \
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
            stop_loss=1890.0,
            idempotency_key="idemp-mt5-real",
        )

        with patch("broker.mt5_demo.mt5.account_info", return_value=mock_info_real), \
             patch("broker.mt5_gateway.mt5.order_send") as mock_send:
            with pytest.raises(UnsafeBrokerAccountError, match="NOT authoritatively verified as DEMO"):
                await gateway.submit_order(order)
            mock_send.assert_not_called()
