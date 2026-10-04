"""Keep canonical API analysis current with GET-only local requests.

This process owns no broker/execution capabilities and cannot submit orders.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from monitoring.observation_supervisor import ObservationMutex

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'state/live_analysis'


def read_api(resource, params=None):
    url = 'http://127.0.0.1:8000/api/v1/' + resource
    if params:
        url += '?' + urlencode(params)
    with urlopen(url, timeout=20) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('Analysis response too large')
    return json.loads(raw)


def current_analysis(payload):
    candles = payload.get('candles', {})
    return (candles.get('stale') is False and candles.get('degraded') is False
            and candles.get('market_data_source') == 'BROKER')


def publish(payload, path=None):
    STATE.mkdir(parents=True, exist_ok=True)
    path = path or STATE / 'heartbeat.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


async def run_cycle(fetch=read_api):
    watchlist = await asyncio.to_thread(fetch, 'watchlist')
    items = watchlist.get('items', [])
    if not items or len(items) > 34:
        raise ValueError('Configured watchlist unavailable or exceeds supported size')
    results = []
    for item in items:
        params = {'symbol': item['symbol'], 'timeframe': item['timeframe'], 'count': 250}
        payload = await asyncio.to_thread(fetch, 'market/active-analysis', params)
        fresh = current_analysis(payload)
        key = hashlib.sha256(f"{item['symbol']}:{item['timeframe']}".encode()).hexdigest()[:20]
        publish({'observed_at': datetime.now(timezone.utc).isoformat(),
                 'current': fresh, 'analysis': payload}, STATE / f'{key}.json')
        results.append({'symbol': item['symbol'], 'timeframe': item['timeframe'], 'current': fresh})
    return results


async def run():
    with ObservationMutex(STATE / 'analysis.lock'):
        while True:
            now = datetime.now(timezone.utc)
            heartbeat = {'pid': os.getpid(), 'updated_at': now.isoformat(),
                         'status': 'ANALYZING', 'execution_enabled': False}
            publish(heartbeat)
            try:
                results = await run_cycle()
                heartbeat.update(status='RUNNING' if all(r['current'] for r in results) else 'STALE', pairs=results)
            except Exception as exc:
                heartbeat.update(status='UNAVAILABLE', reason=type(exc).__name__)
            # Freshness is evaluated from market evidence, never the process badge.
            for _ in range(6):
                heartbeat['updated_at'] = datetime.now(timezone.utc).isoformat()
                publish(heartbeat)
                await asyncio.sleep(10)


if __name__ == '__main__':
    asyncio.run(run())
