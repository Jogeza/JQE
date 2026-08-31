"""Tests for broker.types — the broker-agnostic DTOs and enums."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from broker.types import (
    TIMEFRAME_SECONDS,
    AccountInfo,
    Candle,
    ExecutionQuantity,
    ExecutionQuantityUnit,
    OrderRequest,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Timeframe,
    TradeHistoryCompleteness,
    TradeHistoryEntry,
    TradeHistorySnapshot,
)


class TestTimeframeSeconds:
    def test_every_timeframe_has_a_seconds_mapping(self) -> None:
        for timeframe in Timeframe:
            assert timeframe in TIMEFRAME_SECONDS

    def test_seconds_increase_with_timeframe_size(self) -> None:
        assert TIMEFRAME_SECONDS[Timeframe.M1] < TIMEFRAME_SECONDS[Timeframe.M5]
        assert TIMEFRAME_SECONDS[Timeframe.M5] < TIMEFRAME_SECONDS[Timeframe.H1]
        assert TIMEFRAME_SECONDS[Timeframe.H1] < TIMEFRAME_SECONDS[Timeframe.D1]


class TestOrderRequest:
    def test_valid_order_constructs(self) -> None:
        order = OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, quantity=ExecutionQuantity(value=0.1, unit=ExecutionQuantityUnit.MT5_LOTS))
        assert order.order_type is OrderType.MARKET
        assert order.stop_loss is None

    def test_zero_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionQuantity(value=0, unit=ExecutionQuantityUnit.MT5_LOTS)

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ExecutionQuantity(value=-1, unit=ExecutionQuantityUnit.MT5_LOTS)

    def test_idempotency_key_defaults_to_none(self) -> None:
        order = OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, quantity=ExecutionQuantity(value=0.1, unit=ExecutionQuantityUnit.MT5_LOTS))
        assert order.idempotency_key is None

    def test_accepts_explicit_idempotency_key(self) -> None:
        order = OrderRequest(
            symbol="XAUUSD",
            side=OrderSide.BUY,
            quantity=ExecutionQuantity(value=0.1, unit=ExecutionQuantityUnit.MT5_LOTS),
            idempotency_key="intent-1",
        )
        assert order.idempotency_key == "intent-1"


class TestOrderResult:
    def test_transaction_id_defaults_to_none(self) -> None:
        result = OrderResult(
            order_id="order-1",
            status=OrderStatus.FILLED,
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
        )
        assert result.transaction_id is None

    def test_accepts_explicit_transaction_id(self) -> None:
        result = OrderResult(
            order_id="order-1",
            status=OrderStatus.FILLED,
            symbol="XAUUSD",
            side=OrderSide.BUY,
            volume=0.1,
            transaction_id="transaction-1",
        )
        assert result.transaction_id == "transaction-1"


class TestAccountInfo:
    def test_optional_fields_default_to_none(self) -> None:
        account = AccountInfo(account_id="123", balance=1000.0, currency="USD")
        assert account.equity is None
        assert account.leverage is None


class TestCandle:
    def test_volume_defaults_to_zero(self) -> None:
        candle = Candle(time=datetime.now(timezone.utc), open=1.0, high=1.5, low=0.5, close=1.2)
        assert candle.volume == 0.0


class TestBrokerTransactionIds:
    def test_position_transaction_id_defaults_to_none(self) -> None:
        position = Position(
            position_id="position-1",
            symbol="EURUSD",
            side=OrderSide.BUY,
            volume=1.0,
            open_price=1.1,
        )
        assert position.transaction_id is None

    def test_position_accepts_transaction_id(self) -> None:
        position = Position(
            position_id="position-1",
            symbol="EURUSD",
            side=OrderSide.BUY,
            volume=1.0,
            open_price=1.1,
            transaction_id="transaction-1",
        )
        assert position.transaction_id == "transaction-1"

    def test_trade_history_transaction_id_defaults_to_none(self) -> None:
        trade = TradeHistoryEntry(
            trade_id="trade-1",
            symbol="EURUSD",
            side=OrderSide.SELL,
            volume=1.0,
            open_price=1.1,
            close_price=1.0,
            profit=100.0,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
        )
        assert trade.transaction_id is None

    def test_trade_history_accepts_transaction_id(self) -> None:
        trade = TradeHistoryEntry(
            trade_id="trade-1",
            symbol="EURUSD",
            side=OrderSide.SELL,
            volume=1.0,
            open_price=1.1,
            close_price=1.0,
            profit=100.0,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
            transaction_id="transaction-1",
        )
        assert trade.transaction_id == "transaction-1"


class TestTradeHistorySnapshot:
    def test_complete_snapshot_requires_interval_coverage(self) -> None:
        start = datetime(2026, 8, 30, tzinfo=timezone.utc)
        end = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
        snapshot = TradeHistorySnapshot(
            completeness=TradeHistoryCompleteness.COMPLETE,
            coverage_start=start,
            coverage_end=end,
        )
        assert snapshot.covers(start, end) is True

    @pytest.mark.parametrize(
        "snapshot",
        [
            TradeHistorySnapshot(completeness=TradeHistoryCompleteness.TRUNCATED),
            TradeHistorySnapshot(completeness=TradeHistoryCompleteness.UNKNOWN),
            TradeHistorySnapshot(completeness=TradeHistoryCompleteness.COMPLETE),
        ],
    )
    def test_unproven_snapshot_does_not_cover_interval(
        self, snapshot: TradeHistorySnapshot
    ) -> None:
        start = datetime(2026, 8, 30, tzinfo=timezone.utc)
        end = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
        assert snapshot.covers(start, end) is False


class TestOrderStatusAndSide:
    def test_order_status_values(self) -> None:
        assert {status.value for status in OrderStatus} == {"SUBMITTED", "FILLED", "REJECTED"}

    def test_order_side_values(self) -> None:
        assert {side.value for side in OrderSide} == {"BUY", "SELL"}
