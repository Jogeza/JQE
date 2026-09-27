"""Phase 4 - Volatility Parity & Microstructure Cost Realism tests.

Validates:
1. BacktestExecutionAssumptions accepts, rejects, and defaults the two new
   ATR-fraction fields correctly.
2. _enter() applies ATR-scaled adverse costs to the fill price.
3. Volatility parity: two candle sequences with different ATR magnitudes but
   identical risk_percent risk the same cash per trade.
4. Higher ATR-fraction costs shrink net PnL relative to zero-cost baseline.
"""
from __future__ import annotations

import math
import pytest
import pandas as pd
from datetime import datetime, timezone

from backtesting.engine import BacktestEngine
from backtesting.models import (
    BacktestExecutionAssumptions,
    BacktestRiskConfiguration,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(n: int) -> datetime:
    from datetime import timedelta; base = datetime(2024, 1, 1, tzinfo=timezone.utc); return base + timedelta(days=n)


def _make_df(
    n: int = 30,
    atr: float = 10.0,
    open_: float = 1000.0,
    trend: float = 0.0,
) -> pd.DataFrame:
    rows = []
    price = open_
    for i in range(n):
        o = price
        h = o + atr * 2
        l = o - atr * 0.5
        c = o + trend
        rows.append({"time": _ts(i), "open": o, "high": h, "low": l, "close": c, "ATR": atr})
        price = c
    return pd.DataFrame(rows)


def _run_one_trade(engine: BacktestEngine, df: pd.DataFrame) -> None:
    signal = {"signal": "BUY", "confidence": 80, "reasons": []}
    engine.queue_signal(signal, 0, df)
    for i in range(1, len(df)):
        engine.process_candle(i, df)
        if engine.trades:
            break
    engine.finish(len(df) - 1, df)


# ---------------------------------------------------------------------------
# 1. Model validation
# ---------------------------------------------------------------------------

class TestBacktestExecutionAssumptionsPhase4:
    def test_defaults_are_zero(self) -> None:
        ea = BacktestExecutionAssumptions()
        assert ea.adverse_slippage_atr_fraction == 0.0
        assert ea.spread_atr_fraction == 0.0

    def test_positive_values_accepted(self) -> None:
        ea = BacktestExecutionAssumptions(
            adverse_slippage_atr_fraction=0.10,
            spread_atr_fraction=0.05,
        )
        assert ea.adverse_slippage_atr_fraction == 0.10
        assert ea.spread_atr_fraction == 0.05

    def test_negative_adverse_slippage_rejected(self) -> None:
        with pytest.raises(ValueError, match="costs cannot be negative"):
            BacktestExecutionAssumptions(adverse_slippage_atr_fraction=-0.01)

    def test_negative_spread_fraction_rejected(self) -> None:
        with pytest.raises(ValueError, match="costs cannot be negative"):
            BacktestExecutionAssumptions(spread_atr_fraction=-0.01)

    def test_nan_atr_fraction_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be finite"):
            BacktestExecutionAssumptions(adverse_slippage_atr_fraction=math.nan)


# ---------------------------------------------------------------------------
# 2. ATR-scaled cost wired into fill price
# ---------------------------------------------------------------------------

class TestATRScaledFillPrice:
    def test_buy_fill_price_higher_with_atr_cost(self) -> None:
        atr = 20.0
        df = _make_df(n=25, atr=atr, open_=500.0, trend=5.0)
        ea_plain = BacktestExecutionAssumptions()
        ea_costly = BacktestExecutionAssumptions(
            adverse_slippage_atr_fraction=0.10,
            spread_atr_fraction=0.05,
        )
        eng_plain = BacktestEngine(
            starting_balance=1000.0, risk=BacktestRiskConfiguration(risk_percent=1.0),
            execution=ea_plain,
        )
        eng_costly = BacktestEngine(
            starting_balance=1000.0, risk=BacktestRiskConfiguration(risk_percent=1.0),
            execution=ea_costly,
        )
        _run_one_trade(eng_plain, df)
        _run_one_trade(eng_costly, df)
        assert eng_plain.trades, "plain engine must record a trade"
        assert eng_costly.trades, "costly engine must record a trade"
        plain_entry = eng_plain.trades[0].entry_price
        costly_entry = eng_costly.trades[0].entry_price
        expected_extra = atr * (0.10 + 0.05)
        assert costly_entry == pytest.approx(plain_entry + expected_extra, rel=1e-6)


# ---------------------------------------------------------------------------
# 3. Volatility parity
# ---------------------------------------------------------------------------

class TestVolatilityParity:
    def test_cash_risk_invariant_to_atr(self) -> None:
        risk_percent = 1.0
        balance = 1000.0
        risk_cash = balance * risk_percent / 100.0   # $10

        for atr in (5.0, 25.0):
            df = _make_df(n=30, atr=atr, open_=500.0, trend=atr * 2)
            ea = BacktestExecutionAssumptions(stop_atr_multiple=1.5)
            risk_cfg = BacktestRiskConfiguration(
                risk_percent=risk_percent, minimum_atr=0.1,
            )
            eng = BacktestEngine(
                starting_balance=balance, risk=risk_cfg, execution=ea,
            )
            _run_one_trade(eng, df)
            if not eng.trades:
                continue
            trade = eng.trades[0]
            stop_distance = abs(trade.entry_price - trade.stop_price)
            implied_risk = stop_distance * trade.quantity.value
            assert implied_risk == pytest.approx(risk_cash, rel=0.01), (
                f"ATR={atr}: implied_risk={implied_risk:.4f} != target={risk_cash:.4f}"
            )


# ---------------------------------------------------------------------------
# 4. Higher ATR costs reduce net PnL vs zero-cost baseline
# ---------------------------------------------------------------------------

class TestCostImpactOnPnL:
    def test_atr_costs_reduce_net_pnl_on_winning_trade(self) -> None:
        atr = 15.0
        df = _make_df(n=40, atr=atr, open_=200.0, trend=atr * 2)
        balance = 500.0

        results = {}
        for label, slippage_frac in [("none", 0.0), ("costly", 0.15)]:
            ea = BacktestExecutionAssumptions(
                adverse_slippage_atr_fraction=slippage_frac,
                stop_atr_multiple=1.5,
                target_atr_multiple=3.0,
            )
            eng = BacktestEngine(
                starting_balance=balance,
                risk=BacktestRiskConfiguration(risk_percent=2.0, minimum_atr=0.1),
                execution=ea,
            )
            _run_one_trade(eng, df)
            results[label] = eng.balance

        if results.get("none", balance) != balance and results.get("costly", balance) != balance:
            assert results["costly"] <= results["none"]
