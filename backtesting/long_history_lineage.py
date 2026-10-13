"""Explicit, evidence-bound serialization lineage; default resume stays strict."""
import ast
import json
from pathlib import Path
from backtesting.label_protocol import file_hash, write_new
from backtesting.provenance import source_snapshot

EVIDENCE_HASH = 'sha256:cfc3b07c3b53d3b02fda229cc944aa003b0baea020d7c27f6a8a4a086efb6b06'
SCHEMA = 'jqe-exact-serialization-resume-lineage-v1'


def verify_overlay(approved, implementation):
    """No data, strategy, accounting or replay arithmetic transition allowed."""
    if approved['dependencies'] != implementation['dependencies']:
        raise ValueError('Lineage dependencies differ')
    allowed = {'backtesting/backtest.py','backtesting/long_history_labels.py',
               'backtesting/long_history_label_resume.py','backtesting/long_history_label_audit.py'}
    if set(approved['files'])-set(implementation['files']):
        raise ValueError('Lineage source removed')
    if set(implementation['files'])-set(approved['files']) != {'backtesting/long_history_lineage.py'}:
        raise ValueError('Unrecognized lineage source additions')
    if any(implementation['files'].get(k)!=v for k,v in approved['files'].items() if k not in allowed):
        raise ValueError('Unreviewed protected lineage source change')


def _inputs(files):
    for name,digest in files.items():
        if file_hash(Path(name)) != 'sha256:'+digest.removeprefix('sha256:'):
            raise ValueError('Lineage evidence changed')


def load_transition(path, snapshot):
    path=Path(path).resolve()
    payload=json.loads(path.read_text())
    sidecar=path.with_suffix('.sha256.json')
    if file_hash(path)!=json.loads(sidecar.read_text())['sha256']:
        raise ValueError('Lineage contract checksum differs')
    if (payload['schema']!=SCHEMA or payload['status']!='QUALIFIED_EXACT_RESUME_LINEAGE'
        or payload['implementation_source_snapshot']!=snapshot
        or payload['evidence_contract_sha256']!=EVIDENCE_HASH
        or payload['inherited_completed']!=53 or len(payload['interrupted_attempts'])!=1
        or payload['ml_fits']!=0):
        raise ValueError('Lineage scope or implementation identity differs')
    evidence_path=Path(payload['evidence_contract'])
    if file_hash(evidence_path)!=EVIDENCE_HASH:
        raise ValueError('Unrecognized transition evidence contract')
    approved=json.loads(evidence_path.read_text())
    if (payload['old_source_snapshot']!=approved['old_source_snapshot']
        or payload['approved_source_snapshot']!=approved['new_source_snapshot']
        or payload['original_segment']!=approved['original_segment']
        or payload['interrupted_attempts']!=approved['interrupted_attempts']):
        raise ValueError('Lineage old source/ancestor differs')
    verify_overlay(approved['new_source_snapshot'],snapshot)
    _inputs(approved['input_hashes'])
    _inputs(payload['input_hashes'])
    return payload, {**approved['input_hashes'],**payload['input_hashes'],
                     str(path):file_hash(path),str(sidecar):file_hash(sidecar)}


def qualify(output):
    """Freeze current integration and revalidate inherited evidence without replay."""
    from backtesting.long_history_label_resume import archive_source,load_prior
    from backtesting.long_history_labels import load_registration
    root=Path(__file__).resolve().parents[1]
    path=root/'reports/source-transition-evidence-20261010-01/contract.json'
    if file_hash(path)!=EVIDENCE_HASH:raise ValueError('Evidence contract differs')
    approved=json.loads(path.read_text())
    _inputs(approved['input_hashes'])
    snapshot=source_snapshot()
    verify_overlay(approved['new_source_snapshot'],snapshot)
    archive=root/'reports/source-transition-evidence-20261010-01/source-archive'
    def replay_module(text):
        # Only the CLI main block may change; imports/constants/functions cannot.
        nodes=[n for n in ast.parse(text).body if not (isinstance(n,ast.If)
            and ast.dump(n.test,include_attributes=False)==ast.dump(ast.parse('__name__ == "__main__"',mode='eval').body,include_attributes=False))]
        return [ast.dump(n,include_attributes=False) for n in nodes]
    if replay_module((archive/'backtesting/backtest.py').read_text())!=replay_module((root/'backtesting/backtest.py').read_text()):
        raise ValueError('Canonical replay changed during integration')
    original=Path(approved['original_segment'])
    protocol,events=load_registration(root/'reports/long-history-label-registration-20261009-01')
    records,evidence=load_prior([original],protocol,[e for e in events if e['status']=='ELIGIBLE_UNLABELLED'],
                               approved['old_source_snapshot'])
    if len(records)!=53 or evidence['interrupted_attempts']!=approved['interrupted_attempts']:
        raise ValueError('Inherited coverage differs')
    output.mkdir(parents=True,exist_ok=False)
    archive_source(output,snapshot)
    inputs={str(path):file_hash(path),**evidence['files']}
    for name,digest in snapshot['files'].items():
        inputs[str((output/'source-archive'/name).resolve())]='sha256:'+digest.removeprefix('sha256:')
    payload=dict(schema=SCHEMA,status='QUALIFIED_EXACT_RESUME_LINEAGE',
        old_source_snapshot=approved['old_source_snapshot'],approved_source_snapshot=approved['new_source_snapshot'],
        implementation_source_snapshot=snapshot,original_segment=approved['original_segment'],
        evidence_contract=str(path),evidence_contract_sha256=EVIDENCE_HASH,
        inherited_completed=53,interrupted_attempts=approved['interrupted_attempts'],input_hashes=inputs,
        ml_fits=0,scope='Only this reviewed stopped segment and this exact implementation; no generic source bypass')
    write_new(output/'contract.json',payload)
    write_new(output/'contract.sha256.json',{'sha256':file_hash(output/'contract.json')})
    load_transition(output/'contract.json',snapshot)
