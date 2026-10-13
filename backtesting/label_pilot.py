"""Fixed first-three-event implementation pilot, not ML or strategy selection."""
from dataclasses import asdict
import json

from backtesting.economics import FrozenCostPolicy, FrozenMarketModel, contract_from_evidence
from backtesting.label_protocol import file_hash, write_new
from backtesting.opportunity_inventory import aware
from backtesting.provenance import source_snapshot
from data.dataset import load_dataset_bundle, build_dataset_manifest, candle_content_hash
from unittest.mock import patch


async def pilot(registration, campaign, terms_path, output, runner, *, full_campaign=False, resume_from=None):
    output.mkdir(parents=True,exist_ok=False)
    protocol_path = registration / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    if file_hash(protocol_path) != json.loads((registration/"protocol.sha256.json").read_text())["sha256"]:
        raise ValueError("Registration checksum mismatch")
    if protocol["protocol_id"] != "jqe-counterfactual-training-labels-v1" or protocol["outcomes_computed"] != 0:
        raise ValueError("Unrecognized label registration")
    for path, expected in protocol["inputs"].items():
        from pathlib import Path
        if file_hash(Path(path)) != expected:
            raise ValueError("Registered input changed")
    if file_hash(registration/"events.json") != protocol["events_sha256"]:
        raise ValueError("Registered event list changed")
    if str(terms_path) not in protocol["inputs"] or str(campaign/"acquisition.json") not in protocol["inputs"]:
        raise ValueError("Unregistered evidence path")
    registered_events = json.loads((registration/"events.json").read_text())
    events = [e for e in registered_events if e["status"].startswith("ELIGIBLE")]
    if not full_campaign:
        events = events[:3]
    result_path = next(p for p in protocol["inputs"] if p.endswith("--result.json"))
    from pathlib import Path
    baseline = json.loads(Path(result_path).read_text())
    decisions = {d["timestamp"]:d for d in baseline["decisions"] if d["state"] != "EXECUTION_REJECTED"}
    bundle = campaign/"bundles"/"SFX_Vol_99_M5"
    all_candles,parent = load_dataset_bundle(bundle)
    start,end = (aware(protocol["training_window"][k]) for k in ("start_inclusive","end_exclusive"))
    a = next(i for i,c in enumerate(all_candles) if c.time>=start)-200
    b = next(i for i,c in enumerate(all_candles) if c.time>=end)
    candles = all_candles[a:b]
    if candles[0].time != aware(baseline["dataset_start"]) or candles[-1].time != aware(baseline["dataset_end"]):
        raise ValueError("Original indicator prefix changed")
    manifest = build_dataset_manifest(candles,provider="weltrade",source=parent.source,provider_symbol="SFX Vol 99",
        canonical_symbol="SFX Vol 99",timeframe=parent.timeframe,retrieved_at=parent.retrieved_at)
    if manifest.content_hash != baseline["run_context"]["manifest_content_hash"]:
        raise ValueError("Baseline data content differs")
    spreads = json.loads((bundle/"recorded-spread.json").read_text())
    acquisition = json.loads((campaign/"acquisition.json").read_text())
    terms = json.loads(terms_path.read_text())
    econ = next(r["economics"] for r in acquisition["symbols"] if r["symbol"] == "SFX Vol 99")
    term = next(r for r in terms["symbols"] if r["symbol"] == "SFX Vol 99")
    contract = contract_from_evidence("SFX Vol 99",econ,term,server_offset=acquisition["terminal_verification"]["server_offset_seconds"])
    source = source_snapshot()
    prior_records={}; resume_evidence=None
    if resume_from is not None:
        from backtesting.label_resume import load_completed
        previous_plan,prior_records,resume_evidence=load_completed(resume_from,protocol,events)
        if previous_plan["registration_sha256"]!=file_hash(protocol_path):
            raise ValueError("Previous campaign registration differs")
        old=previous_plan["source_snapshot"]
        changes={k for k in set(old["files"])|set(source["files"]) if old["files"].get(k)!=source["files"].get(k)}
        if old["dependencies"]!=source["dependencies"] or not changes.issubset({"backtesting/backtest.py","backtesting/label_pilot.py","backtesting/label_resume.py"}):
            raise ValueError("Resume source changed beyond orchestration; prior labels cannot be reused")
        import inspect,hashlib
        prechange=json.loads(Path("reports/counterfactual-resume-prechange-20261008.json").read_text())
        if hashlib.sha256(inspect.getsource(runner).encode()).hexdigest()!=prechange["run_backtest_body_sha256"]:
            raise ValueError("Canonical replay function changed")
        resume_evidence["source_files_changed"]=sorted(changes)
        resume_evidence["canonical_replay_body_sha256"]=prechange["run_backtest_body_sha256"]
        write_new(output/"resume-evidence.json",resume_evidence)
    write_new(output/"implementation-plan.json",{"registration_sha256":file_hash(protocol_path),"source_snapshot":source,
        "selection":"all registered eligible events" if full_campaign else "first three eligible events chronologically; all three frozen costs", "event_ids":[e["event_id"] for e in events],
        "attempts_planned":len(events)*3,"models_fitted":0,"candidate_configurations":0,
        "scope":"FULL_TRAINING_LABEL_CAMPAIGN_NOT_STRATEGY_PERFORMANCE" if full_campaign else "IMPLEMENTATION_PILOT_NOT_PERFORMANCE_EVALUATION",
        "resume_evidence_sha256":file_hash(output/"resume-evidence.json") if resume_evidence else None,
        "new_attempts_planned":len(events)*3-len(prior_records)})
    if full_campaign:
        write_new(output/"censored-events.json",[e for e in registered_events if not e["status"].startswith("ELIGIBLE")])
    records=list(prior_records.values())
    def ledger(row):
        with (output/"trials.jsonl").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(row,sort_keys=True)+"\n")
    def deny(*args,**kwargs):raise RuntimeError("Terminal access forbidden in label pilot")
    from core.logger import logger
    logger.remove(); logger.add(output/"pilot.log",level="WARNING")
    with patch.multiple("MetaTrader5",initialize=deny,login=deny,shutdown=deny,order_send=deny,symbol_select=deny,
                        copy_rates_from_pos=deny,copy_rates_range=deny):
        for event_number,event in enumerate(events):
            i=event["source_candle_index"]-a
            original=decisions[event["signal_bar_open"]]
            for name,policy_payload in protocol["cost_cases"].items():
                if (event["event_id"],name) in prior_records:
                    continue
                row={"event_id":event["event_id"],"cost":name}
                ledger({**row,"state":"STARTED"})
                try:
                    model=FrozenMarketModel(contract,FrozenCostPolicy(**policy_payload),tuple(c.time for c in candles),
                        tuple(r["spread_points"]*spreads["point"] for r in spreads["rows"][a:b]),candle_content_hash(candles),
                        tuple(sorted(protocol["inputs"].items())))
                    engine=await runner(symbol="SFX Vol 99",timeframe=parent.timeframe,provider="weltrade",dataset=candles,
                        manifest=manifest,market_model=model,start_index=i,end_index=i+20,
                        single_opportunity=(original["signal"],original["confidence"]))
                    record={**row,"status":"EXECUTED" if engine.trades else "NON_EXECUTABLE","result_hash":engine.result.result_hash,
                        "return_label":None,"rejection_reasons":[reason for d in engine.decisions for reason in d.reasons] if not engine.trades else []}
                    if engine.trades:
                        t=engine.trades[0]
                        from datetime import timedelta
                        record["return_label"]={"net_modelled_usd":t.net_pnl,"net_r":t.net_pnl/t.initial_risk_account_currency,
                            "available_at":(t.exit_timestamp+timedelta(minutes=5)).isoformat()}
                    artifact=engine.result.to_dict()
                    if full_campaign:
                        # Complete payload hash retained; compact trade/decision evidence
                        # avoids repeating thousands of unchanged indicator observations.
                        artifact={"label":record,"run_fingerprint":engine.result.run_fingerprint,
                            "result_hash":engine.result.result_hash,"dataset_hash":engine.result.dataset_hash,
                            "trades":artifact["trades"],"decisions":artifact["decisions"],
                            "source_snapshot_ref":"implementation-plan.json",
                            "scope":"COMPACT_EVIDENCE_NOT_COMPLETE_RESULT_HASH_PREIMAGE"}
                    write_new(output/(event["event_id"].removeprefix("sha256:")+"--"+name+".json"),artifact)
                    records.append(record);ledger({**row,"state":"COMPLETED","status":record["status"]})
                except Exception as exc:
                    ledger({**row,"state":"FAILED","error_type":type(exc).__name__,"reason":str(exc)})
                    raise
            if full_campaign and (event_number+1)%25==0:
                if source_snapshot()!=source:raise ValueError("Source drift during label campaign")
                print(f"Completed {event_number+1}/{len(events)} events ({len(records)} cost attempts)",flush=True)
    if source_snapshot()!=source:raise ValueError("Implementation source drift; pilot invalid")
    if resume_evidence:
        if file_hash(resume_from/"trials.jsonl")!=resume_evidence["previous_ledger_sha256"]:
            raise ValueError("Prior campaign continued or changed during resume")
        for name,expected_hash in resume_evidence["preserved_artifact_sha256"].items():
            if file_hash(resume_from/name)!=expected_hash:raise ValueError("Prior artifact changed during resume")
    write_new(output/"summary.json",{"status":"FULL_TRAINING_LABELS_COMPLETE_NOT_ML_READY" if full_campaign else "IMPLEMENTATION_PILOT_COMPLETE_NOT_ML_READY","attempts":records,
        "distinct_events":len(events),"models_fitted":0,"holdouts_read":False,"promotion_authorized":False})
