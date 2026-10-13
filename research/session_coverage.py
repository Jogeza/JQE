"""Load evidence-bound conditional session assumptions; no model or SDK calls."""
import json
from pathlib import Path

from backtesting.label_protocol import file_hash
from data.coverage import FrozenWeltradeSundayResearchPolicy


def load_policy(path):
    payload=json.loads(path.read_text())
    if file_hash(path)!=json.loads(path.with_suffix('.sha256.json').read_text())['sha256']:
        raise ValueError('Session policy checksum differs')
    if payload['id']!='jqe-sunday-research-calendar-v1' or payload['historical_timezone_verified'] is not False or payload['promotion_authorized'] is not False:
        raise ValueError('Unrecognized/unqualified session evidence')
    if payload['history']!={'start_inclusive':'2026-07-10T00:00:00+00:00','end_exclusive':'2026-10-08T00:00:00+00:00'} or payload['assumed_offset_seconds']!=10800:
        raise ValueError('Frozen research calendar scope differs')
    for name,h in payload['input_hashes'].items():
        if file_hash(Path(name))!=h:raise ValueError('Session evidence changed')
    return FrozenWeltradeSundayResearchPolicy(),payload
