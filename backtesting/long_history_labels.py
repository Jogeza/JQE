"""Separate immutable longer-history target contract and offline pilot dispatcher."""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
from unittest.mock import patch

from backtesting.economics import FrozenCostPolicy, FrozenMarketModel, contract_from_evidence
from backtesting.label_protocol import file_hash, write_new
from backtesting.models import BacktestRiskConfiguration, BacktestExecutionAssumptions
from backtesting.provenance import source_snapshot
from core.exceptions import MarketDataError
from broker.types import Timeframe
from data.dataset import load_dataset_bundle, candle_content_hash

REGISTRATION_HASH = 'sha256:754e420b1b5c18d8b384584643e3242a1fd364e2146529b52c90339fb6b3f9a8'
SYMBOLS = tuple(f'{kind} Vol {number}' for kind in ('FX', 'SFX') for number in (20, 40, 60, 80, 99))


@dataclass(frozen=True)
class LongHistoryOpportunity:
    registration_sha256: str
    event_id: str
    symbol: str
    dataset_content_hash: str
    source_candle_index: int
    signal_bar_open: str
    direction: str
    confidence: int

    def validate(self, *, symbol, provider, timeframe, candles, model, capital, start, end, risk, execution):
        if (self.registration_sha256 != REGISTRATION_HASH or self.symbol not in SYMBOLS
            or symbol != self.symbol or provider != 'weltrade' or timeframe != Timeframe.M5
            or model is None or capital != 50 or risk != BacktestRiskConfiguration()
            or execution != BacktestExecutionAssumptions() or type(start) is not int
            or start != self.source_candle_index or start < 200 or end != start + 20
            or end > len(candles) or self.direction not in ('BUY', 'SELL')
            or type(self.confidence) is not int or not 0 <= self.confidence <= 100
            or not self.event_id.startswith('sha256:')
            or self.dataset_content_hash != candle_content_hash(candles)
            or model.dataset_content_hash != self.dataset_content_hash):
            raise MarketDataError('Incomplete frozen longer-history target contract')
        if (candles[0].time != datetime.fromisoformat('2026-07-10T00:00:00+00:00')
            or candles[start].time != datetime.fromisoformat(self.signal_bar_open)
            or candles[end-1].time + timedelta(minutes=5) > datetime.fromisoformat('2026-10-08T00:00:00+00:00')):
            raise MarketDataError('Longer-history prefix or training boundary differs')
        from backtesting.models import _sha256
        from backtesting.long_history_training import REGISTRATION_HASH as parent_hash
        identity = dict(parent_registration_sha256=parent_hash, dataset_content_hash=self.dataset_content_hash,
                        provider='weltrade', symbol=self.symbol, timeframe='M5', source_candle_index=start,
                        signal_bar_open=self.signal_bar_open, direction=self.direction)
        if self.event_id != _sha256(identity):
            raise MarketDataError('Frozen event identity differs')
        if ((model.policy.commission_per_lot_per_side, model.policy.spread_multiplier) not in ((0,1),(3,1),(6,2))
            or model.policy.slippage_atr_fraction_per_fill != 0.05):
            raise MarketDataError('Unregistered longer-history costs')
        times = [c.time for c in candles[start-3:end]]
        if any(b-a != timedelta(minutes=5) for a,b in zip(times,times[1:])):
            raise MarketDataError('Longer-history target crosses a gap')


def verify_inputs(protocol):
    for name, digest in protocol['inputs'].items():
        if file_hash(Path(name)) != digest:
            raise ValueError(f'Frozen label input changed: {name}')


def load_registration(registration):
    if file_hash(registration/'protocol.json') != REGISTRATION_HASH:
        raise ValueError('Frozen longer-history label checksum differs')
    protocol = json.loads((registration/'protocol.json').read_text())
    verify_inputs(protocol)
    if file_hash(registration/'events.json') != protocol['events_sha256']:
        raise ValueError('Frozen longer-history events changed')
    events = json.loads((registration/'events.json').read_text())
    return protocol, events


async def _dispatch(registration, output, runner, *, full_campaign=False, resume_from=(), transition_path=None):
    """Fixed pilot or all registered eligible events; immutable output per segment."""
    output.mkdir(parents=True, exist_ok=False)
    def ledger(row):
        with (output/'trials.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, allow_nan=False)+'\n')
            stream.flush(); os.fsync(stream.fileno())
    def deny(*args, **kwargs):
        raise RuntimeError('Terminal access forbidden in longer-history label pilot')
    snapshot = source_snapshot()
    transition=None; transition_files={}
    if transition_path is not None:
        if not full_campaign or not resume_from:
            raise ValueError('Transition requires full NEW-segment resume')
        from backtesting.long_history_lineage import load_transition
        transition,transition_files=load_transition(transition_path,snapshot)
        transition['_contract_sha256']=file_hash(transition_path)
    try:
        with patch.multiple('MetaTrader5', initialize=deny, login=deny, shutdown=deny,
                            order_send=deny, symbol_select=deny, copy_rates_from_pos=deny,
                            copy_rates_range=deny, order_calc_profit=deny, order_calc_margin=deny):
            protocol, events = load_registration(registration)
            old = protocol['source']['training_implementation_snapshot']
            changes = sorted(k for k in set(old['files']) | set(snapshot['files'])
                             if old['files'].get(k) != snapshot['files'].get(k))
            if old['dependencies'] != snapshot['dependencies']:
                raise ValueError('Frozen dependencies changed')
            for name in old['files']:
                if name.startswith(('strategy/', 'risk/', 'intelligence/', 'analytics/')) or name in (
                    'core/indicators.py', 'core/regime.py', 'backtesting/engine.py',
                    'backtesting/economics.py', 'backtesting/models.py', 'execution/simulator.py'):
                    if name in changes and not (transition is not None and name=='backtesting/models.py'):
                        raise ValueError(f'Canonical arithmetic/signal dependency changed: {name}')
            selected = [e for symbol in SYMBOLS for e in sorted(
                (e for e in events if e['symbol']==symbol and e['status']=='ELIGIBLE_UNLABELLED'),
                key=lambda e:e['source_candle_index'])[:None if full_campaign else 3]]
            if not full_campaign and len(selected) != 30:
                raise ValueError('Incomplete all-symbol pilot selection')
            from backtesting.long_history_label_resume import load_prior, archive_source
            prior, evidence = load_prior(resume_from, protocol, selected, snapshot, transition=transition)
            evidence['files'].update(transition_files)
            archive_source(output, snapshot)
            write_new(output/'resume-evidence.json', evidence)
            if full_campaign:
                write_new(output/'censored-events.json', [e for e in events if e['status'] != 'ELIGIBLE_UNLABELLED'])
            write_new(output/'implementation.json', {'registration_sha256':REGISTRATION_HASH,'owner_pid':os.getpid(),
                'source_snapshot':snapshot, 'source_files_changed_from_training':changes,
                'selection':'ALL_ELIGIBLE' if full_campaign else 'First three eligible events per symbol, all three costs; fixed before outcomes',
                'event_ids':[e['event_id'] for e in selected], 'attempts_planned':len(selected)*len(protocol['cost_cases']),
                'new_attempts_planned':len(selected)*len(protocol['cost_cases'])-len(prior),
                'scope':'FULL_TRAINING_LABELS_NOT_PORTFOLIO_PERFORMANCE' if full_campaign else 'IMPLEMENTATION_PILOT_NOT_PORTFOLIO_PERFORMANCE', 'ml_fits':0,
                'transition_contract':{'path':str(transition_path.resolve()),'sha256':transition['_contract_sha256']} if transition else None})
            acquisition_path = next(Path(p) for p in protocol['inputs'] if p.endswith('acquisition.json'))
            acquisition = json.loads(acquisition_path.read_text())
            terms = json.loads(next(Path(p) for p in protocol['inputs'] if 'entry-cost-terms' in p).read_text())
            records=list(prior.values())
            for symbol in SYMBOLS:
                directory=acquisition_path.parent/'bundles'/(symbol.replace(' ','_')+'_M5')
                candles, manifest = load_dataset_bundle(directory)
                spreads=json.loads((directory/'recorded-spread.json').read_text())
                term=next(t for t in terms['symbols'] if t['symbol']==symbol)
                econ=next(t['economics'] for t in acquisition['symbols'] if t['symbol']==symbol)
                contract=contract_from_evidence(symbol,econ,term,server_offset=acquisition['terminal_verification']['server_offset_seconds'])
                if (manifest.provider != 'weltrade' or manifest.provider_symbol != symbol
                    or manifest.canonical_symbol != symbol or manifest.timeframe != Timeframe.M5
                    or spreads['content_hash'] != manifest.content_hash or spreads['point'] != term['point']
                    or len(spreads['rows']) != len(candles)
                    or any(datetime.fromisoformat(r['time']) != c.time for r,c in zip(spreads['rows'],candles))):
                    raise ValueError('Native dataset/spread identity differs')
                baseline=json.loads(next(Path(p) for p in protocol['inputs'] if p.endswith(
                    symbol.replace(' ','_')+'--optimistic_zero_commission--result.json')).read_text())
                for event in (e for e in selected if e['symbol']==symbol):
                    i=event['source_candle_index']
                    target=LongHistoryOpportunity(REGISTRATION_HASH,event['event_id'],symbol,
                        manifest.content_hash,i,event['signal_bar_open'],event['direction'],event['confidence'])
                    for cost, policy in protocol['cost_cases'].items():
                        row={'event_id':event['event_id'],'symbol':symbol,'cost':cost}
                        if (event['event_id'],cost) in prior:
                            continue
                        if source_snapshot()!=snapshot:
                            raise ValueError('Source drift before label attempt')
                        ledger({**row,'state':'STARTED'})
                        model=FrozenMarketModel(contract,FrozenCostPolicy(**policy),tuple(c.time for c in candles),
                            tuple(r['spread_points']*spreads['point'] for r in spreads['rows']),
                            manifest.content_hash,tuple(protocol['inputs'].items()))
                        engine=await runner(symbol=symbol,timeframe=Timeframe.M5,provider='weltrade',
                            dataset=candles,manifest=manifest,starting_balance=50,market_model=model,
                            start_index=i,end_index=i+20,long_history_opportunity=target)
                        result=engine.result.to_dict()
                        # Compare the full original causal indicator prefix, not just the target values.
                        if len(result['indicators'][:i+1]) != i+1 or len(baseline['indicators'][:i+1]) != i+1:
                            raise ValueError('Incomplete indicator prefix')
                        for current, original in zip(result['indicators'][:i+1],baseline['indicators'][:i+1]):
                            for key in ('candle_index','timestamp','ema50','ema200','rsi','atr'):
                                if current[key] != original[key]:
                                    raise ValueError('Original canonical indicator prefix differs')
                        from backtesting.long_history_label_resume import save_result, verify_result, label_from_result
                        if full_campaign:
                            verify_result(result,event,cost,protocol)
                        path=save_result(output,event['event_id'],cost,result) if full_campaign else output/(str(len(records)+1).zfill(3)+'--result.json')
                        if not full_campaign:
                            write_new(path,result)
                        record={**row,'state':'COMPLETED','result_hash':result['result_hash'],
                            'trades':len(engine.trades),'indicator_prefix_equivalence':'PASS',
                            'artifact_path':str(path.resolve()),'artifact_sha256':file_hash(path)}
                        if full_campaign:
                            record.update(label_from_result(result,event))
                        records.append(record);ledger(record)
                        if full_campaign and len(records)%25==0:
                            print(f'Completed {len(records)}/{len(selected)*len(protocol["cost_cases"])} attempts',flush=True)
            verify_inputs(protocol)
            from backtesting.long_history_label_resume import verify_evidence
            verify_evidence(evidence)
            if source_snapshot()!=snapshot:
                raise ValueError('Implementation source drift during pilot')
            write_new(output/'summary.json',{'status':'FULL_LABEL_DISPATCH_COMPLETE_AUDIT_REQUIRED_NOT_ML_READY' if full_campaign else 'PILOT_COMPLETE_FULL_CAMPAIGN_NOT_STARTED',
                'attempts':len(records),'records':records,'ml_fits':0,
                'limitations':'Independent inspected training labels; conditional costs/calendar. Fill equivalence qualification remains separate.'})
    except Exception as exc:
        ledger({'state':'FAILED','error_type':type(exc).__name__,'reason':str(exc)})
        raise


async def pilot(registration, output, runner, *, full_campaign=False, resume_from=(), transition_path=None):
    if full_campaign:
        from backtesting.long_history_label_resume import dispatch_lock
        with dispatch_lock():
            return await _dispatch(registration, output, runner, full_campaign=True, resume_from=resume_from,transition_path=transition_path)
    if resume_from or transition_path:
        raise ValueError('Pilot cannot resume full labels')
    return await _dispatch(registration, output, runner)
