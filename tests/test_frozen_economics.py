"""Offline financial accounting, causal spread and frozen broker-probe checks."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pandas as pd
import pytest

from backtesting.backtest import run_backtest
from backtesting.economics import FrozenCFDContract, FrozenCostPolicy, FrozenMarketModel, contract_from_evidence
from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExitReason
from broker.types import Candle, ExecutionQuantityUnit
from data.dataset import candle_content_hash


def contract():
    return FrozenCFDContract("FX Vol 20","USD",.01,.01,.01,1,.01,.01,1,0,.001,0,0,5,10800)


def frame():
    now = datetime(2026,10,8,12,tzinfo=timezone.utc)
    return pd.DataFrame({"time":[now+timedelta(minutes=5*i) for i in range(3)],
        "open":[1000.,1000.,990.],"high":[1002.,1007.,995.],"low":[998.,993.,989.],
        "close":[1001.,1001.,994.],"ATR":[2.,2.,2.]})


def model(df, *, policy=None, terms=None):
    candles = [Candle(time=r.time,open=r.open,high=r.high,low=r.low,close=r.close,source="weltrade") for r in df.itertuples()]
    return FrozenMarketModel(terms or contract(),policy or FrozenCostPolicy(3),tuple(c.time for c in candles),
        tuple(.2 for _ in candles),candle_content_hash(candles),())


def test_all_eighty_captured_profit_and_forty_margin_probes_agree():
    evidence = Path("docs/strategy-research/2026-10-08-v2-campaign-evidence")
    acquisition = json.loads((evidence/"acquisition.json").read_text())
    terms = json.loads((evidence/"additional-cost-terms.json").read_text())
    count = margins = 0
    for row in acquisition["symbols"]:
        captured = next(t for t in terms["symbols"] if t["symbol"]==row["symbol"])
        c = contract_from_evidence(row["symbol"],row["economics"],captured,server_offset=10800)
        for p in row["economics"]["profit_probes"]:
            assert c.pnl(p["side"],p["lots"],p["entry"],p["exit"]) == pytest.approx(p["pnl"],abs=.005001)
            count += 1
        for p in captured["margin_probes"]:
            assert p["margin"] <= c.margin(p["lots"],p["price"]) <= p["margin"]+.020001
            margins += 1
    assert count == 80 and margins == 40


@pytest.mark.parametrize("direction,entry",[("BUY",1000.3),("SELL",999.9)])
def test_bid_ask_entry_stop_first_and_fee_accounting(direction,entry):
    df = frame()
    engine = BacktestEngine(1000,symbol="FX Vol 20",market_model=model(df))
    engine.queue_signal({"signal":direction,"confidence":90},0,df)
    engine.process_candle(1,df)
    trade = engine.trades[0]
    assert trade.exit_reason is BacktestExitReason.STOP_LOSS
    assert trade.entry_price == pytest.approx(entry)
    assert trade.quantity.unit is ExecutionQuantityUnit.MT5_LOTS
    assert trade.quantity.value == 1
    assert trade.commission_costs == 6
    assert trade.net_pnl == pytest.approx(trade.gross_pnl-trade.costs)
    assert trade.net_pnl == pytest.approx(-9.1)
    assert engine.balance == pytest.approx(990.9)
    assert trade.initial_risk_account_currency == 3


def test_adverse_gap_stop_executes_at_open_and_preserves_loss():
    df = frame()
    df.loc[1,["high","low","close"]] = [1002.,999.,1001.]
    engine = BacktestEngine(1000,symbol="FX Vol 20",market_model=model(df))
    engine.queue_signal({"signal":"BUY","confidence":90},0,df)
    engine.process_candle(1,df)
    assert not engine.trades
    assert engine.equity_observations[-1].equity < engine.balance  # liquidation fees matter before closing
    engine.process_candle(2,df)
    assert engine.trades[0].exit_price == 989.9
    assert engine.trades[0].net_pnl < -engine.trades[0].initial_risk_account_currency


def test_minimum_lot_is_rejected_without_rounding_up_risk():
    df = frame()
    engine = BacktestEngine(1,symbol="FX Vol 20",market_model=model(df))
    engine.queue_signal({"signal":"BUY","confidence":90},0,df)
    engine.process_candle(1,df)
    assert not engine.trades
    assert engine.balance == 1
    assert engine.decisions[-1].state == "EXECUTION_REJECTED"
    assert "Minimum lot" in engine.decisions[-1].reasons[0]


def test_lot_step_floor_and_cash_risk_include_fees():
    m = model(frame(),terms=replace(contract(),volume_max=100))
    q = m.quantity(1000,1,1000,997,.1,"BUY")
    assert q.value == 1.09
    assert 3*q.value + .1*q.value + 2*round(3*q.value,2) <= 10
    with pytest.raises(ValueError):
        model(frame(),terms=replace(contract(),volume_step=0))


def test_swap_annual_interest_triple_day_and_weekend_rules():
    c = replace(contract(),swap_long_percent=-36,swap_short_percent=-36)
    # Current-price annual interest: 1000 * .36 / 360 = 1 USD/lot/day.
    for day,expected in ((8,1),(9,3),(10,0)):
        before = datetime(2026,10,day,20,59,tzinfo=timezone.utc)
        after = before + timedelta(minutes=1)
        assert c.carry("BUY",1,before,after,1000) == expected
        assert c.carry("BUY",1,after,after,1000) == 0


def test_spread_uses_only_previous_bar_and_hash_binds_every_cost():
    m = model(frame())
    changed = replace(m,spread_prices=(.2,100,.2))
    assert m.spread(1) == changed.spread(1)
    assert m.spread(2) != changed.spread(2)
    assert m.identity() != changed.identity()
    assert m.identity() != replace(m,policy=FrozenCostPolicy(6)).identity()
    with pytest.raises(ValueError):
        m.spread(0)
    with pytest.raises(ValueError,match="provider/symbol"):
        m.validate_dataset([],"FX Vol 20","deriv")


def test_unsupported_cost_or_currency_conventions_fail_closed():
    with pytest.raises(ValueError):
        replace(contract(),account_currency="EUR")
    with pytest.raises(ValueError):
        FrozenCostPolicy(float("nan"))
    with pytest.raises(ValueError):
        model(frame(),policy=FrozenCostPolicy(-1))


def test_combined_rounded_stop_loss_cannot_exceed_fractional_cent_budget():
    m = model(frame(),terms=replace(contract(),volume_max=.01),policy=FrozenCostPolicy(0))
    with pytest.raises(ValueError,match="Minimum lot"):
        m.quantity(31.8,1,1000,969.6,1.4,"BUY")
    assert m.quantity(32,1,1000,969.6,1.4,"BUY").value == .01


@pytest.mark.parametrize("side",["BUY","SELL"])
def test_stop_validation_uses_opposite_quote_not_slipped_fill(side):
    df=frame()
    # Entry slip .10 plus spread .20 leaves only 2.70 quote-to-SL,
    # despite a fill-to-SL distance of 3.00.
    engine=BacktestEngine(1000,symbol="FX Vol 20",
        market_model=model(df,terms=replace(contract(),minimum_stop_price=2.75)))
    engine.queue_signal({"signal":side,"confidence":90},0,df)
    engine.process_candle(1,df)
    assert not engine.trades
    assert engine.decisions[-1].state == "EXECUTION_REJECTED"
    assert "minimum-stop" in engine.decisions[-1].reasons[0]


@pytest.mark.parametrize("side",["BUY","SELL"])
def test_liquidation_mark_equals_close_at_same_quote_with_tick_rounding(side):
    df=frame()
    df.loc[1,["high","low","close"]]=[1002.,999.,1001.007]
    engine=BacktestEngine(1000,symbol="FX Vol 20",market_model=model(df))
    engine.queue_signal({"signal":side,"confidence":90},0,df)
    engine.process_candle(1,df)
    assert not engine.trades
    mark=engine.equity_observations[-1].equity
    engine.finish(1,df)
    assert engine.balance == mark
    assert engine.trades[0].exit_price == (1000.9 if side == "BUY" else 1001.31)


async def test_canonical_runner_binds_model_without_terminal_calls(monkeypatch):
    import MetaTrader5 as mt5
    from tests.test_backtest_reproducibility import _candles
    candles = [c.model_copy(update={"source":"weltrade"}) for c in _candles()]
    m = FrozenMarketModel(contract(),FrozenCostPolicy(3),tuple(c.time for c in candles),
        tuple(.2 for _ in candles),candle_content_hash(candles),())
    monkeypatch.setattr(mt5,"initialize",lambda *a,**k: pytest.fail("No terminal inside replay"))
    first = await run_backtest(symbol="FX Vol 20",dataset=candles,provider="weltrade",market_model=m)
    second = await run_backtest(symbol="FX Vol 20",dataset=candles,provider="weltrade",market_model=replace(m,policy=FrozenCostPolicy(6)))
    assert first.result.run_fingerprint != second.result.run_fingerprint
    assert first.result.drawdown_basis == "BAR_CLOSE_LIQUIDATION_EQUITY"
    assert len(first.result.equity_observations) == 30
    assert first.result.run_context["frozen_market_model"]["policy"]["commission_per_lot_per_side"] == 3
