"""Canonical CLI saved-evidence join qualification; no signal/economic replay."""
from collections import Counter
from datetime import timedelta
import json
from pathlib import Path

from backtesting.label_protocol import file_hash,write_new
from backtesting.opportunity_inventory import aware
from backtesting.provenance import source_snapshot
from research.feature_label_join import join_rows,purge_diagnostic


def qualify(output):
    output.mkdir(parents=True,exist_ok=False)
    features=Path('reports/training-features-20261009-02')
    labels=Path('reports/counterfactual-campaign-resume-20261008-01')
    registration=Path('reports/counterfactual-protocol-20261008-01')
    files=[features/'features.json',features/'coverage-audit.json',features/'implementation-plan.json',
        labels/'summary.json',labels/'coverage-audit.json',registration/'events.json',registration/'protocol.json']
    hashes={p:file_hash(p) for p in files};source=source_snapshot()
    # Dates/embargo fixed before joining; no returns used to choose these diagnostics.
    folds=[('2026-09-22T00:00:00+00:00','2026-09-29T00:00:00+00:00'),
           ('2026-09-29T00:00:00+00:00','2026-10-08T00:00:00+00:00')]
    write_new(output/'protocol.json',{'scope':'TRAIN_ONLY_JOIN_AND_PURGE_DIAGNOSTICS',
        'folds':folds,'embargo_minutes':95,'configurations':1,'source_snapshot':source,
        'input_hashes':{str(k):v for k,v in hashes.items()},'models_fitted':0,'holdouts_read':False})
    try:
        fa=json.loads((features/'coverage-audit.json').read_text());la=json.loads((labels/'coverage-audit.json').read_text())
        if fa['status']!='PASS' or la['status']!='PASS' or la['errors']:raise ValueError('Complete coverage audits required')
        if fa['features_sha256']!=hashes[features/'features.json'] or la['summary_sha256']!=hashes[labels/'summary.json']:
            raise ValueError('Feature/label hash mismatch')
        if fa['implementation_plan_sha256']!=hashes[features/'implementation-plan.json']:raise ValueError('Feature plan differs')
        plan=json.loads((features/'implementation-plan.json').read_text())
        for path,h in plan['input_hashes'].items():
            if file_hash(Path(path))!=h:raise ValueError('Feature input lineage changed')
            hashes[Path(path)]=h
        protocol=json.loads((registration/'protocol.json').read_text())
        if file_hash(registration/'events.json')!=protocol['events_sha256']:raise ValueError('Registration changed')
        events=json.loads((registration/'events.json').read_text())
        rows=join_rows(json.loads((features/'features.json').read_text()),
            json.loads((labels/'summary.json').read_text())['attempts'],protocol['cost_cases'])
        by_id={e['event_id']:e for e in events}
        if len(rows)!=2876 or {r['event_id'] for r in rows}!=set(by_id):raise ValueError('Registered coverage differs')
        for row in rows:
            e=by_id[row['event_id']]
            if row['label_disposition']!=e['status'] or row['direction']!=e['direction'] or aware(row['signal_bar_open'])!=aware(e['signal_bar_open']):raise ValueError('Event registration differs')
            for label in row['labels'].values():
                if label['status']=='EXECUTED' and aware(label['return_label']['available_at'])>aware(protocol['training_window']['end_exclusive']):raise ValueError('Label crosses training boundary')
        diagnostics=[{'start_inclusive':start,'end_exclusive':end,'embargo_minutes':95,
            **purge_diagnostic(rows,aware(start),aware(end),timedelta(minutes=95))} for start,end in folds]
        if source_snapshot()!=source or any(file_hash(k)!=v for k,v in hashes.items()):raise ValueError('Inputs/source changed')
        write_new(output/'joined-events.json',rows)
        write_new(output/'purge-diagnostics.json',diagnostics)
        counts=Counter(a['status'] for r in rows for a in r['labels'].values())
        write_new(output/'summary.json',{'status':'PASS_TRAINING_JOIN_NOT_ML_READY','events':len(rows),
            'cost_dispositions':dict(counts),'joined_sha256':file_hash(output/'joined-events.json'),
            'diagnostics_sha256':file_hash(output/'purge-diagnostics.json'),'models_fitted':0,
            'holdouts_read':False,'performance_evaluated':False,'promotion_authorized':False})
    except Exception as exc:
        write_new(output/'failure.json',{'type':type(exc).__name__,'reason':str(exc)})
        raise
