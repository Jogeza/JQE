import json
from datetime import datetime, timedelta, timezone
from monitoring.execution_heartbeat import read_execution_heartbeat


def test_heartbeat_never_treats_old_dead_or_future_evidence_as_armed(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / 'heartbeat.json'
    for age, alive, expected in [(10, True, 'RUNNING'), (601, True, 'STALE'), (10, False, 'STOPPED'), (-5, True, 'STALE')]:
        path.write_text(json.dumps(dict(pid=123, broker='weltrade', status='RUNNING',
            updated_at=(now-timedelta(seconds=age)).isoformat(), execution_enabled=True, cycle_number=2)))
        result = read_execution_heartbeat(path, now=now, process_alive=lambda pid: alive)
        assert result['state'] == expected
        assert result['execution_enabled'] is (expected == 'RUNNING')


def test_missing_corrupt_and_wrong_broker_heartbeat_are_unavailable(tmp_path):
    path = tmp_path / 'heartbeat.json'
    assert read_execution_heartbeat(path)['state'] == 'UNAVAILABLE'
    for value in ['\x00', '{}', '{"broker":"deriv"}']:
        path.write_text(value)
        assert read_execution_heartbeat(path)['execution_enabled'] is False
