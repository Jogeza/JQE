"""End-to-end live-cycle regression test for main.py."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pandas as pd

import main
from broker.simulation_gateway import SimulationGateway
from broker.types import Candle, OrderSide, OrderStatus, Timeframe
from config import settings


def _generate_uptrend_candles(count: int) -> list[Candle]:
    """Generates a deterministic uptrend dataset guaranteed to produce a BUY signal."""
    candles = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    base_price = 100.0

    for i in range(count):
        # Monotonically increasing price to ensure EMA50 > EMA200 and RSI > 50
        price = base_price + i
        # Increase volatility at the end to ensure ATR > average ATR for higher confidence score
        vol = 2.0 if i >= count - 15 else 1.0
        candles.append(
            Candle(
                time=base_time + timedelta(hours=i),
                open=price,
                high=price + vol,
                low=price - vol,
                close=price + 0.5,
                volume=100.0,
            )
        )
    return candles


class TestMainRegression:
    @pytest.mark.asyncio
    async def test_end_to_end_buy_cycle(self) -> None:
        """
        Executes the current main.run() live-cycle pipeline end-to-end.
        Uses the existing SimulationGateway but injects deterministic market data
        to guarantee a BUY signal and verify the resulting OrderRequest invariants.
        """
        # Ensure configuration points to simulation
        settings.broker = "simulation"
        settings.default_candle_count = 250  # Enough to populate EMA200

        # Construct actual gateway
        gateway = SimulationGateway(starting_balance=10000.0, seed=42)

        # Inject deterministic candles to force a BUY signal
        deterministic_candles = _generate_uptrend_candles(settings.default_candle_count)
        gateway.get_candles = AsyncMock(return_value=deterministic_candles)

        # Spy on the gateway to verify submission
        with patch.object(gateway, "submit_order", wraps=gateway.submit_order) as spy_submit_order:
            with patch("main.get_gateway", return_value=gateway):
                # Run the actual production pipeline
                await main.run()

        # Verify simulation execution
        spy_submit_order.assert_awaited_once()
        order = spy_submit_order.call_args[0][0]

        # Verify the resulting order properties deterministically
        assert order.symbol == settings.default_symbol
        assert order.side == OrderSide.BUY

        # Expected from TradePlanBuilder(atr_sl_multiplier=2.0, target_rr=2.0)
        # ATR=4.0, Close=349.5, Risk=0.5%, Balance=10000.0
        # Stop Distance = 8.0, Target Distance = 16.0
        # Cash Risk = 50.0
        # Volume = Cash Risk / Stop Distance = 50.0 / 8.0 = 6.25
        assert order.volume == pytest.approx(6.25)

        # Lifecycle invariants
        last_close = deterministic_candles[-1].close
        assert last_close == 349.5

        expected_sl = 341.5
        expected_tp = 365.5
        assert order.stop_loss == pytest.approx(expected_sl)
        assert order.take_profit == pytest.approx(expected_tp)

        assert order.stop_loss < last_close < order.take_profit, "Lifecycle directional invariant failed"

        # Check exact R:R
        risk = last_close - order.stop_loss
        reward = order.take_profit - last_close
        assert reward / risk == pytest.approx(2.0), "Expected exact target_rr of 2.0"
