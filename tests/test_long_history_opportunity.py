from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backtesting.backtest import run_backtest
from backtesting.long_history_labels import LongHistoryOpportunity, REGISTRATION_HASH, SYMBOLS
from backtesting.long_history_training import REGISTRATION_HASH as PARENT_HASH
from backtesting.models import _sha256
from data.dataset import candle_content_hash
from core.exceptions import MarketDataError
from tests.test_single_opportunity import inputs


def contract(symbol='FX Vol 20'):
    kwargs=inputs()
    start=datetime(2026,7,10,tzinfo=timezone.utc)
    candles=tuple(c.model_copy(update={'time':start+timedelta(minutes=5*i)}) for i,c in enumerate(kwargs['dataset']))
    digest=candle_content_hash(candles)
    kwargs.update(symbol=symbol,dataset=candles,market_model=replace(kwargs['market_model'],
        contract=replace(kwargs['market_model'].contract,symbol=symbol),
        timestamps=tuple(c.time for c in candles),dataset_content_hash=digest,
        policy=replace(kwargs['market_model'].policy,slippage_atr_fraction_per_fill=.05)))
    identity=dict(parent_registration_sha256=PARENT_HASH,dataset_content_hash=digest,
        provider='weltrade',symbol=symbol,timeframe='M5',source_candle_index=200,
        signal_bar_open=candles[200].time.isoformat(),direction='BUY')
    target=LongHistoryOpportunity(REGISTRATION_HASH,_sha256(identity),symbol,digest,200,
        identity['signal_bar_open'],'BUY',90)
    return kwargs,target


@pytest.mark.asyncio
@pytest.mark.parametrize('symbol',SYMBOLS)
async def test_all_symbols_match_first_stateful_fill_without_reentry(symbol):
    kwargs,target=contract(symbol)
    with patch('backtesting.backtest.generate_trading_signal',return_value={'signal':'BUY','confidence':90}) as signal:
        single=await run_backtest(**kwargs,long_history_opportunity=target)
        assert signal.call_count==1
        assert len(signal.call_args.args[0])==201
        stateful=await run_backtest(**kwargs)
    assert len(single.trades)==1
    assert single.trades[0]==stateful.trades[0]
    assert single.result.run_fingerprint!=stateful.result.run_fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[{'starting_balance':100},{'end_index':219},{'end_index':250},
                                  {'provider':'unknown'}])
async def test_unregistered_assumptions_rejected(change):
    kwargs,target=contract()
    with pytest.raises((MarketDataError,ValueError)):
        await run_backtest(**{**kwargs,**change},long_history_opportunity=target)


@pytest.mark.asyncio
async def test_event_tampering_and_mixed_contracts_rejected():
    kwargs,target=contract()
    with pytest.raises(MarketDataError,match='identity differs'):
        await run_backtest(**kwargs,long_history_opportunity=replace(target,event_id='sha256:fake'))
    with pytest.raises(MarketDataError):
        await run_backtest(**kwargs,long_history_opportunity=target,single_opportunity=('BUY',90))


@pytest.mark.asyncio
async def test_gap_after_possible_early_exit_still_rejects():
    kwargs,target=contract()
    candles=tuple(c.model_copy(update={'time':c.time+timedelta(minutes=5)}) if i>=210 else c
                  for i,c in enumerate(kwargs['dataset']))
    digest=candle_content_hash(candles)
    kwargs.update(dataset=candles,market_model=replace(kwargs['market_model'],
        timestamps=tuple(c.time for c in candles),dataset_content_hash=digest))
    identity=dict(parent_registration_sha256=PARENT_HASH,dataset_content_hash=digest,
        provider='weltrade',symbol=target.symbol,timeframe='M5',source_candle_index=200,
        signal_bar_open=target.signal_bar_open,direction='BUY')
    with pytest.raises(MarketDataError,match='crosses a gap'):
        await run_backtest(**kwargs,long_history_opportunity=replace(target,
            event_id=_sha256(identity),dataset_content_hash=digest))


@pytest.mark.asyncio
async def test_signal_mismatch_never_queues():
    kwargs,target=contract()
    with patch('backtesting.backtest.generate_trading_signal',return_value={'signal':'SELL','confidence':90}), \
         patch('backtesting.backtest.BacktestEngine.queue_signal') as queue:
        with pytest.raises(MarketDataError,match='differs from original'):
            await run_backtest(**kwargs,long_history_opportunity=target)
        queue.assert_not_called()
