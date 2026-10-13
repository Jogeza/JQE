from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest

from broker.types import Candle,Timeframe
from core.exceptions import MarketDataError
from data.coverage import FrozenWeltradeSundayResearchPolicy,validate_historical_coverage
from data.historical import HistoricalDataService
from data.storage import CandleStore

START=datetime(2026,7,12,3,45,tzinfo=timezone.utc)
END=START+timedelta(minutes=15)


def candles(times=(START,END)):
    return [Candle(time=t,open=100,high=101,low=99,close=100,source='weltrade') for t in times]


def kwargs():
    return dict(provider='weltrade',canonical_symbol='SFX Vol 99',provider_symbol='SFX Vol 99',
        timeframe=Timeframe.M5,start=START,end=END)


def test_default_stays_continuous_opt_in_research_closes_only_two_buckets():
    assert not validate_historical_coverage(candles(),**kwargs()).is_complete
    result=validate_historical_coverage(candles(),**kwargs(),research_policy=FrozenWeltradeSundayResearchPolicy())
    assert result.is_complete and result.expected_count==2 and result.legitimate_closed_count==2


def test_unexpected_gap_still_fails_completeness():
    result=validate_historical_coverage(candles((START,)),**kwargs(),research_policy=FrozenWeltradeSundayResearchPolicy())
    assert not result.is_complete and result.missing_expected_buckets==(END,)


@pytest.mark.parametrize('case',['closure_candle','duplicate','alias','timeframe','outside'])
def test_research_policy_rejects_unexpected_data_or_scope(case):
    data=candles();params=kwargs()
    if case=='closure_candle':data=candles((START,START+timedelta(minutes=5),END))
    elif case=='duplicate':data+=data[:1]
    elif case=='alias':params['provider_symbol']='R_100'
    elif case=='timeframe':params['timeframe']=Timeframe.M15
    else:params.update(start=datetime(2026,10,9,tzinfo=timezone.utc),end=datetime(2026,10,9,tzinfo=timezone.utc))
    with pytest.raises(MarketDataError):validate_historical_coverage(data,**params,research_policy=FrozenWeltradeSundayResearchPolicy())


@pytest.mark.asyncio
@pytest.mark.parametrize('missing',[False,True])
async def test_historical_service_keeps_completeness_gate(tmp_path,missing):
    class Source:
        async def get_candles_range(self,*args,**kwargs):return candles((START,)) if missing else candles()
    service=HistoricalDataService(Source(),CandleStore(db_path=tmp_path/'new.sqlite3'),
        research_coverage_policy=FrozenWeltradeSundayResearchPolicy())
    call=dict(provider='weltrade',source_symbol='SFX Vol 99')
    if missing:
        with pytest.raises(MarketDataError,match='complete'):await service.get_candles_range('SFX Vol 99',Timeframe.M5,START,END,**call)
    else:
        result=await service.get_candles_range('SFX Vol 99',Timeframe.M5,START,END,**call)
        assert [c.time for c in result]==[START,END]
