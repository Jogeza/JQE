import asyncio
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from api.service import ApplicationService


def test_latest_evidence_normalizes_broker_and_preserves_newest_row(tmp_path,monkeypatch):
    path=tmp_path/"evidence.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE broker_account_verifications (id INTEGER PRIMARY KEY, broker TEXT, account_id TEXT, checked_field TEXT, observed_value INTEGER, status TEXT, verified_at TEXT, facts_json TEXT)")
        connection.executemany("INSERT INTO broker_account_verifications VALUES (?,?,?,?,?,?,?,?)",
            [(i," WelTrade " if i%2 else "weltrade",str(i),"trade_mode",0,"PASSED","now","{}") for i in range(1,1001)])
        connection.execute("INSERT INTO broker_account_verifications VALUES (1001,'legacy','last','trade_mode',0,'PASSED','now','{}')")
    before=path.read_bytes()
    monkeypatch.setattr("api.service.DEFAULT_BROKER_EVIDENCE_PATH",path)
    result=ApplicationService.__new__(ApplicationService)._get_latest_demo_verifications()
    assert set(result)=={"weltrade","legacy"}
    assert result["weltrade"]["account_id"]=="1000"
    assert path.read_bytes()==before  # Observation never edits historical evidence.


@pytest.mark.asyncio
async def test_live_status_durable_reads_run_off_event_loop(monkeypatch):
    service=ApplicationService.__new__(ApplicationService)
    loop_thread=threading.get_ident()
    read_threads=[]
    snapshot=SimpleNamespace(active_broker="weltrade")
    def read():
        read_threads.append(threading.get_ident())
        assert threading.get_ident()!=loop_thread
        return snapshot
    async def unavailable():
        # Exercise first snapshot off-loop without requiring any gateway or store.
        raise asyncio.CancelledError()
    monkeypatch.setattr(service,"get_broker_status",read)
    monkeypatch.setattr(service,"get_execution_state",unavailable)
    with pytest.raises(asyncio.CancelledError):
        await service.get_live_broker_status()
    assert len(read_threads)==1
