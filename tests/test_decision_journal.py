import sqlite3
import pytest
from monitoring.decision_journal import DecisionJournal, read_journal


def test_missing_read_never_creates_database(tmp_path):
    path = tmp_path / 'missing.sqlite3'
    assert read_journal(path) == {'state': 'UNAVAILABLE', 'items': []}
    assert not path.exists()


def test_append_survives_restart_and_filters_without_mutating(tmp_path):
    path = tmp_path / 'journal.sqlite3'
    journal = DecisionJournal(path)
    journal.append(symbol='FX Vol 20', timeframe='M5', stage='ANALYSIS',
                   facts={'signal': 'NO_TRADE', 'confidence': 50, 'reasons': ['Weak momentum']})
    DecisionJournal(path).append(symbol='PainX 400', timeframe='M5', stage='DECISION',
                                facts={'status': 'BLOCKED', 'decision_code': 'DAILY_RISK_LIMIT'})
    rows = read_journal(path, symbol='fx vol 20')['items']
    assert len(rows) == 1
    assert rows[0]['facts']['reasons'] == ['Weak momentum']
    assert rows[0]['observed_at'].endswith('+00:00')
    assert read_journal(path, limit=1)['items'][0]['symbol'] == 'PainX 400'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM decisions').fetchone()[0] == 2


def test_nonfinite_evidence_is_rejected_without_a_partial_record(tmp_path):
    path = tmp_path / 'journal.sqlite3'
    journal = DecisionJournal(path)
    with pytest.raises(ValueError):
        journal.append(symbol='FX Vol 20', timeframe='M5', stage='ANALYSIS', facts={'confidence': float('nan')})
    assert read_journal(path)['items'] == []
