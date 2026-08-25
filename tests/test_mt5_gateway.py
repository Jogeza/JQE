"""Tests for broker.mt5_gateway.MT5Gateway.

MT5's real terminal isn't available in this environment (Windows-only
SDK — see tests/conftest.py). These tests patch the module-level
``mt5`` object and MT5Gateway's collaborators directly, verifying
MT5Gateway's own mapping/error-handling logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from broker.mt5_gateway import MT5Gateway
from broker.types import OrderRequest, OrderSide, OrderStatus, Timeframe
from core.exceptions import BrokerConnectionError, ExecutionError, MarketDataError


@pytest.fixture
def gateway() -> MT5Gateway:
    return MT5Gateway()


class TestConnectionLifecycle:
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_connect_success(self, mock_connect: MagicMock, gateway: MT5Gateway) -> None:
        await gateway.connect()
        assert gateway.is_connected is True

    @patch("broker.mt5_gateway.mt5_connect", return_value=False)
    async def test_connect_failure_raises(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        with pytest.raises(BrokerConnectionError):
            await gateway.connect()
        assert gateway.is_connected is False

    @patch("broker.mt5_gateway.mt5_disconnect")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_disconnect_marks_not_connected(
        self, mock_connect: MagicMock, mock_disconnect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        await gateway.disconnect()
        assert gateway.is_connected is False
        mock_disconnect.assert_called_once()

    async def test_get_account_info_raises_when_not_connected(self, gateway: MT5Gateway) -> None:
        with pytest.raises(BrokerConnectionError):
            await gateway.get_account_info()


class TestGetAccountInfo:
    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_maps_account_info(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        mock_mt5.account_info.return_value = MagicMock(
            login=12345, balance=1000.0, currency="USD", equity=1010.0, leverage=100.0
        )
        account = await gateway.get_account_info()
        assert account.account_id == "12345"
        assert account.balance == 1000.0

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_account_info_is_none(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        mock_mt5.account_info.return_value = None
        with pytest.raises(BrokerConnectionError):
            await gateway.get_account_info()


class TestGetCandles:
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_maps_market_data_candles(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.get_candles.return_value = [
            {
                "time": "2024-01-01T00:00:00",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
            }
        ]
        candles = await gateway.get_candles("XAUUSD", Timeframe.H1, 1)
        assert len(candles) == 1
        assert candles[0].close == 1.5

    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_no_candles_returned(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.get_candles.return_value = []
        with pytest.raises(MarketDataError):
            await gateway.get_candles("XAUUSD", Timeframe.H1, 10)


class TestGetCandlesWithEnd:
    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_uses_copy_rates_from_for_historical_range(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.TIMEFRAME_M5 = 5
        mock_mt5.copy_rates_from.return_value = [
            {
                "time": 1700000000,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1,
                "tick_volume": 5,
            }
        ]

        end = datetime(2024, 1, 1, tzinfo=timezone.utc)
        candles = await gateway.get_candles("XAUUSD", Timeframe.M5, 1, end=end)

        assert len(candles) == 1
        assert candles[0].close == 1.1
        mock_mt5.copy_rates_from.assert_called_once_with("XAUUSDm", 5, end, 1)
        gateway._market_data.get_candles.assert_not_called()

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_for_unknown_symbol(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = None
        with pytest.raises(MarketDataError):
            await gateway.get_candles(
                "NOPE", Timeframe.M5, 1, end=datetime(2024, 1, 1, tzinfo=timezone.utc)
            )

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_range_query_returns_nothing(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.copy_rates_from.return_value = None
        with pytest.raises(MarketDataError):
            await gateway.get_candles(
                "XAUUSD", Timeframe.M5, 1, end=datetime(2024, 1, 1, tzinfo=timezone.utc)
            )


class TestSubmitOrder:
    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_rejects_unknown_symbol(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = None
        with pytest.raises(ExecutionError):
            await gateway.submit_order(OrderRequest(symbol="NOPE", side=OrderSide.BUY, volume=0.1))

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_successful_order_fills(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_info_tick.return_value = MagicMock(ask=2000.5, bid=2000.0)
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value = MagicMock(retcode=10009, order=555, price=2000.5)

        result = await gateway.submit_order(
            OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1)
        )
        assert result.status is OrderStatus.FILLED
        assert result.order_id == "555"

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_rejected_order_returns_rejected_status(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_select.return_value = True
        mock_mt5.symbol_info.return_value = MagicMock(digits=2, point=0.01, trade_stops_level=10)
        mock_mt5.symbol_info_tick.return_value = MagicMock(ask=2000.5, bid=2000.0)
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value = MagicMock(retcode=10004, order=None, price=None)

        result = await gateway.submit_order(
            OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1)
        )
        assert result.status is OrderStatus.REJECTED

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_symbol_select_fails(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_select.return_value = False

        with pytest.raises(MarketDataError, match="Unable to select MT5 symbol"):
            await gateway.submit_order(OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1))

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_symbol_info_is_none(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_select.return_value = True
        mock_mt5.symbol_info.return_value = None

        with pytest.raises(MarketDataError, match="Unable to retrieve symbol info"):
            await gateway.submit_order(OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1))

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_raises_when_tick_is_none(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_select.return_value = True
        mock_mt5.symbol_info.return_value = MagicMock(digits=2, point=0.01, trade_stops_level=10)
        mock_mt5.symbol_info_tick.return_value = None

        with pytest.raises(MarketDataError, match="No tick data available"):
            await gateway.submit_order(OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1))

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_adjusts_sl_tp_when_below_minimum_distance(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = "XAUUSDm"
        mock_mt5.symbol_select.return_value = True
        # stops level = 50 points * 0.1 = 5.0 min distance
        mock_mt5.symbol_info.return_value = MagicMock(digits=2, point=0.1, trade_stops_level=50)
        mock_mt5.symbol_info_tick.return_value = MagicMock(ask=2000.0, bid=1999.0)
        mock_mt5.TRADE_RETCODE_DONE = 10009
        mock_mt5.order_send.return_value = MagicMock(retcode=10009, order=777, price=2000.0)

        # SL was 1998.0 (diff 2.0 < 5.0 min distance) -> adjusted to 2000.0 - 5.0 = 1995.0
        # TP was 2002.0 (diff 2.0 < 5.0 min distance) -> adjusted to 2000.0 + 5.0 = 2005.0
        result = await gateway.submit_order(
            OrderRequest(
                symbol="XAUUSD",
                side=OrderSide.BUY,
                volume=0.1,
                stop_loss=1998.0,
                take_profit=2002.0,
            )
        )
        assert result.status is OrderStatus.FILLED
        sent_request = mock_mt5.order_send.call_args[0][0]
        assert sent_request["sl"] == 1995.0
        assert sent_request["tp"] == 2005.0


class TestGetPositions:
    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_returns_empty_list_when_no_positions(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        mock_mt5.positions_get.return_value = ()
        positions = await gateway.get_positions()
        assert positions == []

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_maps_open_positions(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        mock_pos = MagicMock(
            ticket=123456,
            symbol="XAUUSD",
            type=mock_mt5.ORDER_TYPE_BUY,
            volume=0.2,
            price_open=2000.0,
            price_current=2010.0,
            profit=200.0,
            sl=1990.0,
            tp=2030.0,
            time=1700000000,
        )
        mock_mt5.positions_get.return_value = [mock_pos]
        positions = await gateway.get_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.position_id == "123456"
        assert pos.symbol == "XAUUSD"
        assert pos.side is OrderSide.BUY
        assert pos.volume == 0.2
        assert pos.open_price == 2000.0
        assert pos.current_price == 2010.0
        assert pos.profit == 200.0
        assert pos.stop_loss == 1990.0
        assert pos.take_profit == 2030.0


class TestStreamTicks:
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_stream_ticks_rejects_unknown_symbol(
        self, mock_connect: MagicMock, gateway: MT5Gateway
    ) -> None:
        await gateway.connect()
        gateway._market_data = MagicMock()
        gateway._market_data.resolve_symbol.return_value = None

        gen = gateway.stream_ticks("UNKNOWN")
        with pytest.raises(MarketDataError, match="Unknown MT5 symbol"):
            await gen.__anext__()


# ---------------------------------------------------------------------------
# Helper factories for mock MT5 deal objects
# ---------------------------------------------------------------------------

def _make_deal(
    *,
    ticket: int,
    position_id: int,
    symbol: str = "XAUUSD",
    deal_type: object = None,  # e.g. mock_mt5.DEAL_TYPE_BUY
    entry: object = None,      # e.g. mock_mt5.DEAL_ENTRY_OUT
    price: float = 2000.0,
    profit: float = 0.0,
    volume: float = 0.1,
    time: int = 1_700_000_000,
) -> MagicMock:
    """Return a MagicMock deal object that behaves like an MT5 deal namedtuple."""
    deal = MagicMock()
    deal.ticket = ticket
    deal.position_id = position_id
    deal.symbol = symbol
    deal.type = deal_type
    deal.entry = entry
    deal.price = price
    deal.profit = profit
    deal.volume = volume
    deal.time = time
    return deal


@pytest.fixture
def _today_epoch() -> int:
    """A Unix timestamp that is definitely today (UTC)."""
    import time
    return int(time.time())


class TestGetTradeHistory:
    """Tests for MT5Gateway.get_trade_history with correct deal filtering."""

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_deal_entry_in_is_excluded(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 1: Opening deals (DEAL_ENTRY_IN) must not appear in results."""
        await gateway.connect()

        opening_deal = _make_deal(
            ticket=101,
            position_id=1,
            deal_type=mock_mt5.DEAL_TYPE_BUY,
            entry=mock_mt5.DEAL_ENTRY_IN,
            profit=0.0,
        )
        mock_mt5.history_deals_get.return_value = [opening_deal]

        result = await gateway.get_trade_history()

        assert result == [], (
            "DEAL_ENTRY_IN (opening deals) must be excluded from trade history"
        )

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_deal_entry_out_is_included(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 2: Closing deals (DEAL_ENTRY_OUT) must be returned."""
        await gateway.connect()

        closing_deal = _make_deal(
            ticket=202,
            position_id=2,
            deal_type=mock_mt5.DEAL_TYPE_BUY,
            entry=mock_mt5.DEAL_ENTRY_OUT,
            profit=-50.0,
        )
        mock_mt5.history_deals_get.return_value = [closing_deal]

        result = await gateway.get_trade_history()

        assert len(result) == 1
        assert result[0].trade_id == "202"
        assert result[0].profit == -50.0

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_commission_deal_is_excluded(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 3: Commission accounting deals must be excluded."""
        await gateway.connect()

        # Commission deals use DEAL_TYPE_COMMISSION and often DEAL_ENTRY_IN
        # but the type-based filter should exclude them regardless of entry.
        commission_deal = _make_deal(
            ticket=303,
            position_id=3,
            deal_type=mock_mt5.DEAL_TYPE_COMMISSION,
            entry=mock_mt5.DEAL_ENTRY_IN,
            profit=-7.0,
        )
        mock_mt5.history_deals_get.return_value = [commission_deal]

        result = await gateway.get_trade_history()

        assert result == [], (
            "DEAL_TYPE_COMMISSION must be excluded — it is not a trade execution"
        )

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_interest_swap_deal_is_excluded(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 4: Swap/overnight-interest deals must be excluded."""
        await gateway.connect()

        interest_deal = _make_deal(
            ticket=404,
            position_id=4,
            deal_type=mock_mt5.DEAL_TYPE_INTEREST,
            entry=mock_mt5.DEAL_ENTRY_IN,
            profit=-3.5,
        )
        mock_mt5.history_deals_get.return_value = [interest_deal]

        result = await gateway.get_trade_history()

        assert result == [], (
            "DEAL_TYPE_INTEREST must be excluded — it is not a trade execution"
        )

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_trade_id_uses_deal_ticket_not_position_id(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 5: trade_id must be str(deal.ticket), not str(deal.position_id)."""
        await gateway.connect()

        closing_deal = _make_deal(
            ticket=9999,
            position_id=1111,
            deal_type=mock_mt5.DEAL_TYPE_BUY,
            entry=mock_mt5.DEAL_ENTRY_OUT,
            profit=100.0,
        )
        mock_mt5.history_deals_get.return_value = [closing_deal]

        result = await gateway.get_trade_history()

        assert len(result) == 1
        assert result[0].trade_id == "9999", (
            "trade_id must be deal.ticket, not deal.position_id (1111)"
        )

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_partial_close_produces_multiple_entries(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 6 + 7: Three partial closes produce 3 entries with unique IDs
        and correct P/L per execution."""
        await gateway.connect()

        # One position closed in three partial executions.
        # All share position_id=5 but each has its own unique ticket.
        deals = [
            _make_deal(
                ticket=501,
                position_id=5,
                deal_type=mock_mt5.DEAL_TYPE_BUY,
                entry=mock_mt5.DEAL_ENTRY_OUT,
                profit=-10.0,
                volume=0.03,
            ),
            _make_deal(
                ticket=502,
                position_id=5,
                deal_type=mock_mt5.DEAL_TYPE_BUY,
                entry=mock_mt5.DEAL_ENTRY_OUT,
                profit=-20.0,
                volume=0.04,
            ),
            _make_deal(
                ticket=503,
                position_id=5,
                deal_type=mock_mt5.DEAL_TYPE_BUY,
                entry=mock_mt5.DEAL_ENTRY_OUT,
                profit=-30.0,
                volume=0.03,
            ),
        ]
        mock_mt5.history_deals_get.return_value = deals

        result = await gateway.get_trade_history()

        assert len(result) == 3, "Each partial close is one closing execution"
        trade_ids = {e.trade_id for e in result}
        assert trade_ids == {"501", "502", "503"}, "Each deal.ticket must be unique"
        profits = sorted(e.profit for e in result)
        assert profits == [-30.0, -20.0, -10.0], "Realized P/L per execution must be correct"

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_round_trip_one_open_one_close_produces_one_entry(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """Test 13 (reconciliation): One opening deal + one closing deal for
        the same position must produce exactly ONE entry in get_trade_history().
        This is the core double-count regression test."""
        await gateway.connect()

        opening = _make_deal(
            ticket=601,
            position_id=6,
            deal_type=mock_mt5.DEAL_TYPE_BUY,
            entry=mock_mt5.DEAL_ENTRY_IN,
            profit=0.0,
        )
        closing = _make_deal(
            ticket=602,
            position_id=6,
            deal_type=mock_mt5.DEAL_TYPE_BUY,
            entry=mock_mt5.DEAL_ENTRY_OUT,
            profit=-75.0,
        )
        mock_mt5.history_deals_get.return_value = [opening, closing]

        result = await gateway.get_trade_history()

        assert len(result) == 1, (
            "A complete round-trip (DEAL_ENTRY_IN + DEAL_ENTRY_OUT) must produce "
            "exactly one TradeHistoryEntry — the closing deal"
        )
        assert result[0].trade_id == "602"
        assert result[0].profit == -75.0

    @patch("broker.mt5_gateway.mt5")
    @patch("broker.mt5_gateway.mt5_connect", return_value=True)
    async def test_mixed_deals_only_closing_trades_returned(
        self, mock_connect: MagicMock, mock_mt5: MagicMock, gateway: MT5Gateway
    ) -> None:
        """All deal types together: only DEAL_ENTRY_OUT trade deals survive."""
        await gateway.connect()

        deals = [
            # Opening — excluded
            _make_deal(ticket=10, position_id=1, deal_type=mock_mt5.DEAL_TYPE_BUY,
                       entry=mock_mt5.DEAL_ENTRY_IN, profit=0.0),
            # Commission — excluded
            _make_deal(ticket=11, position_id=1, deal_type=mock_mt5.DEAL_TYPE_COMMISSION,
                       entry=mock_mt5.DEAL_ENTRY_IN, profit=-5.0),
            # Interest/swap — excluded
            _make_deal(ticket=12, position_id=1, deal_type=mock_mt5.DEAL_TYPE_INTEREST,
                       entry=mock_mt5.DEAL_ENTRY_IN, profit=-2.0),
            # Closing trade — INCLUDED
            _make_deal(ticket=13, position_id=1, deal_type=mock_mt5.DEAL_TYPE_BUY,
                       entry=mock_mt5.DEAL_ENTRY_OUT, profit=-40.0),
        ]
        mock_mt5.history_deals_get.return_value = deals

        result = await gateway.get_trade_history()

        assert len(result) == 1
        assert result[0].trade_id == "13"
        assert result[0].profit == -40.0
