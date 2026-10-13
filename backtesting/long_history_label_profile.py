"""One fixed canonical replay profile; inspected TRAIN, not a new strategy trial."""
import copy
import cProfile
import io
import json
from pathlib import Path
import pstats
import time
from unittest.mock import patch

from backtesting.label_protocol import write_new, file_hash
from backtesting.long_history_labels import load_registration, LongHistoryOpportunity, REGISTRATION_HASH
from backtesting.economics import contract_from_evidence, FrozenMarketModel, FrozenCostPolicy
from backtesting.models import backtest_run_fingerprint, BacktestRiskConfiguration, BacktestExecutionAssumptions
from backtesting.provenance import source_snapshot
from broker.types import Timeframe
from data.dataset import load_dataset_bundle


def fingerprint(payload):
    return backtest_run_fingerprint(
        dataset_hash=payload['dataset_hash'], symbol=payload['symbol'],timeframe=Timeframe.M5,
        initial_capital=payload['initial_capital'], strategy=payload['strategy'],
        risk=BacktestRiskConfiguration(**payload['risk']),
        execution=BacktestExecutionAssumptions(**payload['execution']),
        engine_version=payload['engine_version'], run_context=payload['run_context'])


def equivalent_payload(actual, original):
    """Only disclosed source identity/fingerprint can differ, never observations."""
    from backtesting.long_history_result_store import verify_preimage
    verify_preimage(actual)
    verify_preimage(original)
    if actual['run_fingerprint'] != fingerprint(actual) or original['run_fingerprint'] != fingerprint(original):
        return False
    adjusted = copy.deepcopy(actual)
    adjusted['run_context']['source_snapshot'] = original['run_context']['source_snapshot']
    adjusted['run_fingerprint'] = fingerprint(adjusted)
    adjusted.pop('result_hash')
    expected = dict(original)
    expected.pop('result_hash')
    return adjusted == expected


async def profile_attempt(registration, output, runner, *, golden_path=None):
    output.mkdir(parents=True,exist_ok=False)
    from core.logger import logger
    logger.remove()
    logger.add(output/'backtest.log',level='WARNING')
    protocol,events=load_registration(registration)
    event=min((e for e in events if e['symbol']=='SFX Vol 99' and e['status']=='ELIGIBLE_UNLABELLED'),
              key=lambda e:e['source_candle_index'])
    cost='optimistic_zero_commission'
    if golden_path is not None:
        golden=json.loads(golden_path.read_text())
        identity=golden['run_context']['long_history_opportunity']
        event=next(e for e in events if e['event_id']==identity['event_id'] and e['status']=='ELIGIBLE_UNLABELLED')
        cost=next(c for c,p in protocol['cost_cases'].items() if p==golden['run_context']['frozen_market_model']['policy'])
    snapshot=source_snapshot()
    write_new(output/'selection.json',dict(scope='ONE_INSPECTED_TRAIN_REPLAY_PROFILE_NOT_STRATEGY_SELECTION',
        event=event,cost=cost,attempt_budget=1,source_snapshot=snapshot,ml_fits=0))
    acquisition_path=next(Path(p) for p in protocol['inputs'] if p.endswith('acquisition.json'))
    acquisition=json.loads(acquisition_path.read_text())
    terms=json.loads(next(Path(p) for p in protocol['inputs'] if 'entry-cost-terms' in p).read_text())
    symbol=event['symbol']
    directory=acquisition_path.parent/'bundles'/(symbol.replace(' ','_')+'_M5')
    candles,manifest=load_dataset_bundle(directory)
    spreads=json.loads((directory/'recorded-spread.json').read_text())
    term=next(t for t in terms['symbols'] if t['symbol']==symbol)
    economics=next(t['economics'] for t in acquisition['symbols'] if t['symbol']==symbol)
    contract=contract_from_evidence(symbol,economics,term,
        server_offset=acquisition['terminal_verification']['server_offset_seconds'])
    model=FrozenMarketModel(contract,FrozenCostPolicy(**protocol['cost_cases'][cost]),
        tuple(c.time for c in candles),tuple(r['spread_points']*spreads['point'] for r in spreads['rows']),
        manifest.content_hash,tuple(protocol['inputs'].items()))
    target=LongHistoryOpportunity(REGISTRATION_HASH,event['event_id'],symbol,manifest.content_hash,
        event['source_candle_index'],event['signal_bar_open'],event['direction'],event['confidence'])
    def deny(*a,**k):raise RuntimeError('Terminal calls forbidden during replay profile')
    profiler=cProfile.Profile()
    started=time.perf_counter()
    with patch.multiple('MetaTrader5',initialize=deny,login=deny,shutdown=deny,order_send=deny,
        symbol_select=deny,copy_rates_from_pos=deny,copy_rates_range=deny,order_calc_profit=deny,order_calc_margin=deny):
        profiler.enable()
        engine=await runner(symbol=symbol,timeframe=Timeframe.M5,provider='weltrade',
            dataset=candles,manifest=manifest,starting_balance=50,market_model=model,
            start_index=event['source_candle_index'],end_index=event['source_candle_index']+20,
            long_history_opportunity=target)
        result=engine.result.to_dict()
        profiler.disable()
    elapsed=time.perf_counter()-started
    profiler.dump_stats(output/'replay.prof')
    stream=io.StringIO()
    pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(35)
    with (output/'profile.txt').open('x') as handle:handle.write(stream.getvalue())
    write_new(output/'result.json',result)
    root=Path(__file__).resolve().parents[1]
    pilot=root/'reports/long-history-label-pilot-20261009-01'
    audit=json.loads((root/'reports/long-history-label-pilot-audit-20261009-01/audit.json').read_text())
    matched=None
    for path in sorted(pilot.glob('*--result.json')):
        if golden_path is not None and path.resolve()!=golden_path.resolve():
            continue
        original=json.loads(path.read_text())
        target_old=original['run_context']['long_history_opportunity']
        if target_old['event_id']==event['event_id'] and original['run_context']['frozen_market_model']['policy']==protocol['cost_cases'][cost]:
            assert file_hash(path)==audit['file_hashes'][str(path)]
            assert equivalent_payload(result,original),'Canonical replay differs beyond disclosed source identity'
            matched=str(path)
            break
    assert matched is not None,'Matching preserved golden pilot result absent'
    assert source_snapshot()==snapshot,'Source changed during profile'
    from backtesting.long_history_labels import verify_inputs
    verify_inputs(protocol)
    write_new(output/'summary.json',dict(status='PROFILE_COMPLETE_GOLDEN_PAYLOAD_MATCH_EXCEPT_SOURCE_IDENTITY',
        profile_seconds=elapsed,profile_includes='canonical runner and complete result serialization; excludes dataset load/storage',
        event_id=event['event_id'],cost=cost,executed_trades=len(result['trades']),golden=matched,
        new_diagnostic_replays=1,parameter_configurations_changed=0,ml_fits=0,
        limitations='One inspected TRAIN target; profiler overhead; not throughput estimate or general acceleration qualification'))


async def qualify_transition_replays(registration, output, runner):
    """Fixed saved-pilot executed examples plus first null; no outcome tuning."""
    from backtesting.long_history_label_resume import archive_source, verify_evidence
    output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[1]
    pilot=root/'reports/long-history-label-pilot-20261009-01'
    audit_path=root/'reports/long-history-label-pilot-audit-20261009-01/audit.json'
    audit=json.loads(audit_path.read_text())
    assert audit['errors']==0 and audit['attempts']==90
    selected=[]; null_added=False
    for path in sorted(pilot.glob('*--result.json')):
        original=json.loads(path.read_text())
        assert file_hash(path)==audit['file_hashes'][str(path)]
        if original['trades'] or not null_added:
            selected.append(path)
            if not original['trades']:null_added=True
    assert len(selected)==3,'Expected exactly two executed golden examples and one null'
    snapshot=source_snapshot()
    archive_source(output,snapshot)
    write_new(output/'selection.json',dict(scope='FIXED_EXECUTED_NULL_IMPLEMENTATION_EQUIVALENCE_NOT_STRATEGY_TRIAL',
        selected=[str(p) for p in selected],attempt_budget=3,source_snapshot=snapshot,
        golden_input_hashes={str(p):file_hash(p) for p in selected},ml_fits=0))
    summaries=[]
    for i,path in enumerate(selected):
        directory=output/str(i+1).zfill(2)
        await profile_attempt(registration,directory,runner,golden_path=path)
        summaries.append(json.loads((directory/'summary.json').read_text()))
    verify_evidence({'files':audit['file_hashes']})
    assert source_snapshot()==snapshot
    write_new(output/'audit.json',dict(status='PASS_FIXED_EXECUTED_NULL_CANONICAL_EQUIVALENCE_NOT_RESUME_AUTHORIZATION',
        errors=0,attempts=3,executed=sum(s['executed_trades'] for s in summaries),
        null=sum(s['executed_trades']==0 for s in summaries),records=summaries,
        source_snapshot=snapshot,new_diagnostic_replays=3,ml_fits=0,
        limitation='Inspected pilot examples only; exact source transition and inherited53 audit still required'))
