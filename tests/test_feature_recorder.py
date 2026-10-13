from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backtesting.backtest import run_backtest
from backtesting.feature_recorder import verify_spreads, verify_signal
from broker.types import Candle, Timeframe
from core.exceptions import MarketDataError


@pytest.mark.asyncio
async def test_feature_only_canonical_observer_never_executes_or_returns_performance():
    now=datetime(2026,9,8,tzinfo=timezone.utc)
    candles=[Candle(time=now+timedelta(minutes=5*i),open=100,high=101,low=99,close=100,source='weltrade') for i in range(203)]
    observations=[]
    signal={'signal':'BUY','confidence':90,'reasons':[]}
    with patch('backtesting.backtest.generate_trading_signal',return_value=signal) as pipeline, \
         patch('backtesting.engine.BacktestEngine.process_candle',side_effect=AssertionError('economic replay')), \
         patch('backtesting.engine.BacktestEngine.queue_signal',side_effect=AssertionError('queued order')):
        engine=await run_backtest(symbol='SFX Vol 99',timeframe=Timeframe.M5,provider='weltrade',dataset=candles,
            features_only=True,feature_observer=lambda i,h,s:observations.append((i,len(h),s)))
    assert pipeline.call_count==3
    assert observations[0]==(200,201,signal)
    assert engine.result is None and not engine.trades


@pytest.mark.asyncio
async def test_missing_feature_observer_fails_closed():
    with pytest.raises(MarketDataError,match='observer'):await run_backtest(features_only=True)


def spread_fixture():
    time=datetime(2026,9,8,tzinfo=timezone.utc)
    candles=[SimpleNamespace(time=time)]
    manifest=SimpleNamespace(content_hash='sha256:data')
    acquisition={'spread_sidecar_sha256':'side','content_hash':'sha256:data',
        'status':'ACQUIRED_NOT_PROMOTION_QUALIFIED','economics':{'point':.01}}
    side={'provider':'weltrade','content_hash':'sha256:data','point':.01,
        'rows':[{'time':time.isoformat(),'spread_points':20}]}
    return side,candles,manifest,acquisition


def test_spread_provenance_matches_original_acquisition():
    side,candles,manifest,acq=spread_fixture()
    assert verify_spreads(side,candles,manifest,acq,'sha256:side')[candles[0].time]==.2


def test_stateful_reasons_do_not_replace_canonical_identity():
    signal={'signal':'BUY','confidence':75,'reasons':['Trend alignment']}
    saved={'confidence':75,'reasons':['Trend alignment','Position already open']}
    verify_signal(signal,{'direction':'BUY'},saved)
    with pytest.raises(ValueError):verify_signal(signal,{'direction':'SELL'},saved)
    with pytest.raises(ValueError):verify_signal(signal,{'direction':'BUY'},{'confidence':75,'reasons':['Other signal','Position already open']})


@pytest.mark.parametrize('mutation',['provider','hash','time','negative','point'])
def test_spread_mismatches_fail_closed(mutation):
    side,candles,manifest,acq=spread_fixture()
    if mutation=='provider':side['provider']='deriv'
    elif mutation=='hash':side['content_hash']='other'
    elif mutation=='time':side['rows'][0]['time']=(candles[0].time+timedelta(minutes=5)).isoformat()
    elif mutation=='negative':side['rows'][0]['spread_points']=-1
    else:side['point']=.1
    with pytest.raises(ValueError):verify_spreads(side,candles,manifest,acq,'sha256:side')
