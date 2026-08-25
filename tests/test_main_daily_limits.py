import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import patch

from broker.base import BrokerGateway
from broker.types import OrderSide, TradeHistoryEntry
from config import settings
from main import run
from risk.risk_controller import _default_engine

pytestmark = pytest.mark.asyncio

@pytest.fixture(autouse=True)
def _reset_risk_engine():
    """Ensure tests start with clean limits."""
    _default_engine.reset_daily_stats()
    _default_engine.max_trades_daily = 3
    _default_engine.max_daily_loss = 2.0
    yield
    _default_engine.reset_daily_stats()


@pytest.fixture
def mock_gateway():
    """Provides access to the SimulationGateway for injecting trades."""
    from broker.factory import get_gateway
    settings.account_balance = 10000.0
    gw = get_gateway(settings)

    # Empty out trade history before each test
    gw._trade_history = []

    return gw


def _create_trade(profit: float, days_ago: int = 0) -> TradeHistoryEntry:
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return TradeHistoryEntry(
        trade_id=f"TEST-{days_ago}",
        symbol="EURUSD",
        side=OrderSide.BUY,
        volume=1.0,
        open_price=1.1000,
        close_price=1.0900 if profit < 0 else 1.1100,
        profit=profit,
        opened_at=now - timedelta(minutes=5),
        closed_at=now,
    )


async def test_loss_is_reconciled(mock_gateway):
    """Test 1: Loss is recorded when reconciliation runs."""
    # Inject $100 loss on a $10,000 simulated balance = 1.0% loss
    trade = _create_trade(profit=-100.0)
    mock_gateway._inject_closed_trade(trade)

    # We mock approve_trade so we can inspect RiskEngine state without actually placing an order
    with patch("main.approve_trade") as mock_approve, patch("main.get_gateway") as mock_get_gw:
        mock_get_gw.return_value = mock_gateway
        mock_approve.return_value = {"approved": False, "reason": "Test mock", "risk_percent": 0.0, "lot_size": 0.0}
        await run()

    assert _default_engine._daily_realized_loss_percent == 1.0


async def test_loss_blocks_next_trade(mock_gateway):
    """Test 2: A loss hitting max_daily_loss blocks the next trade."""
    _default_engine.max_daily_loss = 2.0
    # Inject $250 loss on $10,000 = 2.5% loss (exceeds 2.0%)
    trade = _create_trade(profit=-250.0)
    mock_gateway._inject_closed_trade(trade)

    # We don't mock approve_trade because we want it to reject natively
    # But we mock submit_order so we don't actually trade if it erroneously passes
    with patch.object(mock_gateway, "submit_order") as mock_submit, patch("main.get_gateway") as mock_get_gw:
        mock_get_gw.return_value = mock_gateway
        await run()
        mock_submit.assert_not_called()

    assert _default_engine._daily_realized_loss_percent == 2.5


async def test_idempotency(mock_gateway):
    """Test 3: Reconciliation does not double-count identical trades."""
    trade = _create_trade(profit=-100.0)
    mock_gateway._inject_closed_trade(trade)

    with patch("main.approve_trade") as mock_approve, patch("main.get_gateway") as mock_get_gw:
        mock_get_gw.return_value = mock_gateway
        mock_approve.return_value = {"approved": False, "reason": "Test mock", "risk_percent": 0.0, "lot_size": 0.0}
        # Run main cycle twice
        await run()
        await run()

    # Total loss should be exactly 1.0% (reconciled from scratch each time)
    assert _default_engine._daily_realized_loss_percent == 1.0


async def test_trade_count(mock_gateway):
    """Test 4: Trade count increments correctly and idempotently."""
    trade1 = _create_trade(profit=50.0)
    trade2 = _create_trade(profit=-50.0)
    mock_gateway._inject_closed_trade(trade1)
    mock_gateway._inject_closed_trade(trade2)

    with patch("main.approve_trade") as mock_approve, patch("main.get_gateway") as mock_get_gw:
        mock_get_gw.return_value = mock_gateway
        mock_approve.return_value = {"approved": False, "reason": "Test mock", "risk_percent": 0.0, "lot_size": 0.0}
        await run()
        await run()

    assert _default_engine._daily_trades_count == 2


async def test_new_day(mock_gateway):
    """Test 5: Trades from yesterday do not affect today's limits."""
    # Trade from yesterday
    old_trade = _create_trade(profit=-500.0, days_ago=1)
    # Trade from today
    new_trade = _create_trade(profit=-100.0, days_ago=0)

    mock_gateway._inject_closed_trade(old_trade)
    mock_gateway._inject_closed_trade(new_trade)

    with patch("main.approve_trade") as mock_approve, patch("main.get_gateway") as mock_get_gw:
        mock_get_gw.return_value = mock_gateway
        mock_approve.return_value = {"approved": False, "reason": "Test mock", "risk_percent": 0.0, "lot_size": 0.0}
        await run()

    # Should only record the 1.0% loss from today's trade
    assert _default_engine._daily_realized_loss_percent == 1.0
    assert _default_engine._daily_trades_count == 1
