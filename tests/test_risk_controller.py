"""Tests for risk.risk_controller — institutional risk approval and position sizing."""

from __future__ import annotations

import pandas as pd
import pytest

from risk.risk_controller import approve_trade, calculate_position_size


def _market_data(atr: float = 2.0, spread: float = 5.0) -> pd.DataFrame:
    return pd.DataFrame({"close": [100.0], "ATR": [atr], "spread": [spread]})


class TestApproveTrade:
    def test_rejects_none_signal(self) -> None:
        decision = approve_trade(None, _market_data())
        assert decision["approved"] is False
        assert decision["reason"] == "Missing signal"

    def test_rejects_non_buy_sell_signal(self) -> None:
        decision = approve_trade({"signal": "NO_TRADE"}, _market_data())
        assert decision["approved"] is False
        assert decision["reason"] == "No trade signal"

    def test_rejects_low_confidence(self) -> None:
        decision = approve_trade({"signal": "BUY", "confidence": 50}, _market_data())
        assert decision["approved"] is False
        assert decision["reason"] == "Confidence too low"

    def test_rejects_invalid_market_data(self) -> None:
        decision = approve_trade({"signal": "BUY", "confidence": 90}, market_data=None)
        assert decision["approved"] is False
        assert decision["reason"] == "Invalid market data"

    def test_rejects_low_volatility(self) -> None:
        decision = approve_trade({"signal": "BUY", "confidence": 90}, _market_data(atr=0.1))
        assert decision["approved"] is False
        assert decision["reason"] == "Low volatility"

    def test_rejects_high_spread(self) -> None:
        decision = approve_trade(
            {"signal": "BUY", "confidence": 90}, _market_data(atr=2.0, spread=999)
        )
        assert decision["approved"] is False
        assert decision["reason"] == "Spread too high"

    def test_approves_valid_trade(self) -> None:
        decision = approve_trade(
            {"signal": "BUY", "confidence": 90}, _market_data(atr=2.0, spread=5.0)
        )
        assert decision["approved"] is True
        assert decision["lot_size"] > 0

    def test_uses_provided_balance_for_position_sizing(self) -> None:
        small = approve_trade({"signal": "BUY", "confidence": 90}, _market_data(), balance=100)
        large = approve_trade({"signal": "BUY", "confidence": 90}, _market_data(), balance=100_000)
        assert large["lot_size"] > small["lot_size"]

    def test_defaults_to_placeholder_balance_when_not_given(self) -> None:
        # Backward compatibility: omitting balance must not raise, and
        # should match calling with the documented default explicitly.
        implicit = approve_trade({"signal": "BUY", "confidence": 90}, _market_data())
        explicit = approve_trade({"signal": "BUY", "confidence": 90}, _market_data(), balance=50)
        assert implicit["lot_size"] == explicit["lot_size"]


class TestCalculatePositionSize:
    def test_zero_stop_loss_returns_minimum_lot(self) -> None:
        assert calculate_position_size(balance=1000, risk_percent=1, stop_loss=0) == 0.01

    def test_negative_stop_loss_returns_minimum_lot(self) -> None:
        assert calculate_position_size(balance=1000, risk_percent=1, stop_loss=-5) == 0.01

    def test_lot_size_scales_with_balance(self) -> None:
        small = calculate_position_size(balance=100, risk_percent=1, stop_loss=1.0)
        large = calculate_position_size(balance=10_000, risk_percent=1, stop_loss=1.0)
        assert large > small

    def test_never_returns_below_minimum_lot(self) -> None:
        size = calculate_position_size(balance=1, risk_percent=0.01, stop_loss=100)
        assert size >= 0.01

    @pytest.mark.parametrize("balance,risk_percent,stop_loss", [(1000, 1, 2), (5000, 0.5, 1.5)])
    def test_result_is_rounded_to_two_decimals(
        self, balance: float, risk_percent: float, stop_loss: float
    ) -> None:
        size = calculate_position_size(balance, risk_percent, stop_loss)
        assert size == round(size, 2)
