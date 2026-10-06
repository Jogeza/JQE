"""Read-only execution supervisor evidence; never authorizes an order."""
import json
from datetime import datetime, timezone
from pathlib import Path
from core.processes import is_process_alive


def read_execution_heartbeat(path, *, now=None, max_age_seconds=600, process_alive=is_process_alive):
    result = dict(state='UNAVAILABLE', updated_at=None, age_seconds=None,
                  stale=True, process_alive=False, execution_enabled=False,
                  cycle_number=None, max_age_seconds=max_age_seconds)
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('broker') != 'weltrade':
            return result
        stamp = datetime.fromisoformat(value['updated_at'])
        pid = value['pid']
        status = value['status']
        if stamp.tzinfo is None or type(pid) is not int or pid <= 0 or status not in ('STARTING', 'RUNNING', 'BLOCKED', 'STOPPED', 'FAILED'):
            return result
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        alive = process_alive(pid)
        stale = not 0 <= age <= max_age_seconds
        state = 'STALE' if stale else 'STOPPED' if not alive else status
        result.update(state=state, updated_at=stamp.isoformat(), age_seconds=age,
                      stale=stale, process_alive=alive,
                      execution_enabled=not stale and alive and status in ('STARTING', 'RUNNING', 'BLOCKED') and value.get('execution_enabled') is True,
                      cycle_number=value.get('cycle_number') if type(value.get('cycle_number')) is int else None)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        pass
    return result
