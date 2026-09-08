"""Build and freeze a strategy-independent balanced development corpus."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import statistics

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker.types import Timeframe
from data.storage import CandleStore
from research.market_regime_corpus import (
    candidate_windows, build_window, corpus_artifact, discovery_artifact,
)


def main() -> None:
    store = CandleStore(read_only=True)
    candidates = []
    raw = []
    for window_id, start, end in candidate_windows():
        candles = store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
        if candles:
            raw.append((window_id, start, end, candles))
    provisional = []
    for _, _, _, candles in raw:
        from research.market_regime_corpus import _raw_metrics
        provisional.append(_raw_metrics(candles)["realized_volatility"])
    low, high = statistics.quantiles(provisional, n=3)[0:2] if len(provisional) >= 3 else (min(provisional), max(provisional))
    for window_id, start, end, candles in raw:
        try:
            candidates.append(build_window(window_id, start, end, candles, low, high))
        except ValueError:
            continue
    discovery = discovery_artifact(candidates)
    selected = __import__("research.market_regime_corpus", fromlist=["select_balanced"]).select_balanced(candidates)
    corpus = corpus_artifact(selected)
    root = Path("data/research")
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_regime_discovery_v1.json").write_text(json.dumps(discovery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "v3_development_corpus.json").write_text(json.dumps(corpus, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"discovery_windows": len(candidates), "selected_windows": len(selected),
        "selected_ids": [item.window_id for item in selected], "diversity_gate": corpus["diversity_gate"],
        "discovery_artifact_hash": discovery["artifact_hash"], "corpus_artifact_hash": corpus["artifact_hash"]}, indent=2))


if __name__ == "__main__":
    main()