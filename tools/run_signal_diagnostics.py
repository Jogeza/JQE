"""Run unchanged canonical signal diagnostics on preselected frozen windows."""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone

from broker.types import Timeframe
from data.dataset import canonical_dataset_hash
from data.storage import CandleStore
from research.signal_diagnostics import diagnose_signals
from tools.acquire_diagnostic_windows import WINDOWS

BASELINE = ("BASELINE", datetime(2026,8,24,tzinfo=timezone.utc), datetime(2026,8,31,tzinfo=timezone.utc))


def main() -> None:
    store, timeframe, output = CandleStore(read_only=True), Timeframe.M15, []
    for name, start, end in (BASELINE, *WINDOWS):
        candles = store.load_candles("XAUUSD", timeframe, start, end, provider="deriv")
        result = diagnose_signals(candles)
        payload = asdict(result)
        payload.update(name=name, start=start.isoformat(), end=end.isoformat(),
            dataset_hash=canonical_dataset_hash(candles,symbol="XAUUSD",timeframe=timeframe),
            condition_pass_percent={key: round(value/result.evaluations*100,2) if result.evaluations else 0
                                    for key,value in result.condition_pass_counts.items()})
        output.append(payload)
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__": main()
