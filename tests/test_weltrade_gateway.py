from unittest.mock import MagicMock, patch

import pytest
from tests.mt5_stubs import activate_gateway

from broker.types import OrderRequest, OrderSide, OrderStatus
from broker.weltrade_gateway import WeltradeGateway
from core.exceptions import BrokerConnectionError, UnsafeBrokerAccountError


@pytest.mark.asyncio
async def test_connect_verifies_weltrade_demo_identity() -> None:
    account = MagicMock(login=42, server="Weltrade-Demo", trade_mode=0)
    terminal = MagicMock(connected=True, trade_allowed=True, tradeapi_disabled=False)
    gateway = WeltradeGateway(login=42, password="test-password", server="Weltrade-Demo", expected_environment="demo")
    with (
        patch("broker.mt5_gateway.mt5_connect", return_value=True),
        patch("broker.mt5_gateway.mt5.account_info", return_value=account),
        patch("broker.mt5_gateway.mt5.terminal_info", return_value=terminal),
        patch("broker.mt5_demo.mt5.account_info", return_value=account),
        patch("broker.weltrade_gateway.mt5.account_info", return_value=account),
    ):
        await gateway.connect()
    assert gateway.is_connected is True
    assert gateway._demo_verified is True


@pytest.mark.asyncio
async def test_connect_rejects_non_weltrade_server() -> None:
    account = MagicMock(login=42, server="OtherBroker-Demo", trade_mode=0)
    terminal = MagicMock(connected=True, trade_allowed=True, tradeapi_disabled=False)
    gateway = WeltradeGateway(login=42, password="test-password", server="OtherBroker-Demo", expected_environment="demo")
    with (
        patch("broker.mt5_gateway.mt5_connect", return_value=True),
        patch("broker.mt5_gateway.mt5.account_info", return_value=account),
        patch("broker.mt5_gateway.mt5.terminal_info", return_value=terminal),
        patch("broker.mt5_demo.mt5.account_info", return_value=account),
        patch("broker.weltrade_gateway.mt5.account_info", return_value=account),
        patch("broker.mt5_gateway.mt5_disconnect"),
    ):
        with pytest.raises(BrokerConnectionError, match="Weltrade terminal identity"):
            await gateway.connect()


@pytest.mark.asyncio
async def test_connect_rejects_missing_credentials(monkeypatch) -> None:
    from config import settings
    monkeypatch.setattr(settings, "weltrade_login", None)
    monkeypatch.setattr(settings, "weltrade_demo_login", None)
    monkeypatch.setattr(settings, "weltrade_password", None)
    monkeypatch.setattr(settings, "weltrade_demo_password", None)
    monkeypatch.setattr(settings, "weltrade_server", None)
    monkeypatch.setattr(settings, "weltrade_demo_server", None)
    gateway = WeltradeGateway(login=None, password=None, server=None, expected_environment="demo")
    with pytest.raises(BrokerConnectionError, match="Weltrade demo login configuration missing"):
        await gateway.connect()


def test_synthetic_symbol_resolves_from_terminal_catalogue() -> None:
    gateway = WeltradeGateway(expected_environment="demo")
    item = MagicMock(name="symbol")
    item.name = "FX Vol.75"
    item.visible = True
    with (
        patch("broker.weltrade_gateway.mt5.symbol_info", return_value=None),
        patch("broker.weltrade_gateway.mt5.symbols_get", return_value=[item]),
    ):
        assert gateway._resolve_symbol("R_75") == "FX Vol.75"


@pytest.mark.asyncio
async def test_submit_rechecks_demo_before_shared_mt5_order_path() -> None:
    gateway = WeltradeGateway(expected_environment="demo")
    activate_gateway(gateway)
    gateway._demo_verified = True
    real_account = MagicMock(login=42, server="Weltrade-Live", trade_mode=2)
    order = OrderRequest(
        symbol="R_75", side=OrderSide.BUY,
        quantity={"value": 0.01, "unit": "MT5_LOTS"}, stop_loss=90.0,
    )
    with (
        patch("broker.mt5_demo.mt5.account_info", return_value=real_account),
        patch("broker.mt5_gateway.mt5.order_send") as order_send,
    ):
        with pytest.raises(UnsafeBrokerAccountError):
            await gateway.submit_order(order)
    order_send.assert_not_called()
