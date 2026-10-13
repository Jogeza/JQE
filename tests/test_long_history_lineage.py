import copy
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from backtesting.long_history_lineage import verify_overlay,load_transition,EVIDENCE_HASH,SCHEMA
from backtesting.long_history_label_resume import load_prior,save_result
from backtesting.label_protocol import file_hash,write_new
from backtesting.models import _sha256
from tests.test_long_history_label_resume import evidence


@pytest.mark.parametrize('mode',['valid','protected','dependency','removed','added'])
def test_integration_overlay_rejects_unreviewed_changes(mode):
    old={'files':{'strategy/pipeline.py':'old','backtesting/backtest.py':'old'},'dependencies':{'python':'x'}}
    new=copy.deepcopy(old)
    new['files'].update({'backtesting/backtest.py':'new','backtesting/long_history_lineage.py':'new'})
    if mode=='protected':new['files']['strategy/pipeline.py']='new'
    if mode=='dependency':new['dependencies']['python']='other'
    if mode=='removed':new['files'].pop('strategy/pipeline.py')
    if mode=='added':new['files']['backtesting/extra.py']='new'
    if mode=='valid':verify_overlay(old,new)
    else:
        with pytest.raises(ValueError):verify_overlay(old,new)


def test_evidence_accepts_both_existing_hash_encodings_without_ignoring_bytes(tmp_path):
    from backtesting.long_history_lineage import _inputs
    path=tmp_path/'owned.txt';path.write_text('immutable')
    digest=file_hash(path)
    _inputs({str(path):digest})
    _inputs({str(path):digest.removeprefix('sha256:')})
    path.write_text('changed')
    with pytest.raises(ValueError):_inputs({str(path):digest})


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['qualified','default','wrong_ancestor','wrong_result_source','count','active','missing_ancestor'])
async def test_opt_in_mixed_source_requires_exact_segment_lineage(tmp_path,evidence,mode):
    result,event,protocol=evidence
    old={'files':{},'dependencies':{'identity':'old'}}
    new={'files':{},'dependencies':{'identity':'new'}}
    result['run_context']['source_snapshot']=old if mode!='wrong_result_source' else new
    result['result_hash']=_sha256({k:v for k,v in result.items() if k not in ('provider','result_hash')})
    segment=tmp_path/'old';segment.mkdir()
    write_new(segment/'implementation.json',dict(scope='FULL_TRAINING_LABELS_NOT_PORTFOLIO_PERFORMANCE',
        registration_sha256=event['registration_sha256'],source_snapshot=old,event_ids=[event['event_id']],owner_pid=999999999))
    write_new(segment/'resume-evidence.json',dict(directories=[],files={}))
    artifact=save_result(segment,event['event_id'],'cost',result)
    started=dict(event_id=event['event_id'],cost='cost',state='STARTED')
    completed=dict(started,state='COMPLETED',artifact_path=str(artifact),artifact_sha256=file_hash(artifact),
                   result_hash=result['result_hash'],trades=len(result['trades']))
    (segment/'trials.jsonl').write_text(json.dumps(started)+'\n'+json.dumps(completed)+'\n')
    transition=dict(original_segment=str(segment.resolve()),old_source_snapshot=old,
        inherited_completed=1,interrupted_attempts=[],_contract_sha256='contract')
    if mode=='wrong_ancestor':transition['original_segment']=str(tmp_path/'other')
    if mode=='count':transition['inherited_completed']=2
    before=(segment/'trials.jsonl').read_bytes()
    with patch('backtesting.long_history_label_resume.is_process_alive',return_value=mode=='active'):
        if mode=='qualified':
            rows,audit=load_prior([segment],protocol,[event],new,transition=transition)
            assert len(rows)==1 and audit['source_transition']['old_source_snapshot']==old
        else:
            with pytest.raises(ValueError):load_prior([] if mode=='missing_ancestor' else [segment],protocol,[event],new,
                transition=None if mode=='default' else transition)
    assert (segment/'trials.jsonl').read_bytes()==before


@pytest.mark.parametrize('mode',['valid','tamper','snapshot','evidence','ancestor','dependency'])
def test_hashed_contract_validation_and_input_rechecks(tmp_path,monkeypatch,mode):
    import backtesting.long_history_lineage as module
    evidence_path=tmp_path/'evidence.json'
    old={'files':{},'dependencies':{}}
    approved={'files':{'strategy/pipeline.py':'hash'},'dependencies':{}}
    current=copy.deepcopy(approved);current['files']['backtesting/long_history_lineage.py']='new'
    ancestor=str(tmp_path/'old')
    write_new(evidence_path,dict(old_source_snapshot=old,new_source_snapshot=approved,
        original_segment=ancestor,interrupted_attempts=[{'directory':ancestor}],input_hashes={}))
    digest=file_hash(evidence_path)
    monkeypatch.setattr(module,'EVIDENCE_HASH',digest)
    payload=dict(schema=SCHEMA,status='QUALIFIED_EXACT_RESUME_LINEAGE',implementation_source_snapshot=current,
        evidence_contract_sha256=digest,evidence_contract=str(evidence_path),inherited_completed=53,
        interrupted_attempts=[{'directory':ancestor}],ml_fits=0,old_source_snapshot=old,
        approved_source_snapshot=approved,original_segment=ancestor,input_hashes={str(evidence_path):digest})
    if mode=='snapshot':payload['implementation_source_snapshot']={'files':{},'dependencies':{}}
    if mode=='ancestor':payload['original_segment']='other'
    if mode=='evidence':payload['input_hashes'][str(evidence_path)]='wrong'
    if mode=='dependency':payload['implementation_source_snapshot']['dependencies']={'new':'version'}
    path=tmp_path/'contract.json';write_new(path,payload)
    write_new(path.with_suffix('.sha256.json'),{'sha256':file_hash(path)})
    if mode=='tamper':path.write_text(path.read_text()+' ')
    if mode=='valid':assert load_transition(path,current)[0]['inherited_completed']==53
    else:
        with pytest.raises(ValueError):load_transition(path,current)
