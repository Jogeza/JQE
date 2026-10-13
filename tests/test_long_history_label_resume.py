import json
from dataclasses import asdict
from unittest.mock import patch
import pytest
from backtesting.backtest import run_backtest
from backtesting.long_history_label_resume import (save_result, verify_result, archive_source,
    load_prior, label_from_result, dispatch_lock, verify_evidence)
from backtesting.label_protocol import write_new, file_hash
from backtesting.models import _sha256
from tests.test_long_history_opportunity import contract


@pytest.fixture
async def evidence():
    kwargs, target = contract()
    with patch('backtesting.backtest.generate_trading_signal',return_value={'signal':'BUY','confidence':90}):
        engine = await run_backtest(**kwargs,long_history_opportunity=target)
    result = engine.result.to_dict()
    event = asdict(target)
    model = result['run_context']['frozen_market_model']
    protocol = dict(cost_cases={'cost':model['policy']},inputs=model['evidence_hashes'],
                    risk=result['risk'],execution_descriptor=result['execution'])
    return result,event,protocol


@pytest.mark.asyncio
async def test_full_preimage_and_tampering(evidence):
    result,event,protocol = evidence
    assert verify_result(result,event,'cost',protocol) == result['result_hash']
    result['initial_capital'] = 100
    with pytest.raises(ValueError,match='preimage'):
        verify_result(result,event,'cost',protocol)
    result['result_hash'] = _sha256({k:v for k,v in result.items() if k not in ('provider','result_hash')})
    with pytest.raises(ValueError,match='capital'):
        verify_result(result,event,'cost',protocol)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['complete','interrupted','tampered','active','failed','duplicate','pilot','source'])
async def test_resume_preserves_and_validates_segments(tmp_path,evidence,mode):
    result,event,protocol = evidence
    snapshot = result['run_context']['source_snapshot']
    snapshot = {'files':{},'dependencies':snapshot['dependencies']}
    result['run_context']['source_snapshot'] = snapshot
    result['result_hash'] = _sha256({k:v for k,v in result.items() if k not in ('provider','result_hash')})
    write_new(tmp_path/'implementation.json',dict(scope='FULL_TRAINING_LABELS_NOT_PORTFOLIO_PERFORMANCE',
        registration_sha256=event['registration_sha256'],source_snapshot=snapshot,event_ids=[event['event_id']],owner_pid=999999999))
    write_new(tmp_path/'resume-evidence.json',dict(directories=[],files={}))
    row=dict(event_id=event['event_id'],cost='cost',state='STARTED')
    rows=[row]
    if mode != 'interrupted':
        path=save_result(tmp_path,event['event_id'],'cost',result)
        rows.append(dict(row,state='COMPLETED',artifact_path=str(path),artifact_sha256=file_hash(path),
                         result_hash=result['result_hash'],trades=len(result['trades'])))
    if mode=='tampered': path.write_bytes(b'changed')
    if mode=='failed': rows.append(dict(row,state='FAILED'))
    if mode=='duplicate': rows.append(row)
    if mode in ('pilot','source'):
        plan=json.loads((tmp_path/'implementation.json').read_text())
        if mode=='pilot': plan['scope']='IMPLEMENTATION_PILOT_NOT_PORTFOLIO_PERFORMANCE'
        else: plan['source_snapshot']['dependencies']={}
        (tmp_path/'implementation.json').write_text(json.dumps(plan))
    (tmp_path/'trials.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    before=(tmp_path/'trials.jsonl').read_bytes()
    with patch('backtesting.long_history_label_resume.is_process_alive',return_value=mode=='active'):
        if mode in ('complete','interrupted'):
            records,audit=load_prior([tmp_path],protocol,[event],snapshot)
            assert len(records)==(mode=='complete')
            assert len(audit['interrupted_attempts'])==(mode=='interrupted')
            verify_evidence(audit)
        else:
            with pytest.raises(ValueError): load_prior([tmp_path],protocol,[event],snapshot)
    assert (tmp_path/'trials.jsonl').read_bytes()==before


def test_global_dispatch_lock_released_and_blocks_duplicate():
    with dispatch_lock():
        with pytest.raises(OSError):
            with dispatch_lock(): pass
    with dispatch_lock(): pass


@pytest.mark.asyncio
async def test_exclusive_result_write_and_actual_availability(tmp_path,evidence):
    result,event,_ = evidence
    path=save_result(tmp_path,event['event_id'],'cost',result)
    with pytest.raises(FileExistsError): save_result(tmp_path,event['event_id'],'cost',result)
    label=label_from_result(result,event)
    assert label['status']=='EXECUTED' and label['return_label']['net_r'] is not None
    assert path.exists()

@pytest.mark.asyncio
async def test_null_rejection_and_missing_reasons(evidence):
    result,event,_=evidence
    result['trades']=[]
    from datetime import datetime,timedelta
    result['decisions']=[dict(state='EXECUTION_REJECTED',candle_index=event['source_candle_index']+1,
        timestamp=(datetime.fromisoformat(event['signal_bar_open'])+timedelta(minutes=5)).isoformat(),reasons=['minimum lot'])]
    label=label_from_result(result,event)
    assert label['return_label'] is None and label['status']=='NON_EXECUTABLE'
    result['decisions'][0]['reasons']=[]
    with pytest.raises(ValueError,match='null rejection'): label_from_result(result,event)


def test_source_archive_hashes_and_exclusive_creation(tmp_path):
    from backtesting.provenance import source_snapshot
    snapshot=source_snapshot()
    snapshot['files']={'backtesting/long_history_label_resume.py':snapshot['files']['backtesting/long_history_label_resume.py']}
    archive_source(tmp_path,snapshot)
    assert file_hash(tmp_path/'source-archive/backtesting/long_history_label_resume.py')=='sha256:'+snapshot['files']['backtesting/long_history_label_resume.py']
    with pytest.raises(FileExistsError): archive_source(tmp_path,snapshot)


@pytest.mark.parametrize('mode', ['valid', 'missing', 'duplicate', 'wrong_status', 'altered'])
def test_complete_audit_requires_matching_final_summary(tmp_path, mode):
    from backtesting.long_history_label_audit import verify_final_summary
    row = dict(event_id='event', cost='cost', state='COMPLETED', artifact_sha256='hash')
    records = {('event', 'cost'): row}
    summary = dict(status='FULL_LABEL_DISPATCH_COMPLETE_AUDIT_REQUIRED_NOT_ML_READY',
                   ml_fits=0, attempts=1, records=[dict(row)])
    if mode == 'duplicate': summary['records'].append(dict(row))
    if mode == 'wrong_status': summary['status'] = 'RUNNING'
    if mode == 'altered': summary['records'][0]['artifact_sha256'] = 'other'
    if mode != 'missing': write_new(tmp_path/'summary.json', summary)
    if mode == 'valid': verify_final_summary(tmp_path, records)
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            verify_final_summary(tmp_path, records)


@pytest.mark.asyncio
async def test_full_dispatch_interruption_and_resume_new_directory(tmp_path,evidence,monkeypatch):
    import copy
    from types import SimpleNamespace
    import backtesting.long_history_labels as module
    result,event,protocol=evidence
    kwargs,target=contract()
    event['status']='ELIGIBLE_UNLABELLED'
    protocol['cost_cases']['cost2']=protocol['cost_cases']['cost']
    snapshot={'files':{},'dependencies':{}}
    protocol['source']={'training_implementation_snapshot':snapshot}
    acquisition=tmp_path/'acquisition.json'
    acquisition.write_text(json.dumps(dict(symbols=[dict(symbol=target.symbol,economics={})],terminal_verification={'server_offset_seconds':0})))
    terms=tmp_path/'entry-cost-terms.json'
    terms.write_text(json.dumps(dict(symbols=[dict(symbol=target.symbol,point=.01)])))
    baseline=tmp_path/(target.symbol.replace(' ','_')+'--optimistic_zero_commission--result.json')
    baseline.write_text(json.dumps(result))
    protocol['inputs']={str(p):file_hash(p) for p in (acquisition,terms,baseline)}
    directory=tmp_path/'bundles'/(target.symbol.replace(' ','_')+'_M5')
    directory.mkdir(parents=True)
    (directory/'recorded-spread.json').write_text(json.dumps(dict(content_hash=target.dataset_content_hash,point=.01,
        rows=[dict(time=c.time.isoformat(),spread_points=1) for c in kwargs['dataset']])))
    manifest=SimpleNamespace(provider='weltrade',provider_symbol=target.symbol,canonical_symbol=target.symbol,
        timeframe=kwargs['timeframe'],content_hash=target.dataset_content_hash)
    monkeypatch.setattr(module,'SYMBOLS',(target.symbol,))
    monkeypatch.setattr(module,'load_registration',lambda _: (protocol,[event]))
    monkeypatch.setattr(module,'source_snapshot',lambda: snapshot)
    monkeypatch.setattr(module,'load_dataset_bundle',lambda _: (kwargs['dataset'],manifest))
    monkeypatch.setattr(module,'contract_from_evidence',lambda *a,**k: kwargs['market_model'].contract)
    monkeypatch.setattr('backtesting.long_history_label_resume.is_process_alive',lambda _:False)
    calls=[]
    class Interrupted(BaseException): pass
    async def runner(**params):
        calls.append(params)
        if len(calls)==2: raise Interrupted()
        payload=copy.deepcopy(result)
        payload['run_context']['source_snapshot']=snapshot
        payload['run_context']['frozen_market_model']['evidence_hashes']=protocol['inputs']
        payload['result_hash']=_sha256({k:v for k,v in payload.items() if k not in ('provider','result_hash')})
        return SimpleNamespace(result=SimpleNamespace(to_dict=lambda:payload,result_hash=payload['result_hash']),trades=payload['trades'])
    first=tmp_path/'first'; second=tmp_path/'second'
    with pytest.raises(Interrupted):
        await module.pilot(tmp_path,first,runner,full_campaign=True)
    ledger_before=(first/'trials.jsonl').read_bytes()
    assert not (first/'summary.json').exists()
    await module.pilot(tmp_path,second,runner,full_campaign=True,resume_from=[first])
    assert len(calls)==3
    summary=json.loads((second/'summary.json').read_text())
    assert summary['attempts']==2 and len(summary['records'])==2
    assert (first/'trials.jsonl').read_bytes()==ledger_before
    assert json.loads((second/'resume-evidence.json').read_text())['interrupted_attempts'][0]['cost']=='cost2'
