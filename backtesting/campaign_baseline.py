"""Training diagnostics only, dispatched by the canonical backtest CLI."""
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from backtesting.economics import FrozenCostPolicy, FrozenMarketModel, contract_from_evidence
from backtesting.entry_quality import summarize
from backtesting.models import BacktestExecutionAssumptions
from backtesting.provenance import source_snapshot
from data.dataset import build_dataset_manifest, load_dataset_bundle, candle_content_hash
from research.campaign_provenance import canonical_json, sha256_file, sha256_text


def write_new(path: Path, payload):
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2, default=str, allow_nan=False) + "\n")


def diagnostic_metrics(engine, candles, start, end):
    metrics = summarize(engine, candles, start, end)
    metrics["claim_scope"] = "TRAIN_ONLY_CONDITIONAL_MODELLED_USD_NOT_VERIFIED_ACCOUNT_RESULTS"
    metrics["expectancy_modelled_usd"] = metrics.pop("expectancy_simulation_cash")
    metrics["average_win_modelled_usd"] = metrics.pop("average_win_simulation_cash")
    metrics["average_loss_modelled_usd"] = metrics.pop("average_loss_simulation_cash")
    metrics["max_bar_close_drawdown_modelled_usd"] = metrics.pop("max_realized_drawdown_simulation_cash")
    metrics["drawdown_basis"] = engine.result.drawdown_basis
    metrics["net_modelled_usd"] = engine.result.absolute_pnl
    metrics["commission_modelled_usd"] = sum(t.commission_costs or 0 for t in engine.trades)
    metrics["financing_modelled_usd"] = sum(t.financing_costs or 0 for t in engine.trades)
    metrics["rejection_reasons"] = dict(Counter(reason for d in engine.decisions if d.state == "EXECUTION_REJECTED" for reason in d.reasons))
    metrics["exit_reasons"] = dict(Counter(t.exit_reason.value for t in engine.trades))
    holding = [(t.exit_timestamp + timedelta(minutes=5)-t.entry_timestamp).total_seconds()/60 for t in engine.trades]
    metrics["holding_minutes_upper_bound_p10_p50_p90"] = list(map(float,np.quantile(holding,[.1,.5,.9]))) if holding else None
    duration = (candles[end-1].time+timedelta(minutes=5)-candles[start].time).total_seconds()
    metrics["exposure_wall_time_upper_bound_fraction"] = sum(holding)*60/duration
    equity = np.array([engine.starting_balance, *(o.equity for o in engine.equity_observations)])
    positive = equity[:-1] > 0
    returns = np.diff(equity)[positive] / equity[:-1][positive]
    sd = returns.std(ddof=1) if len(returns)>1 else 0
    downside = np.sqrt(np.mean(np.minimum(returns,0)**2)) if len(returns) else 0
    metrics["sharpe_bar_returns_unannualized"] = float(returns.mean()/sd) if sd>0 else None
    metrics["sortino_bar_returns_unannualized"] = float(returns.mean()/downside) if downside>0 else None
    metrics["bar_return_periods"] = len(returns)
    return metrics


def pooled_summary(records, start: datetime, end: datetime):
    rows = [t for r in records for t in r["metrics"]["trade_details"]]
    net = [r["net_pnl"] for r in rows]
    rs = [r["net_r"] for r in rows]
    wins, losses = [p for p in net if p>0], [p for p in net if p<0]
    n_days = (end.date()-start.date()).days
    totals, counts = np.zeros(n_days), np.zeros(n_days)
    for row in rows:
        day = (row["exit_timestamp"].date()-start.date()).days
        totals[day] += row["net_r"]
        counts[day] += 1
    ci = None
    if len(rows)>1:
        rng = np.random.default_rng(20261008)
        draws = (rng.integers(0,n_days,size=(10000,(n_days+2)//3,1))+np.arange(3)) % n_days
        draws = draws.reshape(10000,-1)[:,:n_days]
        denominator = counts[draws].sum(axis=1)
        valid = denominator > 0
        means = totals[draws].sum(axis=1)[valid]/denominator[valid]
        ci = list(map(float,np.quantile(means,[.025,.975]))) if len(means) else None
    return {"trades": len(rows), "expectancy_modelled_usd": float(np.mean(net)) if net else None,
        "expectancy_r": float(np.mean(rs)) if rs else None, "expectancy_r_ci95_3day_block_train_only": ci,
        "profit_factor": sum(wins)/abs(sum(losses)) if losses else None,
        "profit_factor_status": "DEFINED" if losses else "UNDEFINED_NO_LOSSES",
        "win_rate_percent": 100*len(wins)/len(rows) if rows else None,
        "average_win_modelled_usd": float(np.mean(wins)) if wins else None,
        "average_loss_modelled_usd": float(np.mean(losses)) if losses else None,
        "net_modelled_usd_sum_independent_accounts": sum(net),
        "equal_weight_symbol_expectancy_r": float(np.mean([r["metrics"]["expectancy_r"] for r in records if r["metrics"]["expectancy_r"] is not None])) if rows else None,
        "zero_trade_symbols": [r["symbol"] for r in records if r["metrics"]["trades"] == 0],
        "portfolio_metrics": "NOT_COMPUTED; ten independent 50-USD research accounts, not shared portfolio capital"}


async def training_baseline(campaign: Path, terms_path: Path, output: Path, runner):
    output.mkdir(parents=True, exist_ok=False)
    from core.logger import logger
    logger.remove()
    logger.add(output/"backtest.log", level="WARNING")
    protocol = json.loads((campaign/"protocol.json").read_text())
    digest = json.loads((campaign/"protocol.sha256.json").read_text())["sha256"]
    if digest != sha256_text(canonical_json(protocol)) or protocol["baseline"] != "jqe-canonical-strategy-v2":
        raise ValueError("Frozen protocol identity/baseline mismatch")
    start, end = (datetime.fromisoformat(protocol["windows"]["train"][key]) for key in ("start_inclusive","end_exclusive"))
    acquisition = json.loads((campaign/"acquisition.json").read_text())
    terms = json.loads(terms_path.read_text())
    if acquisition["status"] != "ACQUIRED_NEEDS_COST_MODEL_AND_FUTURE_HOLDOUT" or terms["account_currency"] != "USD":
        raise ValueError("Complete qualified acquisition and USD snapshot required")
    snapshots = source_snapshot()
    costs = {"optimistic_zero_commission": FrozenCostPolicy(0),
             "assumed_3usd_per_lot_per_side": FrozenCostPolicy(3),
             "double_spread_commission": FrozenCostPolicy(6,spread_multiplier=2)}
    replay_protocol = {"parent_registration_sha256": digest, "partition": "TRAIN_DIAGNOSTIC_ONLY", "windows": protocol["windows"],
        "initial_capital_per_independent_symbol": 50.0, "risk_percent": 1.0,
        "strategy_configurations": 1, "candidate_configurations": 0, "cost_configurations": 3, "planned_replays": 30,
        "costs": {name: asdict(policy) for name,policy in costs.items()}, "source_snapshot": snapshots,
        "generic_execution": asdict(BacktestExecutionAssumptions()),
        "signal_inputs": "Canonical v2 unchanged including unknown spread fallback; frozen spreads affect fills only",
        "promotion": "BLOCKED: exact fee tariff, historical terms and rollover calendar not verified; future partitions unavailable",
        "sources": {"account_overview": "https://help.weltrade.com/en/articles/13434918-trading-account-types-overview-cent-micro-pro-syntx-and-raw-spread",
                    "swap": "https://help.weltrade.com/en/articles/14485261-swap-in-trading-what-it-is-and-how-it-works-on-weltrade"}}
    write_new(output/"training-replay-protocol.json", replay_protocol)
    evidence_hashes = tuple((name,sha256_file(path)) for name,path in (
        ("acquisition",campaign/"acquisition.json"),("additional_terms",terms_path),("registration",campaign/"protocol.json")))
    results = []
    def ledger(event):
        with (output/"trials.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(event,sort_keys=True,default=str)+"\n")
    def deny_sdk(*args, **kwargs):
        raise RuntimeError("Terminal/SDK access forbidden inside canonical research replay")
    with patch.multiple("MetaTrader5", initialize=deny_sdk,login=deny_sdk,shutdown=deny_sdk,order_send=deny_sdk,
        copy_rates_from_pos=deny_sdk,copy_rates_range=deny_sdk,order_calc_profit=deny_sdk,order_calc_margin=deny_sdk):
        for symbol in protocol["symbols"]:
            directory = campaign/"bundles"/(symbol.replace(" ","_")+"_M5")
            all_candles, parent = load_dataset_bundle(directory)
            if parent.provider != "weltrade" or parent.provider_symbol != symbol or parent.canonical_symbol != symbol or parent.timeframe.value != "M5":
                raise ValueError("Provider/exact symbol/timeframe mismatch")
            if any(c.time+timedelta(minutes=5)>parent.retrieved_at for c in all_candles):
                raise ValueError("Closed-bar provenance failed")
            a = next(i for i,c in enumerate(all_candles) if c.time>=start)
            b = next(i for i,c in enumerate(all_candles) if c.time>=end)
            if a<200 or all_candles[a].time != start or all_candles[b-1].time != end-timedelta(minutes=5):
                raise ValueError("Training boundaries/warmup incomplete")
            candles = all_candles[a-200:b]
            manifest = build_dataset_manifest(candles,provider=parent.provider,source=parent.source,provider_symbol=symbol,
                canonical_symbol=symbol,timeframe=parent.timeframe,retrieved_at=parent.retrieved_at)
            sidecar = json.loads((directory/"recorded-spread.json").read_text())
            if sidecar["content_hash"] != parent.content_hash or sidecar["provider"] != "weltrade" or len(sidecar["rows"]) != len(all_candles):
                raise ValueError("Spread sidecar identity mismatch")
            if any(datetime.fromisoformat(row["time"]) != c.time for row,c in zip(sidecar["rows"],all_candles)):
                raise ValueError("Spread timestamps mismatch")
            econ = next(r["economics"] for r in acquisition["symbols"] if r["symbol"]==symbol)
            term = next(r for r in terms["symbols"] if r["symbol"]==symbol)
            if sidecar["point"] != term["point"]:
                raise ValueError("Sidecar point differs from contract snapshot")
            contract = contract_from_evidence(symbol,econ,term,server_offset=acquisition["terminal_verification"]["server_offset_seconds"])
            source_hashes = evidence_hashes + (("spread_sidecar",sha256_file(directory/"recorded-spread.json")),
                                              ("parent_manifest",sha256_file(directory/"manifest.json")))
            spreads = tuple(row["spread_points"]*sidecar["point"] for row in sidecar["rows"][a-200:b])
            for name, policy in costs.items():
                event = {"symbol": symbol,"cost": name,"partition": "TRAIN_DIAGNOSTIC_ONLY","state": "STARTED"}
                ledger(event)
                model = FrozenMarketModel(contract,policy,tuple(c.time for c in candles),spreads,candle_content_hash(candles),source_hashes)
                try:
                    engine = await runner(symbol=symbol,timeframe=parent.timeframe,dataset=candles,manifest=manifest,
                        provider="weltrade",starting_balance=50,market_model=model,start_index=200,end_index=len(candles))
                    result = engine.result
                    record = {"symbol": symbol,"cost": name,"start": start,"end_exclusive": end,
                        "parent_content_hash": parent.content_hash,"dataset_hash": result.dataset_hash,
                        "run_fingerprint": result.run_fingerprint,"result_hash": result.result_hash,
                        "metrics": diagnostic_metrics(engine,candles,200,len(candles))}
                    stem = symbol.replace(" ","_")+"--"+name
                    with (output/(stem+"--result.json")).open("xb") as stream:
                        stream.write(result.to_json_bytes())
                    write_new(output/(stem+"--metrics.json"),record)
                    results.append(record)
                    ledger({**event,"state": "COMPLETED","run_fingerprint": result.run_fingerprint,"result_hash": result.result_hash,"trades":result.total_trades})
                    print(f"{symbol} / {name}: {result.total_trades} trades",flush=True)
                except Exception as exc:
                    ledger({**event,"state":"FAILED","error_type":type(exc).__name__,"reason":str(exc)})
                    raise
    if source_snapshot() != snapshots:
        raise ValueError("Source/dependency drift across campaign; all results remain diagnostic and campaign invalid")
    summary = {"status":"TRAIN_DIAGNOSTIC_COMPLETE_PROMOTION_BLOCKED", "candidate_configurations_evaluated":0,
        "replays":len(results),"aggregates":{name:pooled_summary([r for r in results if r["cost"]==name],start,end) for name in costs}}
    write_new(output/"summary.json",summary)
    return summary
