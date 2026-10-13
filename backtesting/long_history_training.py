"""Separate frozen longer-history TRAIN dispatch; entirely offline."""
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from unittest.mock import patch

from backtesting.campaign_baseline import write_new, diagnostic_metrics, pooled_summary
from backtesting.economics import FrozenCostPolicy, FrozenMarketModel, contract_from_evidence
from backtesting.label_protocol import file_hash
from backtesting.models import BacktestRiskConfiguration, BacktestExecutionAssumptions
from backtesting.provenance import source_snapshot
from data.dataset import load_dataset_bundle
from data.coverage import require_complete_historical_coverage
from research.session_coverage import load_policy

REGISTRATION_HASH = 'sha256:06be54a572cd52b608755fa643d12f4f39843aa09ce9dcd3212f1597b884bfa4'


def verify_inputs(protocol):
    for name, digest in {**protocol['input_hashes'], **protocol['helper_source_hashes']}.items():
        if file_hash(Path(name)) != digest:
            raise ValueError(f'Frozen input changed: {name}')


def preflight(registration):
    path = registration / 'protocol.json'
    if file_hash(path) != REGISTRATION_HASH or json.loads(path.with_name('protocol.sha256.json').read_text())['sha256'] != REGISTRATION_HASH:
        raise ValueError('Frozen longer-history registration checksum differs')
    protocol = json.loads(path.read_text())
    verify_inputs(protocol)
    root = Path(__file__).resolve().parents[1]
    current = source_snapshot()
    # CLI routing is separately bound; every existing replay dependency must match.
    for name, digest in protocol['source_snapshot']['files'].items():
        if name != 'backtesting/backtest.py' and current['files'].get(name) != digest:
            raise ValueError(f'Frozen replay source changed: {name}')
    if current['dependencies'] != protocol['source_snapshot']['dependencies']:
        raise ValueError('Frozen dependency versions changed')
    acquisition = json.loads((root/'reports/history-acquisition-20261009-04/acquisition.json').read_text())
    terms = json.loads((root/'reports/entry-cost-terms-20261008-01.json').read_text())
    policy, _ = load_policy(root/'reports/session-calendar-20261009-01/policy.json')
    start = datetime.fromisoformat(protocol['window']['source_start_inclusive'])
    end = datetime.fromisoformat(protocol['window']['end_exclusive'])
    prepared = []
    for row in protocol['bundles']:
        symbol = row['symbol']; directory = Path(row['directory'])
        candles, manifest = load_dataset_bundle(directory)
        if manifest.provider != 'weltrade' or manifest.source != 'weltrade' or manifest.provider_symbol != symbol or manifest.canonical_symbol != symbol or manifest.timeframe.value != 'M5':
            raise ValueError('Exact native bundle identity differs')
        if manifest.content_hash != row['content_hash'] or len(candles) != row['bars'] or candles[200].time != datetime.fromisoformat(protocol['window']['evaluation_start_inclusive']):
            raise ValueError('Frozen prefix/warmup differs')
        if any(c.time + timedelta(minutes=5) > manifest.retrieved_at for c in candles):
            raise ValueError('Unclosed candle')
        require_complete_historical_coverage(candles=candles, provider='weltrade',canonical_symbol=symbol,provider_symbol=symbol,timeframe=manifest.timeframe,start=start,end=end-timedelta(minutes=5),research_policy=policy)
        econ = next(r['economics'] for r in acquisition['symbols'] if r['symbol']==symbol)
        term = next(r for r in terms['symbols'] if r['symbol']==symbol)
        if len(econ['profit_probes']) != 8 or any(not all(math.isfinite(p[k]) for k in ('lots','entry','exit','pnl')) for p in econ['profit_probes']):
            raise ValueError('Finite matched profit probes required')
        probes = term['margin_probes']
        if {p['side'] for p in probes} != {'BUY','SELL'} or len({p['lots'] for p in probes}) < 2 or any(not all(math.isfinite(p[k]) and p[k] > 0 for k in ('lots','price','margin')) for p in probes):
            raise ValueError('Finite two-sided multi-size margin probes required')
        contract = contract_from_evidence(symbol,econ,term,server_offset=acquisition['terminal_verification']['server_offset_seconds'])
        sidecar = json.loads((directory/'recorded-spread.json').read_text())
        if sidecar['provider'] != 'weltrade' or sidecar['content_hash'] != manifest.content_hash or sidecar['point'] != term['point'] or len(sidecar['rows']) != len(candles):
            raise ValueError('Spread binding differs')
        if any(datetime.fromisoformat(r['time']) != c.time for r,c in zip(sidecar['rows'],candles)):
            raise ValueError('Spread chronology differs')
        spreads = tuple(r['spread_points'] * sidecar['point'] for r in sidecar['rows'])
        model = FrozenMarketModel(contract,FrozenCostPolicy(0),tuple(c.time for c in candles),spreads,manifest.content_hash,tuple(protocol['input_hashes'].items()))
        model.validate_dataset(candles,symbol,'weltrade')
        prepared.append((symbol,candles,manifest,model))
    verify_inputs(protocol)
    return protocol, prepared


async def dispatch(registration, output, runner, *, preflight_only=False):
    output.mkdir(parents=True,exist_ok=False)
    snapshot = source_snapshot()
    def ledger(event):
        with (output/'trials.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(event,default=str,allow_nan=False)+'\n')
    def deny(*args,**kwargs):
        raise RuntimeError('SDK access forbidden during longer-history research')
    try:
        with patch.multiple('MetaTrader5',initialize=deny,login=deny,shutdown=deny,order_send=deny,copy_rates_from_pos=deny,copy_rates_range=deny,order_calc_profit=deny,order_calc_margin=deny):
            protocol, prepared = preflight(registration)
            write_new(output/'implementation.json',{'registration_sha256':REGISTRATION_HASH,'source_snapshot':snapshot,'limitations':protocol['limitations']})
            write_new(output/'preflight.json',{'status':'PASS_CONDITIONAL_SNAPSHOT_COMPATIBILITY','symbols':[{'symbol':s,'contract':asdict(m.contract),'profit_probes':8} for s,_,_,m in prepared],'outcomes':0})
            if preflight_only:
                return
            records=[]
            for symbol,candles,manifest,base in prepared:
                for name,cost in protocol['cost_cases'].items():
                    verify_inputs(protocol)
                    if source_snapshot()!=snapshot: raise ValueError('Implementation source drift')
                    event={'symbol':symbol,'cost':name,'state':'STARTED'};ledger(event)
                    model=FrozenMarketModel(base.contract,FrozenCostPolicy(**cost),base.timestamps,base.spread_prices,base.dataset_content_hash,base.evidence_hashes)
                    engine=await runner(symbol=symbol,timeframe=manifest.timeframe,dataset=candles,manifest=manifest,provider='weltrade',starting_balance=50,market_model=model,start_index=200,end_index=len(candles),risk_configuration=BacktestRiskConfiguration(**protocol['risk']),execution_assumptions=BacktestExecutionAssumptions(**protocol['execution_descriptor']))
                    verify_inputs(protocol)
                    if source_snapshot()!=snapshot: raise ValueError('Implementation source drift')
                    record={'symbol':symbol,'cost':name,'metrics':diagnostic_metrics(engine,candles,200,len(candles))}
                    stem=symbol.replace(' ','_')+'--'+name
                    with (output/(stem+'--result.json')).open('xb') as stream:stream.write(engine.result.to_json_bytes())
                    write_new(output/(stem+'--metrics.json'),record);records.append(record)
                    ledger({**event,'state':'COMPLETED','result_hash':engine.result.result_hash})
            start=datetime.fromisoformat(protocol['window']['evaluation_start_inclusive']);end=datetime.fromisoformat(protocol['window']['end_exclusive'])
            write_new(output/'summary.json',{'status':'TRAIN_COMPLETE_PROMOTION_BLOCKED','replays':len(records),'limitations':protocol['limitations'],'aggregates':{name:pooled_summary([r for r in records if r['cost']==name],start,end) for name in protocol['cost_cases']}})
    except Exception as exc:
        ledger({'state':'FAILED','error_type':type(exc).__name__,'reason':str(exc)})
        raise
