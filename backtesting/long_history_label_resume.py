"""Saved full-result verification and immutable multi-segment resume evidence."""
import json
import os
from pathlib import Path

from backtesting.label_protocol import file_hash
from backtesting.models import _sha256
from core.processes import is_process_alive


def archive_source(output, snapshot):
    root = Path(__file__).resolve().parents[1]
    for name, digest in snapshot['files'].items():
        source = root/name
        destination = output/'source-archive'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(source.read_bytes())
        if file_hash(destination) != ('sha256:'+digest if not digest.startswith('sha256:') else digest):
            raise ValueError('Source changed during archive')


def save_result(output, event_id, cost, result):
    from backtesting.long_history_result_store import save_shared_result
    return save_shared_result(output, event_id, cost, result)


def verify_result(result, event, cost, protocol):
    payload = dict(result)
    digest = payload.pop('result_hash')
    payload.pop('provider', None)
    if _sha256(payload) != ('sha256:'+digest if not digest.startswith('sha256:') else digest):
        raise ValueError('Complete result hash preimage differs')
    context = result['run_context']
    model = context['frozen_market_model']
    evaluation = context['evaluation']
    target = context['long_history_opportunity']
    if (target['event_id'] != event['event_id'] or target['symbol'] != event['symbol']
        or target['direction'] != event['direction'] or target['confidence'] != event['confidence']
        or target['signal_bar_open'] != event['signal_bar_open']
        or target['source_candle_index'] != event['source_candle_index']
        or target['registration_sha256'] != protocol_hash()
        or evaluation['start_index_inclusive'] != event['source_candle_index']
        or evaluation['end_index_exclusive'] != event['source_candle_index']+20
        or model['policy'] != protocol['cost_cases'][cost]
        or model['evidence_hashes'] != protocol['inputs']):
        raise ValueError('Prior event/cost/evaluation identity differs')
    if (result['symbol'] != event['symbol'] or result['timeframe'] != 'M5'
        or result['initial_capital'] != 50 or result['risk'] != protocol['risk']
        or result['execution'] != protocol['execution_descriptor']
        or target['dataset_content_hash'] != event['dataset_content_hash']):
        raise ValueError('Prior capital/risk/dataset differs')
    signals = [d for d in result['decisions'] if d['state'] != 'EXECUTION_REJECTED']
    if (len(signals) != 1 or signals[0]['candle_index'] != event['source_candle_index']
        or (signals[0]['signal'], signals[0]['confidence']) != (event['direction'], event['confidence'])):
        raise ValueError('Prior target decision differs')
    label_from_result(result, event)
    if len(result['trades']) > 1:
        raise ValueError('Multiple target fills')
    return digest


def protocol_hash():
    from backtesting.long_history_labels import REGISTRATION_HASH
    return REGISTRATION_HASH


def verify_evidence(evidence):
    for path, digest in evidence['files'].items():
        if file_hash(Path(path)) != ('sha256:'+digest if not digest.startswith('sha256:') else digest):
            raise ValueError('Prior campaign changed during resume')


def load_prior(directories, protocol, events, snapshot, *, transition=None):
    expected = {(e['event_id'], c): e for e in events for c in protocol['cost_cases']}
    records = {}; evidence = {'files': {}, 'interrupted_attempts': [], 'directories': []}
    for directory in directories:
        directory = directory.resolve()
        if str(directory) in evidence['directories']:
            raise ValueError('Duplicate resume directory')
        evidence['directories'].append(str(directory))
        plan_path = directory/'implementation.json'
        plan = json.loads(plan_path.read_text())
        segment_snapshot = snapshot
        transitioned = transition is not None and str(directory)==transition['original_segment']
        if transitioned:
            segment_snapshot=transition['old_source_snapshot']
        if (plan['scope'] != 'FULL_TRAINING_LABELS_NOT_PORTFOLIO_PERFORMANCE'
            or plan['registration_sha256'] != protocol_hash()
            or plan['source_snapshot'] != segment_snapshot
            or set(plan['event_ids']) != {e['event_id'] for e in events}):
            raise ValueError('Prior full campaign source/selection differs; pilot reuse forbidden')
        if is_process_alive(plan['owner_pid']):
            raise ValueError('Prior campaign owner still alive; duplicate dispatch forbidden')
        if plan.get('transition_contract'):
            if transition is None or plan['transition_contract']['sha256'] != transition['_contract_sha256']:
                raise ValueError('Prior segment transition lineage missing or different')
        for name, digest in segment_snapshot['files'].items():
            path = directory/'source-archive'/name
            if file_hash(path) != ('sha256:'+digest if not digest.startswith('sha256:') else digest):
                raise ValueError('Prior source archive differs')
            evidence['files'][str(path)] = digest
        ledger = directory/'trials.jsonl'
        evidence['files'][str(plan_path)] = file_hash(plan_path)
        evidence['files'][str(ledger)] = file_hash(ledger)
        states = {}
        for line in ledger.read_text().splitlines():
            row = json.loads(line)
            key = (row.get('event_id'), row.get('cost'))
            if key not in expected or row['state'] not in ('STARTED', 'COMPLETED'):
                raise ValueError('Failed/unrecognized prior attempt requires review')
            if row['state'] == 'STARTED':
                if key in states or key in records:
                    raise ValueError('Duplicate prior attempt')
                states[key] = 'STARTED'
            else:
                if states.get(key) != 'STARTED' or key in records:
                    raise ValueError('Invalid prior completion transition')
                path = Path(row['artifact_path']).resolve()
                if path.parent != directory or file_hash(path) != row['artifact_sha256']:
                    raise ValueError('Prior artifact path/hash differs')
                from backtesting.long_history_result_store import load_result
                result = load_result(path, evidence['files'])
                if result['run_context']['source_snapshot'] != segment_snapshot:
                    raise ValueError('Prior result source differs')
                digest = verify_result(result, expected[key], key[1], protocol)
                if digest != row['result_hash'] or len(result['trades']) != row['trades']:
                    raise ValueError('Prior completion/result mismatch')
                evidence['files'][str(path)] = row['artifact_sha256']
                records[key] = row; states[key] = 'COMPLETED'
        evidence['interrupted_attempts'].extend({'directory':str(directory), 'event_id':k[0], 'cost':k[1]}
            for k,v in states.items() if v == 'STARTED')
        if transitioned and sum(v=='COMPLETED' for v in states.values())!=transition['inherited_completed']:
            raise ValueError('Transition ancestor completion count differs')
    # Every inherited artifact must be supplied explicitly, with its original segment.
    for directory in directories:
        prior = json.loads((directory/'resume-evidence.json').read_text())
        if not set(prior['directories']).issubset(evidence['directories']):
            raise ValueError('Missing ancestor resume segment')
        verify_evidence(prior)
        evidence['files'][str((directory/'resume-evidence.json').resolve())] = file_hash(directory/'resume-evidence.json')
    verify_evidence(evidence)
    if transition is not None:
        if transition['original_segment'] not in evidence['directories']:
            raise ValueError('Required transition ancestor missing')
        original_interrupted=[r for r in evidence['interrupted_attempts'] if r['directory']==transition['original_segment']]
        if original_interrupted!=transition['interrupted_attempts']:
            raise ValueError('Transition interruption lineage differs')
        evidence['source_transition']={'contract_sha256':transition['_contract_sha256'],
            'original_segment':transition['original_segment'],'old_source_snapshot':transition['old_source_snapshot'],
            'implementation_source_snapshot':snapshot}
    return records, evidence


def label_from_result(result, event):
    from datetime import datetime, timedelta
    signal = datetime.fromisoformat(event['signal_bar_open'])
    trades = result['trades']
    if len(trades) > 1:
        raise ValueError('Multiple fills')
    if trades:
        trade = trades[0]
        exit_time = datetime.fromisoformat(trade['exit_timestamp'])
        if (trade['exit_reason'] == 'END_OF_DATA' or trade['balance_before'] != 50
            or trade['initial_risk_account_currency'] <= 0
            or datetime.fromisoformat(trade['signal_timestamp']) != signal
            or trade['direction'] != event['direction']
            or datetime.fromisoformat(trade['entry_timestamp']) != signal+timedelta(minutes=5)
            or not signal+timedelta(minutes=5) <= exit_time <= signal+timedelta(minutes=95)):
            raise ValueError('Invalid executed label chronology/risk')
        return dict(status='EXECUTED', available_at=(exit_time+timedelta(minutes=5)).isoformat(),
                    return_label=dict(net_modelled_usd=trade['net_pnl'],
                    net_r=trade['net_pnl']/trade['initial_risk_account_currency']), rejection_reasons=[])
    rejects = [d for d in result['decisions'] if d['state'] == 'EXECUTION_REJECTED']
    if (len(rejects) != 1 or rejects[0]['candle_index'] != event['source_candle_index']+1
        or datetime.fromisoformat(rejects[0]['timestamp']) != signal+timedelta(minutes=5)
        or not rejects[0]['reasons']):
        raise ValueError('Invalid null rejection label')
    return dict(status='NON_EXECUTABLE', return_label=None, rejection_reasons=rejects[0]['reasons'],
                available_at=(signal+timedelta(minutes=10)).isoformat())


from contextlib import contextmanager

@contextmanager
def dispatch_lock():
    """OS lock released even on process loss; all full dispatches share one guard."""
    import tempfile
    path = Path(tempfile.gettempdir())/'jqe-long-history-label-dispatch.lock'
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
