"""Exact reviewed implementation transition evidence, not a resume bypass."""
import ast
import difflib
import json
from pathlib import Path
from backtesting.label_protocol import file_hash,write_new
from backtesting.provenance import source_snapshot
from backtesting.long_history_label_resume import archive_source,load_prior,verify_evidence
from backtesting.long_history_labels import load_registration


def check_reviewed_diff(old_sources,new_sources):
    if set(old_sources)-set(new_sources):
        raise ValueError('Required transition source removed')
    changed={k for k in old_sources if old_sources[k]!=new_sources.get(k)}
    added=set(new_sources)-set(old_sources)
    if changed!={'backtesting/backtest.py','backtesting/long_history_labels.py','backtesting/models.py'} or added!={
        'backtesting/long_history_label_profile.py','backtesting/serialization_qualification.py','backtesting/source_transition.py'}:
        raise ValueError('Unreviewed transition file set')
    old=old_sources['backtesting/models.py']
    replacement='''        # Use the same normalized snapshot for the preimage instead of converting
        # the complete dataclass a second time. Hash normalization stays unchanged.
        preimage = dict(payload)
        preimage.pop("provider", None)
        payload["result_hash"] = _sha256(preimage)
'''
    if old.replace('        payload["result_hash"] = self.result_hash\n',replacement)!=new_sources['backtesting/models.py']:
        raise ValueError('Unreviewed serializer change')
    if old_sources['backtesting/long_history_labels.py'].replace(
        "'result_hash':engine.result.result_hash,","'result_hash':result['result_hash'],")!=new_sources['backtesting/long_history_labels.py']:
        raise ValueError('Unreviewed dispatcher change')
    # CLI-only additions cannot alter any existing function/class definition.
    def definitions(text):
        return {node.name:ast.dump(node,include_attributes=False) for node in ast.parse(text).body
                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    if definitions(old_sources['backtesting/backtest.py'])!=definitions(new_sources['backtesting/backtest.py']):
        raise ValueError('Canonical replay function changed')


def qualify(registration,original,output,replay_proof):
    output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    plan_path=original/'implementation.json'
    old=json.loads(plan_path.read_text())['source_snapshot']
    current=source_snapshot()
    if old['dependencies']!=current['dependencies']:
        raise ValueError('Dependency transition forbidden')
    old_text={};new_text={}
    evidence={str(plan_path):file_hash(plan_path)}
    for name,digest in old['files'].items():
        path=original/'source-archive'/name
        if file_hash(path)!='sha256:'+digest.removeprefix('sha256:'):
            raise ValueError('Original source archive differs')
        old_text[name]=path.read_text()
        evidence[str(path)]=file_hash(path)
    for name in current['files']:new_text[name]=(root/name).read_text()
    check_reviewed_diff(old_text,new_text)
    archive_source(output,current)
    protocol,events=load_registration(registration)
    selected=[e for e in events if e['status']=='ELIGIBLE_UNLABELLED']
    records,prior=load_prior([original],protocol,selected,old)
    if len(records)!=53 or len(prior['interrupted_attempts'])!=1:
        raise ValueError('Stopped segment disposition changed')
    evidence.update(prior['files'])
    proof=json.loads(replay_proof.read_text())
    if (proof['status']!='PASS_FIXED_EXECUTED_NULL_CANONICAL_EQUIVALENCE_NOT_RESUME_AUTHORIZATION'
        or proof['errors']!=0 or proof['executed']!=2 or proof['null']!=1):
        raise ValueError('Current executed/null replay evidence missing')
    # Proof implementation differs only in this non-replay evidence verifier.
    proof_source=proof['source_snapshot']
    if proof_source['dependencies']!=current['dependencies'] or {
        k:v for k,v in proof_source['files'].items() if k!='backtesting/source_transition.py'}!={
        k:v for k,v in current['files'].items() if k!='backtesting/source_transition.py'}:
        raise ValueError('Replay proof source differs outside evidence verifier')
    proof_archive=replay_proof.parent/'source-archive'
    for name,digest in proof_source['files'].items():
        path=proof_archive/name
        if file_hash(path)!='sha256:'+digest.removeprefix('sha256:'):
            raise ValueError('Replay proof archive changed')
        evidence[str(path)]=file_hash(path)
    evidence[str(replay_proof)]=file_hash(replay_proof)
    serializer=root/'reports/serialization-qualification-20261009-01/audit.json'
    serial=json.loads(serializer.read_text())
    if serial['status']!='PASS_90_BYTE_HASH_EQUIVALENT_SERIALIZERS' or serial['compared']!=90 or serial['errors']!=0:
        raise ValueError('Golden serializer evidence missing')
    evidence[str(serializer)]=file_hash(serializer)
    diff=''.join(''.join(difflib.unified_diff(old_text.get(n,'').splitlines(True),new_text.get(n,'').splitlines(True),
        fromfile='old/'+n,tofile='new/'+n)) for n in sorted(set(old_text)|set(new_text)) if old_text.get(n)!=new_text.get(n))
    with (output/'reviewed-source.diff').open('x') as stream:stream.write(diff)
    verify_evidence({'files':evidence})
    if source_snapshot()!=current:raise ValueError('Transition source drift')
    write_new(output/'contract.json',dict(status='PASS_EXACT_TRANSITION_EVIDENCE_NOT_RESUME_ENABLED',
        old_source_snapshot=old,new_source_snapshot=current,original_segment=str(original.resolve()),
        inherited_completed=53,interrupted_attempts=prior['interrupted_attempts'],
        reviewed_changes=['serializer single conversion','dispatcher reuse verified hash','CLI qualification commands'],
        replay_proof=str(replay_proof),input_hashes=evidence,resume_enabled=False,ml_fits=0,
        replay_proof_source_snapshot=proof_source,
        limitation='Exact serialization transition evidence; current loader still rejects mixed sources. Integrate and test contract-aware lineage before resume'))
