from dataclasses import replace
from datetime import datetime, timezone, timedelta
from enum import Enum
import json
from unittest.mock import patch
import pytest
from backtesting.backtest import run_backtest
from backtesting.models import _canonical_json
from tests.test_long_history_opportunity import contract


def legacy_bytes(result):
    payload=result._normalized_payload()
    payload['result_hash']=result.result_hash
    return (_canonical_json(payload)+'\n').encode('utf-8')


@pytest.fixture
async def result():
    kwargs,target=contract()
    with patch('backtesting.backtest.generate_trading_signal',return_value={'signal':'BUY','confidence':90}):
        engine=await run_backtest(**kwargs,long_history_opportunity=target)
    return engine.result


class Score(str,Enum):
    VALUE='unicode £ 日本語'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['executed','null','nested','offset','mutation','nan','infinity','naive'])
async def test_exact_legacy_bytes_hashes_and_rejection_semantics(result,mode):
    if mode=='null': result=replace(result,trades=())
    if mode=='nested': result=replace(result,run_context={'nested':{2:Score.VALUE,'a':(-0.0,None,True)}})
    if mode=='offset': result=replace(result,dataset_start=datetime(2026,7,10,tzinfo=timezone(timedelta(hours=3))))
    if mode=='nan': result=replace(result,run_context={'bad':float('nan')})
    if mode=='infinity': result=replace(result,run_context={'bad':float('inf')})
    if mode=='naive': result=replace(result,dataset_start=datetime(2026,7,10))
    if mode in ('nan','infinity','naive'):
        with pytest.raises(ValueError): legacy_bytes(result)
        with pytest.raises(ValueError): result.to_json_bytes()
        return
    assert result.to_json_bytes()==legacy_bytes(result)
    assert result.to_dict()['result_hash']==result.result_hash
    if mode=='mutation':
        before=result.to_json_bytes()
        result.run_context['new']='changed'
        assert result.to_json_bytes()!=before
        assert result.to_json_bytes()==legacy_bytes(result)
