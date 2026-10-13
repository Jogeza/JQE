from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from core.indicators import calculate_indicators
from research.causal_features import closed_bar_features


def bars():
    start=datetime(2026,9,7,tzinfo=timezone.utc)
    return pd.DataFrame([dict(time=start+timedelta(minutes=5*i),open=100+i*.1,
        close=100+i*.1+(.15 if i%3 else -.15),high=101+i*.1,low=99+i*.1)
        for i in range(240)])


def compute(frame):
    return closed_bar_features(frame,signal_open=frame.iloc[220]['time'],
        prefix_start=bars().iloc[0]['time'],spread_open=frame.iloc[220]['time'],recorded_spread_price=.02)


def test_future_price_and_precomputed_indicator_poison_do_not_change_features():
    raw=bars(); expected=compute(raw)
    raw.loc[221:,['open','high','low','close']]=999999
    raw['EMA50']=-999;raw['ATR']=999999;raw['RSI']=0
    assert compute(raw)==expected


def test_prefix_equivalence_to_canonical_full_history_indicators():
    raw=bars(); f=compute(raw); canonical=calculate_indicators(raw).iloc[220]
    assert f['rsi']==canonical.RSI
    assert f['ema_distance_atr']==(canonical.close-canonical.EMA50)/canonical.ATR
    assert f['return_3_atr']==(canonical.close-raw.iloc[217].close)/canonical.ATR
    assert f['lagged_spread_atr']==.02/canonical.ATR


def test_shortened_history_rejected_even_when_ema_would_be_finite():
    raw=bars().iloc[1:].reset_index(drop=True)
    with pytest.raises(ValueError,match='prefix'):compute(raw)


@pytest.mark.parametrize('spread',[float('nan'),float('inf'),-1,True])
def test_unverified_spread_value_rejected(spread):
    raw=bars()
    with pytest.raises(ValueError):closed_bar_features(raw,signal_open=raw.iloc[220].time,
        prefix_start=raw.iloc[0].time,spread_open=raw.iloc[220].time,recorded_spread_price=spread)


def test_future_spread_timestamp_rejected():
    raw=bars()
    with pytest.raises(ValueError,match='Spread'):closed_bar_features(raw,signal_open=raw.iloc[220].time,
        prefix_start=raw.iloc[0].time,spread_open=raw.iloc[221].time,recorded_spread_price=.02)


def test_gap_in_feature_lookback_rejected():
    raw=bars().drop(index=219).reset_index(drop=True)
    with pytest.raises(ValueError,match='gap'):compute(raw)
