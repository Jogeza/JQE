"""Golden stored-payload serializer comparison, no replay or new outcomes."""
import importlib.util
import json
from pathlib import Path
import sys
import time
from backtesting.label_protocol import file_hash,write_new
from backtesting.models import BacktestResult
from backtesting.provenance import source_snapshot
from backtesting.long_history_label_resume import archive_source,verify_evidence


def qualify(output):
    output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    old_path=root/'reports/long-history-label-campaign-20261009-01/source-archive/backtesting/models.py'
    plan=json.loads((old_path.parents[2]/'implementation.json').read_text())
    assert file_hash(old_path)=='sha256:'+plan['source_snapshot']['files']['backtesting/models.py'].removeprefix('sha256:')
    spec=importlib.util.spec_from_file_location('_jqe_owned_archived_serializer',old_path)
    old=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=old
    spec.loader.exec_module(old)
    pilot=root/'reports/long-history-label-pilot-20261009-01'
    audit_path=root/'reports/long-history-label-pilot-audit-20261009-01/audit.json'
    audit=json.loads(audit_path.read_text())
    assert audit['errors']==0 and audit['attempts']==90
    snapshot=source_snapshot()
    archive_source(output,snapshot)
    write_new(output/'selection.json',dict(status='FIXED_90_GOLDEN_SERIALIZER_COMPARISONS',
        trial_configurations=1,changed_strategy_parameters=0,source_snapshot=snapshot,
        reference_source=str(old_path),reference_sha256=file_hash(old_path),new_replays=0))
    records=[]
    evidence={str(old_path):file_hash(old_path),str(audit_path):file_hash(audit_path)}
    files=sorted(pilot.glob('*--result.json'))
    assert len(files)==90
    for i,path in enumerate(files):
        assert file_hash(path)==audit['file_hashes'][str(path)]
        evidence[str(path)]=file_hash(path)
        saved=json.loads(path.read_text())
        payload={k:v for k,v in saved.items() if k!='result_hash'}
        actual=BacktestResult(**payload)
        reference=old.BacktestResult(**payload)
        # Alternate timing order to reduce systematic cache/order bias.
        values={};timings={}
        for name,obj in ([('old',reference),('new',actual)] if i%2==0 else [('new',actual),('old',reference)]):
            start=time.perf_counter();values[name]=obj.to_json_bytes();timings[name]=time.perf_counter()-start
        assert values['new']==values['old'],'Canonical serialized bytes differ'
        assert json.loads(values['new'])==saved,'Golden complete payload differs'
        assert actual.result_hash==saved['result_hash'],'Golden result hash differs'
        records.append(dict(path=str(path),result_hash=saved['result_hash'],**timings))
    verify_evidence({'files':evidence})
    assert source_snapshot()==snapshot,'Source drift during qualification'
    old_seconds=sum(r['old'] for r in records);new_seconds=sum(r['new'] for r in records)
    write_new(output/'audit.json',dict(status='PASS_90_BYTE_HASH_EQUIVALENT_SERIALIZERS',errors=0,
        compared=len(records),old_seconds=old_seconds,new_seconds=new_seconds,
        serialization_speed_ratio_old_over_new=old_seconds/new_seconds,
        evidence=evidence,records=records,new_replays=0,ml_fits=0,
        limitation='Normalized saved JSON representations plus separate typed unit/replay checks; serializer microbenchmark, not whole campaign throughput'))
