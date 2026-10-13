from datetime import datetime,timedelta,timezone
import pytest
from research.ml_validation import LabelInterval,ReadinessEvidence,chronological_fold,readiness,validate_features

NOW=datetime(2026,10,8,tzinfo=timezone.utc)

def event(name,minute,end):
    return LabelInterval(name,NOW+timedelta(minutes=minute),NOW+timedelta(minutes=minute),NOW+timedelta(minutes=end))

def test_purge_actual_label_intervals_and_group_simultaneous_symbols():
    events=(event('past',0,5),event('overlap',10,65),event('boundary',20,50),
        event('symbol_a',60,70),event('symbol_b',60,75),event('crosses_right',110,125))
    train,test=chronological_fold(events,NOW+timedelta(minutes=60),NOW+timedelta(minutes=120),timedelta(minutes=10))
    assert train==('past',)
    assert test==('symbol_a','symbol_b')

@pytest.mark.parametrize('column',['net_r','net_pnl','exit_price','mae_r','mfe_r','entry_gap_atr','future_spread','label'])
def test_outcomes_and_future_fill_features_are_rejected(column):
    with pytest.raises(ValueError):validate_features({column:1.0})

@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,'1'])
def test_nonfinite_or_non_numeric_features_rejected(value):
    with pytest.raises(ValueError):validate_features({'rsi':value})

def test_valid_features_and_feature_availability():
    validate_features({'rsi':50.,'ema_distance_atr':2.})
    with pytest.raises(ValueError):LabelInterval('future',NOW,NOW+timedelta(seconds=1),NOW+timedelta(minutes=5))
    with pytest.raises(ValueError):LabelInterval('naive',NOW.replace(tzinfo=None),NOW,NOW+timedelta(minutes=5))
    with pytest.raises(ValueError):LabelInterval('label',NOW,NOW,NOW)

def test_duplicate_identity_and_invalid_window_rejected():
    row=event('same',0,5)
    with pytest.raises(ValueError):chronological_fold((row,row),NOW,NOW+timedelta(days=1),timedelta(0))
    with pytest.raises(ValueError):chronological_fold((),NOW,NOW,timedelta(0))

def test_current_evidence_blocks_fit_and_even_complete_evidence_never_promotes():
    current=ReadinessEvidence(266,30,1,False,False,False,False,False)
    result=readiness(current)
    assert result['status']=='BLOCKED' and len(result['blocks'])==7
    complete=ReadinessEvidence(1000,90,1,True,True,True,True,True)
    assert readiness(complete)['status']=='ELIGIBLE_FOR_PREREGISTERED_OFFLINE_FIT_ONLY'
    assert readiness(complete)['promotion_authorized'] is False
    with pytest.raises(ValueError):ReadinessEvidence(1000,90,1,'yes',True,True,True,True)
