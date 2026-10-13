import copy
import gzip
import json
from pathlib import Path
import pytest
from backtesting.models import _sha256
from backtesting.long_history_result_store import save_shared_result, load_result


def result(regime='TRENDING'):
    payload = dict(symbol='SFX Vol 99', dataset_hash='dataset',
                   indicators=[dict(candle_index=i, ema50=100+i, regime=regime if i==2 else None)
                               for i in range(4)], run_context=dict(source_snapshot={'files':{'x':'hash'}}),
                   trades=[], provider='weltrade')
    payload['result_hash'] = _sha256({k:v for k,v in payload.items() if k!='provider'})
    return payload


def rewrite(path, value):
    path.write_bytes(gzip.compress(json.dumps(value).encode(), mtime=0))


def test_lossless_dedup_with_distinct_regimes_and_dependency_evidence(tmp_path):
    original = result()
    before = copy.deepcopy(original)
    first = save_shared_result(tmp_path, 'first', 'cost', original)
    second = save_shared_result(tmp_path, 'second', 'cost', result('RANGING'))
    assert original == before
    assert len(list((tmp_path/'shared').glob('*.json.gz'))) == 2
    evidence = {}
    assert load_result(first, evidence) == before
    assert load_result(second)['indicators'][2]['regime'] == 'RANGING'
    assert len(evidence) == 2
    with pytest.raises(FileExistsError): save_shared_result(tmp_path, 'first', 'cost', original)


@pytest.mark.parametrize('mode', ['missing', 'corrupt', 'changed_hash', 'bad_reference',
                                  'duplicate_override', 'changed_outcome', 'unknown_schema'])
def test_corruption_and_missing_dependencies_reject(tmp_path, mode):
    path = save_shared_result(tmp_path, 'event', 'cost', result())
    envelope = json.loads(gzip.decompress(path.read_bytes()))
    dependency = tmp_path/'shared'/(envelope['indicators']['digest'][7:]+'.json.gz')
    if mode == 'missing': dependency.unlink()
    elif mode == 'corrupt': dependency.write_bytes(b'corrupt')
    elif mode == 'changed_hash': envelope['indicators']['artifact_sha256'] = 'sha256:wrong'
    elif mode == 'bad_reference': envelope['indicators']['digest'] = '../../escape'
    elif mode == 'duplicate_override': envelope['regime_overrides'] *= 2
    elif mode == 'changed_outcome': envelope['payload']['trades'] = [{'net_pnl':1000}]
    elif mode == 'unknown_schema': envelope['storage_schema'] = 'unknown'
    if mode not in ('missing','corrupt'): rewrite(path, envelope)
    with pytest.raises((ValueError, FileNotFoundError)): load_result(path)


def test_arithmetic_drift_and_legacy_preimage_validation(tmp_path):
    save_shared_result(tmp_path, 'first', 'cost', result())
    altered = result()
    altered['indicators'][0]['ema50'] = 999
    altered['result_hash'] = _sha256({k:v for k,v in altered.items() if k not in ('provider','result_hash')})
    with pytest.raises(ValueError, match='arithmetic'): save_shared_result(tmp_path, 'second', 'cost', altered)
    legacy = tmp_path/'legacy.gz'
    rewrite(legacy, result())
    assert load_result(legacy) == result()
    altered['result_hash'] = 'wrong'
    rewrite(legacy, altered)
    with pytest.raises(ValueError, match='preimage'): load_result(legacy)
