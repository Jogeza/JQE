"""Rerun sequential safety variants with a fresh breaker each UTC day."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.settings import get_settings
from research.sequential_replay import (
    DEFAULT_HORIZON_BARS,
    GLOBAL_DAILY_CAP,
    load_persisted_candidates,
    load_series_arrays,
    load_watch_pairs,
    simulate_sequential,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("state/sequential_variants_next_day_reset.json"))
    args = parser.parse_args()
    settings = get_settings()
    if settings.broker_execution_enabled:
        raise RuntimeError("safety research refuses to run with broker execution enabled")
    candidates = load_persisted_candidates(settings.dashboard_paper_store_path.parent / "shadow_outcomes.sqlite3")
    pairs = load_watch_pairs(settings.watchlist_store_path)
    series = load_series_arrays(settings.cache_dir / "shadow_mt5_rates.sqlite3", pairs)
    per_cap = int(settings.max_daily_trades_per_instrument)
    result = {
        "execution_enabled": False,
        "horizon_bars": DEFAULT_HORIZON_BARS,
        "next_day_reset": True,
        "variants": {},
    }
    for name, kwargs in {
        "daily_loss_stop_minus_3R": {"daily_loss_stop": -3.0},
        "consecutive_loss_breaker_5": {"consecutive_loss_breaker": 5},
    }.items():
        result["variants"][name] = simulate_sequential(
            candidates, series, horizon=DEFAULT_HORIZON_BARS,
            global_cap=GLOBAL_DAILY_CAP, per_instrument_cap=per_cap,
            use_stored_outcome=True, **kwargs,
        )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output), "execution_enabled": False,
        "variants": {
            key: {
                "entries": value["metrics"]["entries"],
                "total_net_r": value["metrics"]["total_net_r"],
                "max_drawdown_r": value["max_drawdown_r"],
                "days": len(value.get("daily", [])),
            }
            for key, value in result["variants"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
