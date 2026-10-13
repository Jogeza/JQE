"""Immutable interrupted-campaign validation; no signal or outcome generation."""
from collections import Counter
from datetime import timedelta
import json

from backtesting.label_protocol import file_hash
from backtesting.opportunity_inventory import aware


def validate_label(artifact, event, cost):
    label = artifact["label"]
    if (label["event_id"],label["cost"]) != (event["event_id"],cost):
        raise ValueError("Prior artifact identity mismatch")
    if label["result_hash"] != artifact["result_hash"]:
        raise ValueError("Prior result hash reference mismatch")
    trades = artifact["trades"]
    if label["status"] == "NON_EXECUTABLE":
        if trades or label["return_label"] is not None or not label["rejection_reasons"]:
            raise ValueError("Invalid prior rejection label")
    elif label["status"] == "EXECUTED":
        if len(trades)!=1 or label["return_label"] is None:
            raise ValueError("Invalid prior executed label cardinality")
        t=trades[0]; r=label["return_label"]; signal=aware(event["signal_bar_open"])
        if (aware(t["signal_timestamp"]) != signal or t["direction"]!=event["direction"]
            or aware(t["entry_timestamp"])!=signal+timedelta(minutes=5)
            or not signal+timedelta(minutes=5)<=aware(t["exit_timestamp"])<=signal+timedelta(minutes=95)
            or aware(r["available_at"])!=aware(t["exit_timestamp"])+timedelta(minutes=5)
            or t["exit_reason"]=="END_OF_DATA" or t["balance_before"]!=50
            or t["quantity"]["unit"]!="MT5_LOTS" or t["initial_risk_account_currency"]<=0
            or r["net_modelled_usd"]!=t["net_pnl"]
            or abs(r["net_r"]-t["net_pnl"]/t["initial_risk_account_currency"])>1e-12):
            raise ValueError("Invalid prior label chronology/capital/R")
    else:
        raise ValueError("Unknown prior label status")
    return label


def load_completed(previous, protocol, events):
    plan=json.loads((previous/"implementation-plan.json").read_text())
    rows=[json.loads(line) for line in (previous/"trials.jsonl").read_text().splitlines()]
    expected={(e["event_id"],cost) for e in events for cost in protocol["cost_cases"]}
    event_map={e["event_id"]:e for e in events}
    states={};records={};hashes={}
    for row in rows:
        key=(row["event_id"],row["cost"])
        if key not in expected or row["state"] not in {"STARTED","COMPLETED"}:
            raise ValueError("Unexpected or failed prior attempt; explicit review required")
        if row["state"]=="STARTED":
            if key in states:raise ValueError("Duplicate prior attempt")
            states[key]="STARTED"
        else:
            if states.get(key)!="STARTED":raise ValueError("Invalid prior ledger transition")
            path=previous/(key[0].removeprefix("sha256:")+"--"+key[1]+".json")
            label=validate_label(json.loads(path.read_text()),event_map[key[0]],key[1])
            if row["status"]!=label["status"]:raise ValueError("Prior ledger/artifact mismatch")
            records[key]=label;hashes[path.name]=file_hash(path);states[key]="COMPLETED"
    return plan,records,{"previous_directory":str(previous),"previous_plan_sha256":file_hash(previous/"implementation-plan.json"),
        "previous_ledger_sha256":file_hash(previous/"trials.jsonl"),"prior_completed":len(records),
        "interrupted_attempts":[{"event_id":k[0],"cost":k[1]} for k,v in states.items() if v=="STARTED"],
        "preserved_artifact_sha256":hashes,"note":"Unfinished attempts retried in new directory; original history remains unchanged"}
