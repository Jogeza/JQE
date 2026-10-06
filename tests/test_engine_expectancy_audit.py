"""Offline research safeguards: closed contiguous evidence and stricter gates."""
from datetime import datetime, timezone
import sqlite3

import pandas as pd
import pytest

from broker.types import Timeframe
from tools.audit_engine_expectancy import evaluate, freeze


def database(times):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE candles (provider,symbol,timeframe,time,open,high,low,close,volume,source)')
    db.executemany('INSERT INTO candles VALUES (?,?,?,?,?,?,?,?,?,?)',
                   [('weltrade', 'FX Vol 20', 'M1', t, 100, 101, 99, 100, 10, 'weltrade') for t in times])
    return db


def test_freeze_excludes_forming_bar_and_other_provider():
    now = datetime.fromtimestamp(120000, timezone.utc)
    db = database(range(60000, 120001, 60))
    db.execute("INSERT INTO candles VALUES ('deriv','FX Vol 20','M1',60001,200,201,199,200,10,'deriv')")
    bars, gaps = freeze(db, 'FX Vol 20', Timeframe.M1, 1000, now)
    assert len(bars) == 1000
    assert bars[-1].time.timestamp() == 119940
    assert gaps == 0
    assert all(bar.source == 'weltrade' and bar.close == 100 for bar in bars)


def test_freeze_rejects_disconnected_fragments_instead_of_filling_gaps():
    db = database([i*120 for i in range(1100)])
    with pytest.raises(ValueError, match='Insufficient contiguous'):
        freeze(db, 'FX Vol 20', Timeframe.M1, 1000, datetime.fromtimestamp(200000, timezone.utc))


def test_stricter_candidate_cannot_force_or_upgrade_baseline_signal():
    frame = pd.DataFrame({'time': pd.date_range('2026-01-01', periods=3, freq='min', tz='UTC'),
        'open': [100, 100, 100], 'high': [101, 101, 104], 'low': [99, 99, 99],
        'close': [100, 100, 103], 'ATR': [2, 2, 2], 'spread': [1, 1, 1]})
    signals = {i: {'signal': 'BUY' if i == 0 else 'NO_TRADE', 'confidence': 75} for i in range(3)}
    baseline = evaluate(frame, signals, 'FX Vol 20', Timeframe.M1, 0, 3, 75, 0)
    stricter = evaluate(frame, signals, 'FX Vol 20', Timeframe.M1, 0, 3, 80, 0)
    assert len(baseline.trades) == 1
    assert stricter.trades == []
    assert signals[0]['signal'] == 'BUY'
    assert baseline.risk_configuration.risk_percent == stricter.risk_configuration.risk_percent == 0.5
