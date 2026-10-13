from datetime import datetime,timezone

import pytest

from research.entry_campaign import UNIVERSE
from tools.acquire_entry_campaign import validate_history_protocol


def protocol():
    return {'protocol_id':'jqe-pre-holdout-history-v1','symbols':list(UNIVERSE),
        'history':{'start_inclusive':'2026-07-10T00:00:00+00:00','end_exclusive':'2026-10-08T00:00:00+00:00'},
        'models_fitted':0,'performance_evaluation_authorized':False}


def test_history_cutoff_preserves_original_holdouts():
    start,end=validate_history_protocol(protocol())
    assert (end-start).days==90 and end==datetime(2026,10,8,tzinfo=timezone.utc)


@pytest.mark.parametrize('case',['holdout','short','naive','provider_alias','performance'])
def test_invalid_history_registration_fails_closed(case):
    p=protocol()
    if case=='holdout':p['history']['end_exclusive']='2026-10-09T00:00:00+00:00'
    elif case=='short':p['history']['start_inclusive']='2026-09-01T00:00:00+00:00'
    elif case=='naive':p['history']['start_inclusive']='2026-07-10T00:00:00'
    elif case=='provider_alias':p['symbols']=['R_100']
    else:p['performance_evaluation_authorized']=True
    with pytest.raises(ValueError):validate_history_protocol(p)
