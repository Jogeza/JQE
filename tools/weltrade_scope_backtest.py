"""Offline, resumable Weltrade demo scope research. Never connects to a broker.

No candidate has demonstrated positive expectancy. The earlier grid found zero
configurations with a positive CI excluding zero; SFX Vol 99 M1 was a
significant loser. This is instrumentation and learning, not a validated strategy.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ASSUMPTION = ("No candidate has demonstrated positive expectancy. The earlier grid "
              "found zero configurations with a positive CI excluding zero; "
              "SFX Vol 99 @ M1 was a significant loser. This is instrumentation "
              "and learning, not a validated strategy.")
SYMBOLS = (
    "FX Vol 20", "FX Vol 40", "FX Vol 60", "FX Vol 80", "FX Vol 99",
    "SFX Vol 20", "SFX Vol 40", "SFX Vol 60", "SFX Vol 80", "SFX Vol 99",
    "PainX 400", "PainX 600", "PainX 800", "PainX 999", "PainX 1200",
    "MAX PainX 1000", "MAX PainX 2000",
)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import weltrade_mtf_backtest as old
CELLS = ROOT / "state/scope_backtest_cells"
PROGRESS = ROOT / "state/scope_run_progress.json"
OUT = ROOT / "state/weltrade_scope_backtest.json"
LOG = ROOT / "logs/scope_backtest.log"


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, path)


def log(message):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{now()} {message}\n")


def cell_path(symbol, tf):
    return CELLS / f"{symbol.replace(' ', '_')}_{tf}.json"


def block_cis(rs, seed=12345, B=10000):
    n = len(rs)
    if n < 2:
        return {"ci95": [None, None], "ci99": [None, None], "block_length": None}
    L = max(2, round(n ** (1 / 3)))
    arr = np.asarray(rs, dtype=float)
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / L)
    means = np.empty(B)
    offsets = np.arange(L)
    for b in range(B):
        starts = rng.integers(0, n, size=blocks)
        means[b] = arr[((starts[:, None] + offsets) % n).ravel()[:n]].mean()
    return {"ci95": [float(x) for x in np.percentile(means, [2.5, 97.5])],
            "ci99": [float(x) for x in np.percentile(means, [0.5, 99.5])],
            "block_length": L}


def power_n(rs):
    if len(rs) < 2:
        return None
    sd = float(np.std(rs, ddof=1))
    # Normal approximation, two-sided alpha=.05, power=.80, target +0.1R.
    return math.ceil(((1.96 + 0.841621) * sd / 0.1) ** 2)


def spread_stats(candles, point, stop):
    spreads = np.asarray([c[5] * point for c in candles], dtype=float)
    valid = np.asarray(stop, dtype=float) > 0
    ratios = spreads[valid] / np.asarray(stop)[valid] * 100
    return {"median_price": float(np.median(spreads)),
            "p90_price": float(np.percentile(spreads, 90)),
            "median_pct_stop": float(np.median(ratios)) if len(ratios) else None,
            "p90_pct_stop": float(np.percentile(ratios, 90)) if len(ratios) else None}


def summary(trades):
    rs = [t["R"] for t in trades]
    pnls = [t["pnl"] for t in trades]
    if not rs:
        return {"trades": 0, "mean_R": None, "win_rate_pct": None,
                "block": block_cis(rs), "power_trades_for_plus_0_1R": None}
    equity = peak = 0.0
    dd = streak = longest = 0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
        streak = streak + 1 if pnl < 0 else 0
        longest = max(longest, streak)
    return {"trades": len(rs), "mean_R": float(np.mean(rs)),
            "win_rate_pct": 100 * sum(x > 0 for x in pnls) / len(rs),
            "block": block_cis(rs), "max_drawdown_usd_at_1_cap": dd,
            "max_drawdown_cap_units": dd / 1.0,
            "longest_losing_streak": longest,
            "power_trades_for_plus_0_1R": power_n(rs),
            "per_trade_sd_R": float(np.std(rs, ddof=1)) if len(rs) > 1 else None}


def random_control(candles, point, sp, terms, mid_ts, strategy_trades,
                   simulations=200, seed=12345):
    """Sample bias-gated entry times, preserving observed long/short frequency.

    The same stop series, stop/TP/cost/fill engine and one-position-at-a-time
    rule are applied. Oversample bias-qualified random signals, then keep the
    first N non-overlapping executed trades to match strategy trade frequency.
    """
    rng = np.random.default_rng(seed)
    n = len(candles)
    obs_longs = sum(t["dir"] == "LONG" for t in strategy_trades)
    obs_shorts = len(strategy_trades) - obs_longs
    eligible = terms["eligible_random_indices"]
    means = []
    counts = []
    target = len(strategy_trades)
    for _ in range(simulations):
        vals = []
        for multiplier in (2, 3, 4, 6):
            random_sp = {"signal": np.zeros(n, dtype=int), "stop": sp["stop"]}
            for direction, count in ((1, obs_longs), (-1, obs_shorts)):
                pool = eligible[direction]
                if count and len(pool):
                    chosen = rng.choice(pool, size=min(count * multiplier, len(pool)), replace=False)
                    random_sp["signal"][chosen] = direction
            ex = old._execute(candles, point, random_sp, terms, 1.0, mid_ts)
            vals = [t["R"] for t in ex["trades"][:target]]
            if len(vals) >= target:
                break
        if len(vals) != target:
            raise RuntimeError(f"random control could not match {target} trades; got {len(vals)}")
        means.append(float(np.mean(vals)) if vals else None)
        counts.append(len(vals))
    valid = np.asarray([x for x in means if x is not None])
    observed = float(np.mean([t["R"] for t in strategy_trades])) if strategy_trades else None
    return {"simulations": simulations, "seed": seed,
            "observed_percentile": float(100 * np.mean(valid <= observed)) if observed is not None and len(valid) else None,
            "null_mean_R_median": float(np.median(valid)) if len(valid) else None,
            "null_trade_count_median": float(np.median(counts)),
            "observed_trade_count": len(strategy_trades)}


def eligible_random_indices(candles, tf, h1, h4, stop, min_stop):
    pools = {1: [], -1: []}
    for i in range(old.WINDOW - 1, len(candles) - 1):
        if stop[i] < min_stop or stop[i] <= 0:
            continue
        ts = candles[i][0] + old.TF_SECONDS[tf]
        b1 = old._bias_at(*h1, ts)
        b4 = old._bias_at(*h4, ts)
        if b1 == b4 and b1 in pools:
            pools[b1].append(i)
    return pools


def gap_stats(trades, candles, stop, vpp_min, survey_stop):
    # Bar high-low is a conservative direction-agnostic adverse-move proxy.
    rng = np.asarray([c[2] - c[3] for c in candles], dtype=float)
    stop = np.asarray(stop, dtype=float)
    valid = stop > 0
    ratios = rng[valid] / stop[valid]
    sl = [t for t in trades if t["reason"] == "SL"]
    beyond = [-1 - t["R"] for t in sl if t["R"] < -1]
    worst_bar = float(np.max(rng[valid])) if valid.any() else None
    return {"largest_bar_move_vs_stop": float(np.max(ratios)) if len(ratios) else None,
            "worst_adverse_bar_price": worst_bar,
            "sl_fill_worse_than_minus_1R_pct": 100 * len(beyond) / len(trades) if trades else None,
            "sl_fill_worse_count": len(beyond),
            "worst_realized_R": min((t["R"] for t in trades), default=None),
            "avg_loss_beyond_minus_1R": float(np.mean(beyond)) if beyond else 0.0,
            "stress_loss_min_lot_usd": vpp_min * max(survey_stop, worst_bar) if worst_bar is not None else None}


def run_cell(symbol, tf, entry, survey_row):
    c = entry["timeframes"][tf]["candles"]
    h1 = old._direction_series(entry["timeframes"]["H1"]["candles"], "H1")
    h4 = old._direction_series(entry["timeframes"]["H4"]["candles"], "H4")
    sp = old._signal_pass_cached(symbol, tf, c, h1, h4)
    terms = {"volume_min": entry["volume_min"], "volume_step": entry["volume_step"],
             "value_per_point_min_lot_broker": survey_row["value_per_point_min_lot_broker"],
             "min_stop_distance_price": survey_row["min_stop_distance_price"]}
    mid = c[0][0] + (c[-1][0] - c[0][0]) // 2
    ex = old._execute(c, entry["point"], sp, terms, 1.0, mid)
    trades = ex["trades"]
    terms["eligible_random_indices"] = eligible_random_indices(c, tf, h1, h4, sp["stop"], terms["min_stop_distance_price"])
    result = {"assumption": ASSUMPTION, "symbol": symbol, "timeframe": tf,
              "bars": len(c), "history_first": entry["timeframes"][tf].get("first"),
              "history_last": entry["timeframes"][tf].get("last"),
              "spread": spread_stats(c, entry["point"], sp["stop"]),
              "tradeability_survey_min_lot_loss_usd": survey_row["timeframes"][tf]["min_lot_loss_usd"],
              "all": summary(trades),
              "first_half": summary([t for t in trades if t["half"] == "first"]),
              "second_half": summary([t for t in trades if t["half"] == "second"]),
              "gap": gap_stats(trades, c, sp["stop"], terms["value_per_point_min_lot_broker"],
                               survey_row["timeframes"][tf]["stop_distance"]),
              "random_entry": random_control(c, entry["point"], sp, terms, mid, trades),
              "raw_signals": int(np.count_nonzero(sp["raw"])),
              "mtf_passed_signals": int(np.count_nonzero(sp["signal"])),
              "rejected_sizing": ex["rejected_sizing"],
              "rejected_minstop": ex["rejected_minstop"],
              "generated_at": now()}
    return result


def regression(cache, survey):
    prior = json.loads((ROOT / "state/weltrade_mtf_backtest.json").read_text(encoding="utf-8"))
    cases = {"FlipX 1@M1": 0.0219, "SFX Vol 99@M1": -0.2226, "FiboX@M1": 0.0596}
    out = {}
    for key, expected in cases.items():
        symbol, tf = key.split("@")
        entry = cache["symbols"][symbol]
        c = entry["timeframes"][tf]["candles"]
        h1 = old._direction_series(entry["timeframes"]["H1"]["candles"], "H1")
        h4 = old._direction_series(entry["timeframes"]["H4"]["candles"], "H4")
        sp = old._signal_pass_cached(symbol, tf, c, h1, h4)
        row = survey[symbol]
        terms = {"volume_min": entry["volume_min"], "volume_step": entry["volume_step"],
                 "value_per_point_min_lot_broker": row["value_per_point_min_lot_broker"],
                 "min_stop_distance_price": row["min_stop_distance_price"]}
        mid = c[0][0] + (c[-1][0] - c[0][0]) // 2
        trades = old._execute(c, entry["point"], sp, terms, 0.25, mid)["trades"]
        actual = round(float(np.mean([t["R"] for t in trades])), 4) if trades else None
        old_cell = prior["candidates"][key]["by_cap"]["0.25"]["all"]
        out[key] = {"expected_mean_R": expected, "rerun_mean_R": actual,
                    "prior_mean_R": old_cell["avg_R_after_costs"],
                    "rerun_trades": len(trades), "prior_trades": old_cell["trades"],
                    "identical": actual == expected == old_cell["avg_R_after_costs"] and len(trades) == old_cell["trades"]}
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--regression-only", action="store_true")
    parser.add_argument("--refresh-cells", action="store_true",
                        help="Recompute existing scoped cells using cached signal passes")
    args = parser.parse_args()
    os.chdir(ROOT)
    # No broker module, gateway, or MT5 package is imported here.
    from core.logger import logger
    logger.disable("intelligence.market_regime")
    with gzip.open(ROOT / "state/weltrade_history_cache.json.gz", "rt", encoding="utf-8") as f:
        cache = json.load(f)
    survey_raw = json.loads((ROOT / "state/weltrade_cost_survey.json").read_text(encoding="utf-8"))
    survey = {r["symbol"]: r for r in survey_raw["rows"]}
    if args.regression_only:
        print(json.dumps(regression(cache, survey), indent=2))
        return
    pending = []
    skipped = {}
    untradeable = {}
    for symbol in SYMBOLS:
        for tf in ("M1", "M5"):
            key = f"{symbol}@{tf}"
            entry = cache["symbols"].get(symbol)
            c = ((entry or {}).get("timeframes", {}).get(tf) or {}).get("candles") or []
            h1 = ((entry or {}).get("timeframes", {}).get("H1") or {}).get("candles") or []
            h4 = ((entry or {}).get("timeframes", {}).get("H4") or {}).get("candles") or []
            loss = survey[symbol]["timeframes"][tf]["min_lot_loss_usd"]
            spread_cost = survey[symbol]["spread_price"] * survey[symbol]["value_per_point_min_lot_broker"]
            all_in_loss = loss + spread_cost
            if all_in_loss > 2.0:
                untradeable[key] = {"min_lot_stop_loss_usd": loss,
                                    "spread_cost_usd": spread_cost,
                                    "all_in_min_lot_loss_usd": all_in_loss,
                                    "reason": "survey stop loss plus spread exceeds $2"}
            if len(c) <= old.WINDOW + 5 or not h1 or not h4:
                skipped[key] = {"reason": "missing or insufficient cached M1/M5 or H1/H4 history",
                                "bars": len(c), "survey_min_lot_loss_usd": loss}
            elif all_in_loss > 2.0:
                skipped[key] = {"reason": "untradeable at $2 filter", "all_in_min_lot_loss_usd": all_in_loss}
            elif args.refresh_cells or not cell_path(symbol, tf).exists():
                pending.append(key)
    started = now()
    def progress():
        done = [f"{s}@{tf}" for s in SYMBOLS for tf in ("M1", "M5") if cell_path(s, tf).exists()]
        atomic_json(PROGRESS, {"assumption": ASSUMPTION, "started_or_resumed_at": started,
                               "updated_at": now(), "done": done, "pending": pending,
                               "skipped": skipped})
    # Finish cells with an existing signal-pass cache first; the uncached pass
    # can take much longer and remains a single resumable pending cell.
    pending.sort(key=lambda key: (not (ROOT / "state/_sigcache" /
                                  f"{key.split('@')[0].replace(' ', '_')}_{key.split('@')[1]}_"
                                  f"{len(cache['symbols'][key.split('@')[0]]['timeframes'][key.split('@')[1]]['candles'])}.npz").exists(), key))
    progress()
    for key in list(pending):
        symbol, tf = key.split("@")
        log(f"START {key}")
        result = run_cell(symbol, tf, cache["symbols"][symbol], survey[symbol])
        atomic_json(cell_path(symbol, tf), result)
        pending.remove(key)
        progress()
        log(f"DONE {key} trades={result['all']['trades']}")
    cells = {f"{s}@{tf}": json.loads(cell_path(s, tf).read_text(encoding="utf-8"))
             for s in SYMBOLS for tf in ("M1", "M5") if cell_path(s, tf).exists()}
    tests = len(cells)
    output = {"assumption": ASSUMPTION, "generated_at": now(),
              "assumptions": {"window": 500, "stop_atr_multiplier": 2,
                              "target_rr": 2, "slippage_spread_fraction": 0.5,
                              "sl_first_same_bar": True, "cap_usd": 1,
                              "block_bootstrap_seed": 12345, "block_bootstrap_B": 10000},
              "cells": cells, "skipped": skipped, "untradeable": untradeable,
              "spread_outlier_check": {
                  "symbol": "SFX Vol 60", "survey_spread_price": survey["SFX Vol 60"]["spread_price"],
                  "status": "unverifiable: no per-bar SFX Vol 60 history in cache",
              },
              "multiple_testing": {"tested_cells": tests, "expected_false_positives_at_5pct": tests * .05,
                                   "expected_false_positives_at_1pct": tests * .01,
                                   "bonferroni_two_sided_alpha": .05 / tests if tests else None},
              "regression": regression(cache, survey)}
    atomic_json(OUT, output)
    log(f"COMPLETE cells={tests}")


if __name__ == "__main__":
    main()
