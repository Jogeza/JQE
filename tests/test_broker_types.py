"""Tests for broker.types — the broker-agnostic DTOs and enums."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from broker.types import (
    TIMEFRAME_SECONDS,
    AccountInfo,
    Candle,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Timeframe,
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
        order = OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0.1)
        assert order.order_type is OrderType.MARKET
        assert order.stop_loss is None

    def test_zero_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=0)

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OrderRequest(symbol="XAUUSD", side=OrderSide.BUY, volume=-1)


class TestAccountInfo:
    def test_optional_fields_default_to_none(self) -> None:
        account = AccountInfo(account_id="123", balance=1000.0, currency="USD")
        assert account.equity is None
        assert account.leverage is None


class TestCandle:
    def test_volume_defaults_to_zero(self) -> None:
        candle = Candle(time=datetime.now(timezone.utc), open=1.0, high=1.5, low=0.5, close=1.2)
        assert candle.volume == 0.0


class TestOrderStatusAndSide:
    def test_order_status_values(self) -> None:
        assert {status.value for status in OrderStatus} == {"SUBMITTED", "FILLED", "REJECTED"}

    def test_order_side_values(self) -> None:
        assert {side.value for side in OrderSide} == {"BUY", "SELL"}
