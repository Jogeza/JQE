from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from tools import audit_candle_conflicts as audit


@pytest.mark.parametrize('repair', [False, True])
def test_audit_preserves_original_and_repairs_only_verified_closed_conflict(tmp_path, monkeypatch, repair):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'reports').mkdir()
    terminal_path = tmp_path/'terminal64.exe'
    config = SimpleNamespace(weltrade_terminal_path=terminal_path, effective_weltrade_login=42,
                             effective_weltrade_server='Weltrade-Demo', watchlist_store_path=tmp_path/'watch.sqlite3',
                             historical_data_path=tmp_path/'history.sqlite3')
    at = int((datetime.now(timezone.utc)-timedelta(minutes=10)).timestamp())
    with sqlite3.connect(config.watchlist_store_path) as db:
        db.execute('CREATE TABLE watchlist(symbol,timeframe)')
        db.execute("INSERT INTO watchlist VALUES ('FX Vol 20','M5')")
    with sqlite3.connect(config.historical_data_path) as db:
        db.execute('CREATE TABLE candles(provider,symbol,timeframe,time,open,high,low,close,volume)')
        db.execute("INSERT INTO candles VALUES ('weltrade','FX Vol 20','M5',?,100,100,100,100,1)",(at,))
    rate = dict(time=at+10800,open=100,high=103,low=99,close=102,tick_volume=300)
    forming = dict(rate, time=int(datetime.now(timezone.utc).timestamp())+10800)
    terminal = SimpleNamespace(initialize=lambda path:True,shutdown=lambda:None,
                               account_info=lambda:SimpleNamespace(trade_mode=0,login=42,server='Weltrade-Demo'),
                               terminal_info=lambda:SimpleNamespace(path=str(tmp_path)),
                               symbols_get=lambda:[SimpleNamespace(name='FX Vol 20')],
                               copy_rates_from_pos=lambda *args:[rate,forming],TIMEFRAME_M1=1,TIMEFRAME_M5=5)
    monkeypatch.setattr(audit,'mt5',terminal)
    monkeypatch.setattr(audit,'Settings',lambda:config)
    monkeypatch.setattr(audit,'_history_server_offset',lambda *args:10800)
    monkeypatch.setattr('sys.argv',['audit']+(['--repair'] if repair else []))
    audit.main()
    with sqlite3.connect(config.historical_data_path) as db:
        assert db.execute('SELECT count(*) FROM candles').fetchone()[0] == 1
        assert db.execute('SELECT close,volume FROM candles').fetchone() == ((102,300) if repair else (100,1))
    backups = list(tmp_path.glob('history.pre-conflict-repair-*.sqlite3'))
    assert len(backups) == int(repair)
    if repair:
        with sqlite3.connect(backups[0]) as db:
            assert db.execute('SELECT close,volume FROM candles').fetchone() == (100,1)
