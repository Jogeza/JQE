from datetime import datetime,timedelta,timezone
from unittest.mock import MagicMock,patch

import pytest

from broker.weltrade_gateway import WeltradeGateway
from broker.types import Timeframe
from core.exceptions import MarketDataError


@pytest.mark.asyncio
async def test_server_bounds_invert_normalization_and_preserve_inclusive_utc_edges():
    start=datetime(2026,7,10,tzinfo=timezone.utc);end=start+timedelta(minutes=5)
    sdk=MagicMock();sdk.TIMEFRAME_M5=5
    sdk.copy_rates_range.return_value=[dict(time=int((t+timedelta(hours=3)).timestamp()),
        open=100,high=101,low=99,close=100,tick_volume=1) for t in (start,end)]
    gateway=WeltradeGateway()
    with patch.object(gateway,'_require_connected'),patch.object(gateway,'_resolve_symbol',return_value='SFX Vol 99'), \
        patch('broker.weltrade_gateway.mt5',sdk),patch('broker.mt5_gateway.mt5',sdk):
        candles=await gateway.get_candles_range('SFX Vol 99',Timeframe.M5,start,end)
    assert [c.time for c in candles]==[start,end]
    sdk.copy_rates_range.assert_called_once_with('SFX Vol 99',5,start+timedelta(hours=3),end+timedelta(hours=3))
    sdk.symbol_select.assert_not_called();sdk.order_send.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['naive','reversed','out_of_range','duplicate'])
async def test_invalid_range_or_response_fails_closed(case):
    start=datetime(2026,7,10,tzinfo=timezone.utc);end=start+timedelta(minutes=5)
    sdk=MagicMock();sdk.TIMEFRAME_M5=5
    row=dict(time=int((start+timedelta(hours=3)).timestamp()),open=100,high=101,low=99,close=100,tick_volume=1)
    sdk.copy_rates_range.return_value=[row]
    if case=='naive':start=start.replace(tzinfo=None)
    elif case=='reversed':start,end=end,start
    elif case=='out_of_range':row['time']-=300
    else:sdk.copy_rates_range.return_value=[row,row]
    gateway=WeltradeGateway()
    with patch.object(gateway,'_require_connected'),patch.object(gateway,'_resolve_symbol',return_value='SFX Vol 99'), \
        patch('broker.weltrade_gateway.mt5',sdk),patch('broker.mt5_gateway.mt5',sdk),pytest.raises(MarketDataError):
        await gateway.get_candles_range('SFX Vol 99',Timeframe.M5,start,end)
    if case in ('naive','reversed'):sdk.copy_rates_range.assert_not_called()
