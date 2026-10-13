"""Frozen training-only feature export dispatched by the canonical backtest CLI."""
from collections import Counter
from datetime import timedelta
import json
import math
from pathlib import Path

import pandas as pd

from backtesting.label_protocol import file_hash, write_new
from backtesting.opportunity_inventory import aware
from backtesting.provenance import source_snapshot
from broker.types import Timeframe
from data.dataset import load_dataset_bundle, candle_content_hash
from research.causal_features import closed_bar_features


def verify_signal(signal, event, saved):
    # Baseline queue_signal appends stateful occupancy/risk reasons; the canonical
    # reason prefix must still match exactly, along with direction and confidence.
    reasons=signal['reasons']
    if (signal['signal'],signal['confidence'])!=(event['direction'],saved['confidence']) or saved['reasons'][:len(reasons)]!=reasons:
        raise ValueError('Canonical event signal differs')


def verify_spreads(sidecar, candles, manifest, acquisition_record, sidecar_hash):
    if (sidecar['provider'] != 'weltrade' or sidecar['content_hash'] != manifest.content_hash
        or sidecar_hash.removeprefix('sha256:') != acquisition_record['spread_sidecar_sha256']
        or acquisition_record['content_hash'] != manifest.content_hash
        or acquisition_record['status'] != 'ACQUIRED_NOT_PROMOTION_QUALIFIED'):
        raise ValueError('Spread acquisition binding differs')
    point=sidecar['point']
    if isinstance(point,bool) or not math.isfinite(point) or point<=0 or point!=acquisition_record['economics']['point']:
        raise ValueError('Invalid recorded point')
    rows=sidecar['rows']
    if len(rows)!=len(candles):raise ValueError('Spread row coverage differs')
    for row,candle in zip(rows,candles):
        if aware(row['time'])!=candle.time or type(row['spread_points']) is not int or row['spread_points']<0:
            raise ValueError('Spread timestamps/value differ')
    return {c.time:r['spread_points']*point for c,r in zip(candles,rows)}


async def record(contract_path: Path, output: Path, runner):
    output.mkdir(parents=True,exist_ok=False)
    try:
        contract=json.loads(contract_path.read_text())
        if file_hash(contract_path)!=json.loads(contract_path.with_suffix('.sha256.json').read_text())['sha256']:
            raise ValueError('Feature contract checksum differs')
        expected_scope={'provider':'weltrade','symbol':'SFX Vol 99','timeframe':'M5',
            'training_start_inclusive':'2026-09-08T00:00:00+00:00','training_end_exclusive':'2026-10-08T00:00:00+00:00'}
        if contract['id']!='jqe-causal-feature-semantics-v1' or contract['scope']!=expected_scope:
            raise ValueError('Unrecognized training-only contract')
        bound={Path(k):v for k,v in contract['input_hashes'].items()}
        bound[contract_path]=file_hash(contract_path)
        for path,h in bound.items():
            if file_hash(path)!=h:raise ValueError('Frozen contract input changed: '+str(path))
        source=source_snapshot();old=contract['source_snapshot']
        changes={k for k in set(source['files'])|set(old['files']) if source['files'].get(k)!=old['files'].get(k)}
        if changes-{'backtesting/backtest.py','backtesting/feature_recorder.py'} or source['dependencies']!=old['dependencies']:
            raise ValueError('Source changed beyond declared recording orchestration')
        registration=Path('reports/counterfactual-protocol-20261008-01')
        protocol=json.loads((registration/'protocol.json').read_text())
        if file_hash(registration/'protocol.json')!=json.loads((registration/'protocol.sha256.json').read_text())['sha256']:
            raise ValueError('Label protocol checksum differs')
        for path,h in protocol['inputs'].items():
            if file_hash(Path(path))!=h:raise ValueError('Registered data changed')
            bound[Path(path)]=h
        bound[registration/'events.json']=protocol['events_sha256']
        if file_hash(registration/'events.json')!=protocol['events_sha256']:raise ValueError('Events changed')
        events=json.loads((registration/'events.json').read_text())
        if len(events)!=2876 or len({e['event_id'] for e in events})!=2876:raise ValueError('Event census differs')
        labels=Path('reports/counterfactual-campaign-resume-20261008-01')
        audit=json.loads((labels/'coverage-audit.json').read_text())
        if audit['status']!='PASS' or audit['errors'] or audit['completed_attempts']!=8499:
            raise ValueError('Complete label coverage required')
        if file_hash(labels/'summary.json')!=audit['summary_sha256']:raise ValueError('Label summary changed')
        bound[labels/'summary.json']=audit['summary_sha256']
        campaign=Path('reports/entry-campaign-20261008-04')
        bundle=campaign/'bundles/SFX_Vol_99_M5'
        candles,manifest=load_dataset_bundle(bundle)
        if (manifest.provider,manifest.canonical_symbol,manifest.provider_symbol,manifest.timeframe)!=(
            'weltrade','SFX Vol 99','SFX Vol 99',Timeframe.M5):raise ValueError('Native data identity differs')
        if any(c.time+timedelta(minutes=5)>manifest.retrieved_at for c in candles):raise ValueError('Unclosed dataset')
        acq=json.loads((campaign/'acquisition.json').read_text())
        acq_record=next(r for r in acq['symbols'] if r['symbol']=='SFX Vol 99')
        spreads=verify_spreads(json.loads((bundle/'recorded-spread.json').read_text()),candles,manifest,
            acq_record,file_hash(bundle/'recorded-spread.json'))
        baseline=json.loads(Path(next(k for k in protocol['inputs'] if k.endswith('--result.json'))).read_text())
        start,end=(aware(expected_scope[k]) for k in ('training_start_inclusive','training_end_exclusive'))
        prefix=[c for c in candles if aware(baseline['dataset_start'])<=c.time<end]
        if not prefix or prefix[-1].time!=aware(baseline['dataset_end']) or candle_content_hash(prefix)!=baseline['run_context']['manifest_content_hash']:
            raise ValueError('Original full indicator prefix differs')
        first=next(i for i,c in enumerate(prefix) if c.time>=start)
        if first!=200:raise ValueError('Original warmup differs')
        raw=pd.DataFrame([c.model_dump() for c in prefix])
        targets={aware(e['signal_bar_open']):e for e in events}
        decisions={aware(d['timestamp']):d for d in baseline['decisions'] if d['state']!='EXECUTION_REJECTED'}
        saved_indicators={r['candle_index']:r for r in baseline['indicators']}
        source_positions={c.time:i for i,c in enumerate(candles)}
        rows=[]; seen=set()
        write_new(output/'implementation-plan.json',{'contract_sha256':file_hash(contract_path),'source_snapshot':source,
            'prior_feature_source':old,'changes':sorted(changes),'input_hashes':{str(k):v for k,v in bound.items()},
            'scope':expected_scope,'events':2876,'claim':'FEATURE_RECORDING_NO_ECONOMIC_REPLAY'})
        def observe(i,history,signal):
            time=prefix[i].time; e=targets.get(time)
            if signal['signal'] in ('BUY','SELL') and e is None:raise ValueError('Extra canonical opportunity')
            if e is None:return
            saved=decisions[time]
            verify_signal(signal,e,saved)
            if e['source_candle_index']!=source_positions[time] or not start<=time<end or e['event_id'] in seen:
                raise ValueError('Event identity/chronology differs')
            seen.add(e['event_id'])
            for field,column in [('atr','ATR'),('rsi','RSI'),('ema50','EMA50'),('ema200','EMA200')]:
                if float(history.iloc[-1][column])!=saved_indicators[i][field]:
                    raise ValueError('Original canonical indicators differ')
            # Compare canonical observer indicators to saved observations; independent
            # raw-prefix helper recomputes the frozen formulas without trusting aliases.
            features=None; reason=None
            try:
                features=closed_bar_features(raw,signal_open=time,prefix_start=prefix[0].time,
                    spread_open=time,recorded_spread_price=spreads[time])
            except ValueError as exc:reason=str(exc)
            rows.append({'event_id':e['event_id'],'direction':e['direction'],'signal_bar_open':time.isoformat(),
                'decision_available_at':(time+timedelta(minutes=5)).isoformat(),
                'features_available_at':(time+timedelta(minutes=5)).isoformat() if features is not None else None,
                'label_disposition':e['status'],'feature_status':'AVAILABLE' if features is not None else 'UNAVAILABLE',
                'unavailable_reason':reason,'features':features,'source_candle_index':e['source_candle_index']})
        engine=await runner(symbol='SFX Vol 99',timeframe=Timeframe.M5,dataset=prefix,provider='weltrade',
            start_index=first,end_index=len(prefix),feature_observer=observe,features_only=True)
        if engine.result is not None or engine.trades:raise ValueError('Feature-only replay produced economic results')
        if seen!={e['event_id'] for e in events}:raise ValueError('Missing canonical events')
        if source_snapshot()!=source or any(file_hash(k)!=v for k,v in bound.items()):raise ValueError('Recording inputs/source changed')
        write_new(output/'features.json',rows)
        write_new(output/'summary.json',{'status':'COMPLETE_TRAINING_FEATURE_RECORDING_NOT_ML_READY','events':len(rows),
            'feature_status_counts':dict(Counter(r['feature_status'] for r in rows)),
            'label_disposition_counts':dict(Counter(r['label_disposition'] for r in rows)),
            'features_sha256':file_hash(output/'features.json'),'source_snapshot_matches':True,
            'models_fitted':0,'holdouts_read':False,'economic_replays':0,'promotion_authorized':False})
    except Exception as exc:
        write_new(output/'failure.json',{'status':'FAILED','type':type(exc).__name__,'reason':str(exc)})
        raise
