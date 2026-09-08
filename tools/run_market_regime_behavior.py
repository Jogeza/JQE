"""Run strategy-independent behavior diagnostics on the frozen corpus."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from broker.types import Timeframe
from data.storage import CandleStore
from research.market_regime_corpus import (
    DEVELOPMENT_WINDOWS, corpus_artifact, market_behavior,
)
from research.market_regime_corpus import deterministic_hash


def main() -> None:
    store = CandleStore(read_only=True)
    corpus = json.loads(Path("data/research/v3_development_corpus.json").read_text(encoding="utf-8"))
    results = {}
    for item in corpus["selected_windows"]:
        start = __import__("datetime").datetime.fromisoformat(item["start"])
        end = __import__("datetime").datetime.fromisoformat(item["end"])
        candles = store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
        results[item["window_id"]] = {"regime": {k: item[k] for k in ("direction_label", "volatility_label", "efficiency_label")},
                                       "behavior": market_behavior(candles)}
    old = {}
    for name, start, end in DEVELOPMENT_WINDOWS:
        candles = store.load_candles("XAUUSD", Timeframe.M15, start, end, provider="deriv")
        old[name] = market_behavior(candles)
    payload = {"methodology": {"trend_impulse_bars": 16, "trend_forward_bars": 16, "breakout_range_bars": 20,
        "breakout_forward_bars": 8, "mean_reversion_reference_span": 50, "mean_reversion_forward_bars": 8,
        "mean_reversion_stretch_atr": 1.5, "bootstrap_repetitions": 1000, "bootstrap_seed": 62032},
        "corpus_artifact_hash": corpus["artifact_hash"], "behavior_by_window": results,
        "old_development_behavior_by_window": old, "warning": "MARKET_ONLY_DESCRIPTIVE_NOT_STRATEGY_VALIDATION"}
    payload["market_structure_classification"] = "NO_CLEAR_MARKET_STRUCTURE_EDGE"
    payload["artifact_hash"] = deterministic_hash(payload)
    Path("data/research/market_regime_behavior_v1.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"windows": len(results), "artifact_hash": payload["artifact_hash"], "classification": payload["market_structure_classification"]}, indent=2))


if __name__ == "__main__":
    main()