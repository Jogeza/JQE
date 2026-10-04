"""Local read-only decision journal projection."""
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from config.settings import settings
from monitoring.decision_journal import read_journal
from core.processes import is_process_alive

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


@router.get("")
def journal(limit: int = Query(100, ge=1, le=500), symbol: str | None = None):
    try:
        result = read_journal(settings.decision_journal_path, limit=limit, symbol=symbol)
        result['supervisor'] = {'state': 'UNAVAILABLE', 'execution_enabled': False}
        try:
            heartbeat = json.loads(Path('state/weltrade_execution_supervisor_heartbeat.json').read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat['updated_at'])).total_seconds()
            running = is_process_alive(heartbeat['pid']) and 0 <= age <= 30 and heartbeat['status'] in ('STARTING', 'RUNNING', 'BLOCKED')
            result['supervisor'] = {
                'state': heartbeat['status'] if running else 'STOPPED_OR_STALE',
                'execution_enabled': running and heartbeat.get('execution_enabled') is True,
                'updated_at': heartbeat['updated_at'], 'cycle_number': heartbeat['cycle_number'],
                'reason': heartbeat.get('reason'),
            }
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result['analysis'] = {'state': 'UNAVAILABLE', 'current_pairs': 0, 'total_pairs': 0}
        try:
            heartbeat = json.loads(Path('state/live_analysis/heartbeat.json').read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat['updated_at'])).total_seconds()
            active = is_process_alive(heartbeat['pid']) and 0 <= age <= 30
            pairs = heartbeat.get('pairs', [])
            result['analysis'] = {
                'state': heartbeat['status'] if active else 'STOPPED_OR_STALE',
                'current_pairs': sum(pair.get('current') is True for pair in pairs) if active else 0,
                'total_pairs': len(pairs), 'updated_at': heartbeat['updated_at'],
                'execution_enabled': False,
            }
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return result
    except (OSError, sqlite3.Error, ValueError):
        raise HTTPException(503, detail="Decision journal evidence unavailable") from None
