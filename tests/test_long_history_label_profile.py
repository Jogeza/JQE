import copy
import pytest
from backtesting.long_history_label_profile import equivalent_payload, fingerprint
from backtesting.models import _sha256
from tests.test_long_history_label_resume import evidence


def rehash(payload):
    payload['result_hash']=_sha256({k:v for k,v in payload.items() if k not in ('provider','result_hash')})


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['source_only','outcome','indicator','risk','fingerprint','preimage'])
async def test_equivalence_allows_only_valid_source_identity_transition(evidence, mode):
    original,_,_=evidence
    actual=copy.deepcopy(original)
    actual['run_context']['source_snapshot']['files']['backtesting/backtest.py']='new-source'
    actual['run_fingerprint']=fingerprint(actual)
    if mode=='outcome': actual['trades'][0]['net_pnl']+=1
    if mode=='indicator': actual['indicators'][0]['ema50']+=1
    if mode=='risk': actual['risk']['risk_percent']=2
    if mode=='fingerprint': actual['run_fingerprint']='forged'
    rehash(actual)
    if mode=='preimage':
        actual['result_hash']='forged'
        with pytest.raises(ValueError,match='preimage'): equivalent_payload(actual,original)
    else:
        assert equivalent_payload(actual,original) is (mode=='source_only')
