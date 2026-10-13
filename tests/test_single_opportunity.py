from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backtesting.backtest import run_backtest
from backtesting.economics import FrozenCFDContract, FrozenCostPolicy, FrozenMarketModel
from broker.types import Candle, Timeframe
from core.exceptions import MarketDataError
from data.dataset import candle_content_hash


def inputs():
    start = datetime(2026, 9, 8, tzinfo=timezone.utc)
    candles = tuple(Candle(time=start+timedelta(minutes=5*i), open=1000., high=1050. if i==201 else 1010.,
                          low=950. if i==201 else 990., close=1000., source="weltrade") for i in range(225))
    contract = FrozenCFDContract("SFX Vol 99", "USD", .01, .01, .01, 1, .01, .01, 1, 0, .001, 0, 0, 5, 10800)
    model = FrozenMarketModel(contract,FrozenCostPolicy(0),tuple(c.time for c in candles),
                              tuple(.2 for c in candles),candle_content_hash(candles),())
    return dict(symbol="SFX Vol 99",timeframe=Timeframe.M5,provider="weltrade",dataset=candles,
                market_model=model,start_index=200,end_index=220)


@pytest.mark.asyncio
async def test_first_fill_matches_stateful_runner_and_no_reentry_after_exit():
    kwargs = inputs()
    signal = {"signal":"BUY","confidence":90,"reasons":[]}
    with patch("backtesting.backtest.generate_trading_signal",return_value=signal) as canonical:
        single = await run_backtest(**kwargs,single_opportunity=("BUY",90))
        assert canonical.call_count == 1
        assert len(canonical.call_args.args[0]) == 201  # Full original prefix.
        stateful = await run_backtest(**kwargs)
    assert len(single.trades) == 1
    assert len(stateful.trades) > 1
    assert single.trades[0] == stateful.trades[0]
    assert single.result.run_fingerprint != stateful.result.run_fingerprint


@pytest.mark.asyncio
async def test_target_mismatch_fails_before_queue():
    with patch("backtesting.backtest.generate_trading_signal",return_value={"signal":"SELL","confidence":90}), \
         patch("backtesting.backtest.BacktestEngine.queue_signal") as queue:
        with pytest.raises(MarketDataError,match="differs from original"):
            await run_backtest(**inputs(),single_opportunity=("BUY",90))
        queue.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("change",[{"end_index":219},{"end_index":250},{"starting_balance":100.}])
async def test_incomplete_horizon_and_unregistered_capital_rejected(change):
    kwargs = {**inputs(),**change}
    with pytest.raises(MarketDataError,match="complete frozen label contract"):
        await run_backtest(**kwargs,single_opportunity=("BUY",90))


@pytest.mark.asyncio
async def test_native_minimum_stop_rejection_has_no_trade_or_reentry():
    from dataclasses import replace
    kwargs=inputs()
    kwargs["market_model"]=replace(kwargs["market_model"],contract=replace(kwargs["market_model"].contract,minimum_stop_price=1000.))
    with patch("backtesting.backtest.generate_trading_signal",return_value={"signal":"BUY","confidence":90}) as canonical:
        engine=await run_backtest(**kwargs,single_opportunity=("BUY",90))
    assert canonical.call_count == 1
    assert not engine.trades
    assert any(d.state == "EXECUTION_REJECTED" for d in engine.decisions)
    assert any("minimum-stop" in reason for d in engine.decisions for reason in d.reasons)
