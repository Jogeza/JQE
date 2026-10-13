import json
import pytest
from backtesting.label_resume import load_completed,validate_label


def fixture(tmp_path):
    event={"event_id":"sha256:abc","signal_bar_open":"2026-09-08T00:00:00+00:00","direction":"BUY"}
    label={"event_id":event["event_id"],"cost":"zero","status":"NON_EXECUTABLE","result_hash":"hash",
           "return_label":None,"rejection_reasons":["Minimum lot cannot satisfy risk"]}
    artifact={"label":label,"result_hash":"hash","trades":[]}
    (tmp_path/"implementation-plan.json").write_text('{}')
    (tmp_path/"abc--zero.json").write_text(json.dumps(artifact))
    started={"event_id":event["event_id"],"cost":"zero","state":"STARTED"}
    completed={**started,"state":"COMPLETED","status":"NON_EXECUTABLE"}
    (tmp_path/"trials.jsonl").write_text(json.dumps(started)+'\n'+json.dumps(completed)+'\n')
    return event,artifact,started


def test_resume_reuses_only_complete_labels_without_editing_history(tmp_path):
    e,_,_=fixture(tmp_path)
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    _,records,evidence=load_completed(tmp_path,{"cost_cases":{"zero":{}}},[e])
    assert len(records)==evidence["prior_completed"]==1
    assert not evidence["interrupted_attempts"]
    assert before=={p.name:p.read_bytes() for p in tmp_path.iterdir()}


def test_unfinished_entry_not_treated_as_complete(tmp_path):
    e,_,started=fixture(tmp_path)
    (tmp_path/"trials.jsonl").write_text(json.dumps(started)+'\n')
    _,records,evidence=load_completed(tmp_path,{"cost_cases":{"zero":{}}},[e])
    assert records=={}
    assert evidence["interrupted_attempts"]==[{"event_id":e["event_id"],"cost":"zero"}]


def test_duplicate_completed_identity_rejected(tmp_path):
    e,_,started=fixture(tmp_path)
    with (tmp_path/"trials.jsonl").open('a') as f:f.write(json.dumps(started)+'\n')
    with pytest.raises(ValueError,match="Duplicate"):
        load_completed(tmp_path,{"cost_cases":{"zero":{}}},[e])


def test_null_rejection_cannot_become_zero_training_return(tmp_path):
    e,artifact,_=fixture(tmp_path)
    artifact['label']['return_label']={'net_r':0}
    with pytest.raises(ValueError,match="rejection"):
        validate_label(artifact,e,'zero')
