"""Tests for research.regime_diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backtesting.models import (
    BacktestDecision,
    BacktestExitReason,
    BacktestIndicatorObservation,
    BacktestResult,
    BacktestRiskConfiguration,
    BacktestTrade,
)
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, Timeframe
from research.regime_diagnostics import (
    RegimeAttributionMetrics,
    aggregate_window_diagnostics,
    audit_regimes_for_result,
    calculate_trade_drawdown,
    compute_metrics_for_trades,
    evaluate_hypothesis_1_directional_asymmetry,
    evaluate_hypothesis_2_regime_drift,
)


def _make_dummy_trade(
    trade_id: int,
    direction: str,
    net_pnl: float,
    signal_time: datetime,
    entry_time: datetime,
    exit_reason: BacktestExitReason = BacktestExitReason.STOP_LOSS,
) -> BacktestTrade:
    qty = ExecutionQuantity(value=1.0, unit=ExecutionQuantityUnit.SIMULATION_UNITS)
    return BacktestTrade(
        trade_id=trade_id,
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        direction=direction,
        signal_timestamp=signal_time,
        entry_timestamp=entry_time,
        entry_price=2000.0,
        exit_timestamp=entry_time,
        exit_price=2000.0 + net_pnl,
        stop_price=1995.0,
        target_price=2010.0,
        quantity=qty,
        gross_pnl=net_pnl,
        costs=0.0,
        net_pnl=net_pnl,
        balance_before=50.0,
        balance_after=50.0 + net_pnl,
        holding_candles=5,
        exit_reason=exit_reason,
    )


def _make_dummy_result(
    trades: list[BacktestTrade],
    indicators: list[BacktestIndicatorObservation] | None = None,
) -> BacktestResult:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return BacktestResult(
        identity_schema_version=1,
        engine_version="1.0.0",
        dataset_hash="sha256:dummy",
        run_fingerprint="sha256:dummy_fp",
        provider="deriv",
        symbol="XAUUSD",
        timeframe=Timeframe.M15,
        dataset_start=now,
        dataset_end=now,
        candle_count=100,
        initial_capital=50.0,
        strategy={},
        risk=BacktestRiskConfiguration(),
        execution=SimpleNamespace(),  # type: ignore[arg-type]
        ending_capital=50.0 + sum(t.net_pnl for t in trades),
        absolute_pnl=sum(t.net_pnl for t in trades),
        return_percent=sum(t.net_pnl for t in trades) / 50.0 * 100.0,
        total_trades=len(trades),
        winning_trades=sum(1 for t in trades if t.net_pnl > 0),
        losing_trades=sum(1 for t in trades if t.net_pnl < 0),
        break_even_trades=sum(1 for t in trades if t.net_pnl == 0),
        win_rate_percent=sum(1 for t in trades if t.net_pnl > 0) / len(trades) * 100.0 if trades else 0.0,
        gross_profit=sum(t.net_pnl for t in trades if t.net_pnl > 0),
        gross_loss=abs(sum(t.net_pnl for t in trades if t.net_pnl < 0)),
        profit_factor=None,
        profit_factor_status="NORMAL",
        average_trade_pnl=0.0,
        average_winner=None,
        average_loser=None,
        largest_winner=None,
        largest_loser=None,
        expectancy=0.0,
        maximum_drawdown=0.0,
        maximum_drawdown_percent=0.0,
        drawdown_basis="EQUITY",
        average_holding_candles=5.0,
        maximum_consecutive_wins=0,
        maximum_consecutive_losses=0,
        trades=tuple(trades),
        decisions=(),
        indicators=tuple(indicators or []),
    )


def test_calculate_trade_drawdown_empty():
    mdd, mdd_pct = calculate_trade_drawdown([])
    assert mdd == 0.0
    assert mdd_pct == 0.0


def test_calculate_trade_drawdown_sequence():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [
        _make_dummy_trade(1, "BUY", 2.0, t0, t0),   # balance: 52
        _make_dummy_trade(2, "BUY", -5.0, t0, t0),  # balance: 47 (dd: 5 / 52 = 9.615%)
        _make_dummy_trade(3, "BUY", 1.0, t0, t0),   # balance: 48
    ]
    mdd, mdd_pct = calculate_trade_drawdown(trades, starting_balance=50.0)
    assert pytest.approx(mdd, 1e-4) == 5.0
    assert pytest.approx(mdd_pct, 1e-3) == (5.0 / 52.0 * 100.0)


def test_compute_metrics_accounting_identity():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades = [
        _make_dummy_trade(1, "BUY", 3.0, t0, t0, BacktestExitReason.TAKE_PROFIT),
        _make_dummy_trade(2, "BUY", -1.0, t0, t0, BacktestExitReason.STOP_LOSS),
        _make_dummy_trade(3, "SELL", 2.0, t0, t0, BacktestExitReason.TIMEOUT),
        _make_dummy_trade(4, "SELL", -1.5, t0, t0, BacktestExitReason.STOP_LOSS),
    ]
    cost_trades = [
        _make_dummy_trade(1, "BUY", 2.5, t0, t0, BacktestExitReason.TAKE_PROFIT),
        _make_dummy_trade(2, "BUY", -1.5, t0, t0, BacktestExitReason.STOP_LOSS),
        _make_dummy_trade(3, "SELL", 1.5, t0, t0, BacktestExitReason.TIMEOUT),
        _make_dummy_trade(4, "SELL", -2.0, t0, t0, BacktestExitReason.STOP_LOSS),
    ]
    m = compute_metrics_for_trades(trades, cost_trades=cost_trades)
    assert m.trades == 4
    assert m.buy_count == 2
    assert m.sell_count == 2
    assert m.wins == 2
    assert m.losses == 2
    assert m.win_rate_percent == 50.0
    assert pytest.approx(m.gross_profit, 1e-4) == 5.0
    assert pytest.approx(m.gross_loss, 1e-4) == 2.5
    assert pytest.approx(m.net_pnl, 1e-4) == 2.5
    assert pytest.approx(m.profit_factor, 1e-4) == 2.0
    assert pytest.approx(m.expectancy, 1e-4) == (2.5 / 4.0)
    assert pytest.approx(m.conservative_cost_net_pnl, 1e-4) == 0.5
    assert pytest.approx(m.conservative_cost_impact, 1e-4) == -2.0
    assert m.cost_flips_sign is False


def test_audit_regimes_for_result_and_directional_breakdown():
    t_sig = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t_entry = datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc)
    trades = [
        _make_dummy_trade(1, "BUY", -1.0, t_sig, t_entry, BacktestExitReason.STOP_LOSS),
        _make_dummy_trade(2, "SELL", 2.0, t_sig, t_entry, BacktestExitReason.TAKE_PROFIT),
    ]
    cost_trades = [
        _make_dummy_trade(1, "BUY", -1.5, t_sig, t_entry, BacktestExitReason.STOP_LOSS),
        _make_dummy_trade(2, "SELL", 1.5, t_sig, t_entry, BacktestExitReason.TAKE_PROFIT),
    ]
    indicators = [
        BacktestIndicatorObservation(candle_index=0, timestamp=t_entry, ema50=100.0, ema200=90.0, rsi=65.0, atr=2.0, regime="TREND_UP"),
    ]
    res_zero = _make_dummy_result(trades, indicators)
    res_cost = _make_dummy_result(cost_trades, indicators)

    audit = audit_regimes_for_result(res_zero, res_cost)

    # 1. Authorizing regimes
    per_regime = audit["per_regime"]
    assert per_regime["TRENDING"]["trades"] == 2
    assert per_regime["RANGING"]["trades"] == 0
    assert per_regime["UNKNOWN"]["trades"] == 0
    assert per_regime["HIGH_VOLATILITY"]["trades"] == 0

    # 2. Directional regimes
    dir_reg = audit["directional_regimes"]
    assert dir_reg["TRENDING BUY"]["trades"] == 1
    assert dir_reg["TRENDING BUY"]["net_pnl"] == -1.0
    assert dir_reg["TRENDING SELL"]["trades"] == 1
    assert dir_reg["TRENDING SELL"]["net_pnl"] == 2.0

    # 3. Exit breakdown
    exits = audit["exit_breakdown"]
    assert exits["STOP_LOSS"]["trades"] == 1
    assert exits["STOP_LOSS"]["share_of_total_losses_percent"] == 100.0
    assert exits["TAKE_PROFIT"]["trades"] == 1


def test_cost_flips_sign_detection():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trades_zero = [_make_dummy_trade(1, "SELL", 1.0, t0, t0, BacktestExitReason.TAKE_PROFIT)]
    trades_cost = [_make_dummy_trade(1, "SELL", -0.5, t0, t0, BacktestExitReason.TAKE_PROFIT)]
    m = compute_metrics_for_trades(trades_zero, cost_trades=trades_cost)
    assert m.cost_flips_sign is True
    assert m.net_pnl == 1.0
    assert m.conservative_cost_net_pnl == -0.5


def test_hypotheses_evaluation_structure():
    t_sig = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t_entry = datetime(2026, 1, 1, 12, 15, tzinfo=timezone.utc)
    ind_trend = BacktestIndicatorObservation(candle_index=0, timestamp=t_entry, ema50=100.0, ema200=90.0, rsi=65.0, atr=2.0, regime="TREND_DOWN")
    ind_drift = BacktestIndicatorObservation(candle_index=0, timestamp=t_entry, ema50=100.0, ema200=90.0, rsi=50.0, atr=2.0, regime="NO_TRADE")

    baseline_trades = [
        _make_dummy_trade(1, "SELL", 2.0, t_sig, t_entry, BacktestExitReason.TAKE_PROFIT),
        _make_dummy_trade(2, "BUY", -2.0, t_sig, t_entry, BacktestExitReason.STOP_LOSS),
    ]
    window_data = {
        "BASELINE": {
            "IDEALIZED_ZERO_COST": _make_dummy_result(baseline_trades, [ind_trend]),
            "CONSERVATIVE_SIMULATION_COST": _make_dummy_result(baseline_trades, [ind_trend]),
        },
        "OOS_1": {
            "IDEALIZED_ZERO_COST": _make_dummy_result(baseline_trades, [ind_drift]),
            "CONSERVATIVE_SIMULATION_COST": _make_dummy_result(baseline_trades, [ind_drift]),
        },
        "OOS_2": {
            "IDEALIZED_ZERO_COST": _make_dummy_result(baseline_trades, [ind_trend]),
            "CONSERVATIVE_SIMULATION_COST": _make_dummy_result(baseline_trades, [ind_trend]),
        },
        "OOS_3": {
            "IDEALIZED_ZERO_COST": _make_dummy_result(baseline_trades, [ind_trend]),
            "CONSERVATIVE_SIMULATION_COST": _make_dummy_result(baseline_trades, [ind_trend]),
        },
    }

    h1 = evaluate_hypothesis_1_directional_asymmetry(window_data)
    assert h1["hypothesis_id"] == "H1_DIRECTIONAL_ASYMMETRY"
    assert "TRAIN" in h1["partitions"]
    assert "FULL_OOS" in h1["partitions"]

    h2 = evaluate_hypothesis_2_regime_drift(window_data)
    assert h2["hypothesis_id"] == "H2_REGIME_DRIFT_DEGRADATION"
    assert "confirmed_trades" in h2
    assert "degraded_trades" in h2
