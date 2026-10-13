from copy import deepcopy
from datetime import datetime,timedelta,timezone

import pytest

from research.feature_label_join import join_rows,purge_diagnostic
from research.ml_validation import FEATURES

NOW=datetime(2026,9,8,tzinfo=timezone.utc)


def feature(key='event',decision=NOW):
    return {'event_id':key,'signal_bar_open':(decision-timedelta(minutes=5)).isoformat(),
        'decision_available_at':decision.isoformat(),'features_available_at':decision.isoformat(),
        'features':{k:1. for k in FEATURES},'feature_status':'AVAILABLE',
        'label_disposition':'ELIGIBLE','direction':'BUY'}


def label(key='event',cost='zero',end=NOW+timedelta(minutes=5)):
    return {'event_id':key,'cost':cost,'status':'EXECUTED','return_label':{
        'available_at':end.isoformat(),'net_r':-1.,'net_modelled_usd':-.5},'rejection_reasons':[]}


def test_cost_reject_remains_null_and_feature_not_duplicated():
    reject={'event_id':'event','cost':'stress','status':'NON_EXECUTABLE','return_label':None,'rejection_reasons':['Minimum lot']}
    joined=join_rows([feature()],[label(),reject],['zero','stress'])
    assert len(joined)==1 and joined[0]['labels']['stress']['return_label'] is None


def test_censored_event_preserved_with_unavailable_features():
    row=feature();row.update(feature_status='UNAVAILABLE',features=None,features_available_at=None,
        unavailable_reason='Gap',label_disposition='CENSORED_GAP')
    joined=join_rows([row],[],['zero','stress'])
    assert all(x['status']=='CENSORED' and x['return_label'] is None for x in joined[0]['labels'].values())


@pytest.mark.parametrize('case',['duplicate_feature','duplicate_label','missing_cost','future_feature','zero_reject','nonfinite'])
def test_invalid_joins_fail_closed(case):
    features=[feature()];attempts=[label()];costs=['zero']
    if case=='duplicate_feature':features*=2
    elif case=='duplicate_label':attempts*=2
    elif case=='missing_cost':costs.append('stress')
    elif case=='future_feature':features[0]['features_available_at']=(NOW+timedelta(minutes=5)).isoformat()
    elif case=='zero_reject':attempts[0].update(status='NON_EXECUTABLE',return_label=0,rejection_reasons=['reject'])
    else:attempts[0]['return_label']['net_r']=float('nan')
    with pytest.raises(ValueError):join_rows(features,attempts,costs)


def test_latest_cost_end_purges_siblings_at_exact_cutoff():
    start=NOW+timedelta(hours=2)
    joined=join_rows([feature()],[label(end=NOW+timedelta(minutes=5)),
        label(cost='stress',end=start-timedelta(minutes=95))],['zero','stress'])
    d=purge_diagnostic(joined,start,start+timedelta(days=1),timedelta(minutes=95))
    assert not d['train_event_ids']  # Equality at cutoff is purged for both costs.


def test_label_at_right_boundary_excluded_and_short_actual_end_retained():
    start=NOW+timedelta(hours=3);end=start+timedelta(hours=1)
    rows=[feature('past'),feature('cross',start),feature('inside',start+timedelta(minutes=5))]
    joined=join_rows(rows,[label('past'),label('cross',end=end),
        label('inside',end=start+timedelta(minutes=10))],['zero'])
    d=purge_diagnostic(joined,start,end,timedelta(minutes=95))
    assert d['train_event_ids']==['past'] and d['evaluation_event_ids']==['inside']
