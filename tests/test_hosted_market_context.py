import importlib.util
from pathlib import Path
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location('market_context_projection',
    Path(__file__).resolve().parents[1] / 'frontend/api/_lib/market_context.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def evidence():
    return {'context': {'market_data_observation_time': '2026-10-04T20:00:00Z'},
            'candles': {'stale': False, 'degraded': False, 'market_data_source': 'BROKER',
                        'symbol': 'FX VOL 20', 'timeframe': 'M5',
                        'candles': [{'time': '2026-10-04T19:55:00Z', 'open': 100, 'high': 101, 'low': 99, 'close': 100}]},
            'signal': {'signal': 'NO_TRADE', 'confidence': 50},
            'account': {'password': 'never-copy', 'balance': 1000}}


def test_current_context_is_bounded_and_excludes_account_data():
    result = module.market_context(evidence(), 'FX VOL 20', 'M5', datetime(2026,10,4,20,0,30,tzinfo=timezone.utc))
    assert result['state'] == 'CURRENT'
    assert result['signal']['signal'] == 'NO_TRADE'
    assert 'never-copy' not in str(result) and 'balance' not in str(result)
    assert result['execution_authorization'].startswith('NONE')


def test_stale_wrong_market_and_missing_evidence_cannot_supply_prices():
    now = datetime(2026,10,4,20,0,30,tzinfo=timezone.utc)
    for snapshot, symbol, clock in ((evidence(), 'OTHER', now), ({}, 'FX VOL 20', now),
                                  (evidence(), 'FX VOL 20', datetime(2026,10,4,20,5,tzinfo=timezone.utc))):
        result = module.market_context(snapshot, symbol, 'M5', clock)
        assert result['state'] == 'UNAVAILABLE'
        assert 'candles' not in result
