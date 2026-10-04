from tools.run_live_analysis import current_analysis


def test_current_requires_all_fresh_broker_evidence():
    assert current_analysis({'candles': {'stale': False, 'degraded': False, 'market_data_source': 'BROKER'}})
    for evidence in ({}, {'stale': True, 'degraded': False, 'market_data_source': 'BROKER'},
                     {'stale': False, 'degraded': True, 'market_data_source': 'BROKER'},
                     {'stale': False, 'degraded': False, 'market_data_source': 'SIMULATION'}):
        assert not current_analysis({'candles': evidence})
