"""Offline full-dispatch saved coverage audit; no replay or terminal access."""
import json
from pathlib import Path
from backtesting.label_protocol import write_new
from backtesting.long_history_labels import load_registration
from backtesting.long_history_label_resume import load_prior, label_from_result, verify_evidence


def verify_final_summary(directory, records):
    """Coverage alone cannot establish clean dispatch completion."""
    summary = json.loads((directory/'summary.json').read_text())
    saved = summary.get('records', [])
    keyed = {(r['event_id'], r['cost']): r for r in saved}
    if (summary.get('status') != 'FULL_LABEL_DISPATCH_COMPLETE_AUDIT_REQUIRED_NOT_ML_READY'
        or summary.get('ml_fits') != 0 or summary.get('attempts') != len(records)
        or len(keyed) != len(saved) or keyed != records):
        raise ValueError('Final summary does not match complete saved coverage')


def audit(registration, directories, output, *, transition_path=None):
    output.mkdir(parents=True, exist_ok=False)
    protocol, events = load_registration(registration)
    selected = [e for e in events if e['status'] == 'ELIGIBLE_UNLABELLED']
    if not directories:
        raise ValueError('Audit requires every campaign segment')
    snapshot = json.loads((directories[-1]/'implementation.json').read_text())['source_snapshot']
    transition=None; transition_files={}
    if transition_path is not None:
        from backtesting.long_history_lineage import load_transition
        from backtesting.label_protocol import file_hash
        transition,transition_files=load_transition(transition_path,snapshot)
        transition['_contract_sha256']=file_hash(transition_path)
    records, evidence = load_prior(directories, protocol, selected, snapshot,transition=transition)
    evidence['files'].update(transition_files)
    expected = {(e['event_id'], c) for e in selected for c in protocol['cost_cases']}
    if set(records) != expected:
        raise ValueError('Incomplete label coverage')
    verify_final_summary(directories[-1], records)
    censors = [e for e in events if e['status'] != 'ELIGIBLE_UNLABELLED']
    for directory in directories:
        if json.loads((directory/'censored-events.json').read_text()) != censors:
            raise ValueError('Censor coverage differs')
    event_map = {e['event_id']:e for e in selected}
    baseline = {}; labels = []
    for key, row in records.items():
        event = event_map[key[0]]
        from backtesting.long_history_result_store import load_result
        result = load_result(row['artifact_path'], evidence['files'])
        symbol = event['symbol']
        if symbol not in baseline:
            baseline.clear()
            name = symbol.replace(' ', '_')+'--optimistic_zero_commission--result.json'
            baseline[symbol] = json.loads(next(Path(p) for p in protocol['inputs'] if p.endswith(name)).read_text())
        original = baseline[symbol]
        i = event['source_candle_index']
        if len(result['indicators']) < i+1:
            raise ValueError('Incomplete original prefix')
        for actual, old in zip(result['indicators'][:i+1], original['indicators'][:i+1]):
            for field in ('candle_index','timestamp','ema50','ema200','rsi','atr'):
                if actual[field] != old[field]:
                    raise ValueError('Original arithmetic prefix differs')
        if result['indicators'][i]['regime'] != original['indicators'][i]['regime']:
            raise ValueError('Target regime differs')
        for field in ('contract','model_version','spread_input_hash','fill_policy','risk_policy','rollover_policy','signal_spread_policy'):
            if result['run_context']['frozen_market_model'][field] != original['run_context']['frozen_market_model'][field]:
                raise ValueError('Baseline frozen economics identity differs')
        label = label_from_result(result,event)
        if any(row.get(k) != v for k,v in label.items()):
            raise ValueError('Ledger label differs from full result')
        labels.append(dict(event_id=key[0],cost=key[1],**label))
    verify_evidence(evidence)
    from backtesting.long_history_labels import verify_inputs
    verify_inputs(protocol)
    write_new(output/'audit.json', dict(status='PASS_COMPLETE_SAVED_LABEL_COVERAGE_NOT_ML_READY',
        errors=0, attempts=len(records), censored_events=len(censors),
        censored_cost_dispositions=len(censors)*len(protocol['cost_cases']), labels=labels,
        evidence=evidence, ml_fits=0, holdouts_read=False))
