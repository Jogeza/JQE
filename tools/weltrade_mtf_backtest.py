"""Offline MTF evaluation for Step 3 (no broker, no orders, no config changes).

Reads the read-only history cache produced by ``tools/weltrade_history_cache.py``
and replays the CANONICAL signal pipeline (``core.indicators`` ->
``core.regime.detect_regime`` -> ``strategy.pipeline.generate_trading_signal``)
bar by bar on a rolling 500-bar window, exactly mirroring live ``main.py``
(``default_candle_count=500``). Higher timeframes (H1/H4) supply DIRECTION ONLY
(EMA50 vs EMA200); they never generate signals.

Execution model (stated assumptions):
* Closed candles only. Signal computed on bar i's close; entry at bar i+1 OPEN.
* Candles are broker BID series; each bar carries its recorded spread (points).
* BUY round trip pays the spread on entry (fills at ask); SELL pays it on exit
  (covers at ask). Slippage = ``SLIPPAGE_SPREAD_FRACTION`` x that bar's spread,
  applied to MARKET fills only (entries and stop-loss exits). Take-profit exits
  are limit fills at the trigger price (no slippage), gap-aware.
* If SL and TP are both touched inside one bar, SL is assumed first.
* Stop distance = 2 x ATR_14 (the strategy's real stop today); TP = 2 x stop
  (target_rr 2.0 => RR 2.0). Nothing is tuned.
* A trade whose stop distance is below the broker minimum stop distance is
  rejected (cannot legally place the SL).
* Sizing per risk cap: lot = floor_to_step(cap / loss_per_lot_at_stop); if the
  lot rounds below the broker minimum lot the trade is REJECTED (never rounded
  up, never widening/dropping the SL). One position at a time per candidate.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

WINDOW = 500               # live default_candle_count
ATR_SL_MULTIPLIER = 2.0    # strategy stop distance = 2 x ATR14
TARGET_RR = 2.0            # strategy target_rr => TP = 2 x stop distance
SLIPPAGE_SPREAD_FRACTION = 0.5  # market fills slip half the recorded spread
MIN_TRADES_TO_CONCLUDE = 30
RISK_CAPS = (0.25, 0.50, 1.00)
PRIMARY_CAP = 0.50

TF_SECONDS = {"M1": 60, "M5": 300, "H1": 3600, "H4": 14400}


def _floor_to_step(value: float, step: float, vmin: float) -> float:
    if step <= 0:
        return value
    floored = math.floor(value / step + 1e-9) * step
    return round(floored, 10)


def _direction_series(candles: list[list[Any]], tf: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (close_times, direction) where direction is 1=UP, -1=DOWN, 0=flat.

    EMA50 vs EMA200 on the higher timeframe, evaluated once over the full
    series (rolling, no lookahead). ``close_times`` lets the entry loop pick the
    last HIGHER-TF bar that had already CLOSED at the decision moment.
    """
    from core.indicators import calculate_indicators

    df = pd.DataFrame(
        {
            "time": [datetime.fromtimestamp(c[0], tz=timezone.utc) for c in candles],
            "open": [c[1] for c in candles],
            "high": [c[2] for c in candles],
            "low": [c[3] for c in candles],
            "close": [c[4] for c in candles],
            "volume": [1.0] * len(candles),
        }
    )
    enriched = calculate_indicators(df)
    ema50 = enriched["EMA_50"].to_numpy(dtype=float)
    ema200 = enriched["EMA_200"].to_numpy(dtype=float)
    close_times = np.array([c[0] + TF_SECONDS[tf] for c in candles], dtype=np.int64)
    direction = np.zeros(len(candles), dtype=int)
    direction[ema50 > ema200] = 1
    direction[ema50 < ema200] = -1
    return close_times, direction


def _bias_at(close_times: np.ndarray, direction: np.ndarray, decision_ts: int) -> int:
    """Direction of the last higher-TF bar that CLOSED at/before decision_ts."""
    idx = int(np.searchsorted(close_times, decision_ts, side="right")) - 1
    if idx < 0:
        return 0
    return int(direction[idx])


def _signal_pass(
    symbol: str, candles: list[list[Any]], tf: str,
    h1: tuple[np.ndarray, np.ndarray], h4: tuple[np.ndarray, np.ndarray],
) -> dict[str, np.ndarray]:
    """Expensive pass: canonical signal + ATR + H1/H4 direction per bar."""
    from core.indicators import calculate_indicators
    from core.regime import detect_regime
    from strategy.pipeline import generate_trading_signal

    n = len(candles)
    sig = np.zeros(n, dtype=int)        # 1 BUY, -1 SELL, 0 none (after MTF filter)
    raw = np.zeros(n, dtype=int)        # pre-filter signal
    atr = np.zeros(n, dtype=float)
    stopd = np.zeros(n, dtype=float)
    blocked = np.zeros(n, dtype=int)    # 1 if signal existed but MTF blocked it
    tf_sec = TF_SECONDS[tf]
    times = np.array([c[0] for c in candles], dtype=np.int64)

    base = pd.DataFrame(
        {
            "time": [datetime.fromtimestamp(c[0], tz=timezone.utc) for c in candles],
            "open": [c[1] for c in candles],
            "high": [c[2] for c in candles],
            "low": [c[3] for c in candles],
            "close": [c[4] for c in candles],
            "volume": [float(c[5]) for c in candles],
        }
    )
    for i in range(WINDOW - 1, n):
        window = base.iloc[i - WINDOW + 1 : i + 1]
        enriched = calculate_indicators(window)
        regime = detect_regime(enriched)
        result = generate_trading_signal(enriched, symbol, regime=regime)
        s = result.get("signal", "NO_TRADE")
        a = float(result.get("intelligence", {}).get("atr", 0.0) or 0.0)
        atr[i] = a
        stopd[i] = a * ATR_SL_MULTIPLIER
        raw_dir = 1 if s == "BUY" else -1 if s == "SELL" else 0
        raw[i] = raw_dir
        if raw_dir == 0:
            continue
        decision_ts = int(times[i]) + tf_sec
        b1 = _bias_at(h1[0], h1[1], decision_ts)
        b4 = _bias_at(h4[0], h4[1], decision_ts)
        # direction-only filter: both H1 and H4 must agree with the signal
        if raw_dir == 1 and b1 == 1 and b4 == 1:
            sig[i] = 1
        elif raw_dir == -1 and b1 == -1 and b4 == -1:
            sig[i] = -1
        else:
            blocked[i] = 1
    return {"signal": sig, "raw": raw, "atr": atr, "stop": stopd, "blocked": blocked}


def _signal_pass_cached(
    symbol: str, tf: str, candles: list[list[Any]],
    h1: tuple[np.ndarray, np.ndarray], h4: tuple[np.ndarray, np.ndarray],
) -> dict[str, np.ndarray]:
    """Signal pass with an on-disk cache so re-runs (e.g. for bootstrap) are instant.

    The cache is keyed by symbol+timeframe+bar-count; the signal pass is
    deterministic for a fixed history cache, so a matching count is sufficient.
    """
    cache_dir = Path("state/_sigcache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace(" ", "_")
    path = cache_dir / f"{safe}_{tf}_{len(candles)}.npz"
    if path.exists():
        z = np.load(path)
        return {k: z[k] for k in ("signal", "raw", "atr", "stop", "blocked")}
    sp = _signal_pass(symbol, candles, tf, h1, h4)
    np.savez(path, **sp)
    return sp


def _execute(
    candles: list[list[Any]], point: float, sp: dict[str, np.ndarray],
    terms: dict[str, Any], cap: float, series_mid_ts: int,
) -> dict[str, Any]:
    """Cheap pass: sequence one-position-at-a-time trades for a risk cap."""
    n = len(candles)
    times = [c[0] for c in candles]
    opens = np.array([c[1] for c in candles], dtype=float)
    highs = np.array([c[2] for c in candles], dtype=float)
    lows = np.array([c[3] for c in candles], dtype=float)
    spreads = np.array([c[5] for c in candles], dtype=float) * point

    vmin = terms["volume_min"]
    vstep = terms["volume_step"]
    vpp_min = terms["value_per_point_min_lot_broker"] or 0.0
    vpp_per_lot = vpp_min / vmin if vmin else 0.0  # $ per 1.0 price point per 1.0 lot
    min_stop = terms["min_stop_distance_price"]

    trades: list[dict[str, Any]] = []
    rejected_sizing = 0
    rejected_minstop = 0
    i = WINDOW - 1
    while i < n - 1:
        d = int(sp["signal"][i])
        if d == 0:
            i += 1
            continue
        stop_dist = float(sp["stop"][i])
        if stop_dist <= 0:
            i += 1
            continue
        if stop_dist < min_stop:
            rejected_minstop += 1
            i += 1
            continue
        loss_at_stop_minlot = vpp_min * stop_dist
        lot_max = (cap * vmin / loss_at_stop_minlot) if loss_at_stop_minlot > 0 else 0.0
        lot = _floor_to_step(lot_max, vstep, vmin)
        if lot < vmin - 1e-12:
            rejected_sizing += 1
            i += 1
            continue
        risked = vpp_per_lot * lot * stop_dist
        tp_dist = stop_dist * TARGET_RR

        e = i + 1
        spread_e = spreads[e]
        slip_e = SLIPPAGE_SPREAD_FRACTION * spread_e
        if d == 1:
            entry_fill = opens[e] + spread_e + slip_e
            sl_level = entry_fill - stop_dist
            tp_level = entry_fill + tp_dist
        else:
            entry_fill = opens[e] - slip_e
            sl_level = entry_fill + stop_dist
            tp_level = entry_fill - tp_dist

        exit_price = None
        reason = "EOD"
        exit_bar = n - 1
        for j in range(e, n):
            o, h, l = opens[j], highs[j], lows[j]
            spread_j = spreads[j]
            slip_j = SLIPPAGE_SPREAD_FRACTION * spread_j
            if d == 1:
                if l <= sl_level:
                    exit_price = min(o, sl_level) - slip_j
                    reason = "SL"
                    exit_bar = j
                    break
                if h >= tp_level:
                    exit_price = max(o, tp_level)
                    reason = "TP"
                    exit_bar = j
                    break
            else:
                ask_o, ask_h, ask_l = o + spread_j, h + spread_j, l + spread_j
                if ask_h >= sl_level:
                    exit_price = max(ask_o, sl_level) + slip_j
                    reason = "SL"
                    exit_bar = j
                    break
                if ask_l <= tp_level:
                    exit_price = min(ask_o, tp_level)
                    reason = "TP"
                    exit_bar = j
                    break
        if exit_price is None:
            # never resolved by series end: mark-to-market at the final bar close
            j = n - 1
            spread_j = spreads[j]
            slip_j = SLIPPAGE_SPREAD_FRACTION * spread_j
            exit_price = closes_last_bid(d, candles, j, spread_j, slip_j)
            reason = "EOD"
            exit_bar = j

        pnl_per_point = vpp_per_lot * lot
        if d == 1:
            pnl = (exit_price - entry_fill) * pnl_per_point
        else:
            pnl = (entry_fill - exit_price) * pnl_per_point
        r = pnl / risked if risked > 0 else 0.0
        trades.append(
            {
                "entry_ts": int(times[e]),
                "exit_ts": int(times[exit_bar]),
                "dir": "LONG" if d == 1 else "SHORT",
                "reason": reason,
                "bars_held": exit_bar - e,
                "lot": round(lot, 10),
                "risked": round(risked, 6),
                "pnl": round(pnl, 6),
                "R": round(r, 6),
                "half": "first" if int(times[e]) < series_mid_ts else "second",
            }
        )
        i = exit_bar + 1  # resume after the position closes (no pyramiding)

    return {
        "cap": cap,
        "trades": trades,
        "rejected_sizing": rejected_sizing,
        "rejected_minstop": rejected_minstop,
    }


def closes_last_bid(d: int, candles: list[list[Any]], j: int, spread_j: float, slip_j: float) -> float:
    close_bid = candles[j][4]
    if d == 1:  # sell to close at bid
        return close_bid - slip_j
    return close_bid + spread_j + slip_j  # buy to cover at ask


def _bootstrap_ci_mean_r(rs: list[float], B: int = 10000, seed: int = 12345) -> list[Any]:
    """Percentile bootstrap 95% CI on the mean R (resample trades with replacement)."""
    if len(rs) < 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    arr = np.asarray(rs, dtype=float)
    idx = rng.integers(0, len(arr), size=(B, len(arr)))
    means = arr[idx].mean(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def _block_length(n: int) -> int:
    """Moving-block length via the n**(1/3) rule ( Politis-White style heuristic)."""
    return max(2, int(round(n ** (1.0 / 3.0))))


def _block_bootstrap_ci_mean_r(rs: list[float], B: int = 10000, seed: int = 12345) -> tuple[Any, Any, int]:
    """Moving-block bootstrap 95% CI on the mean R.

    Trades are time-ordered and losing streaks cluster, so an iid resample
    understates variance. This resamples contiguous blocks of length L (with
    replacement, circular wrap) to preserve short-range serial correlation.
    Returns (ci_low, ci_high, block_length).
    """
    n = len(rs)
    if n < 2:
        return [None, None, 0]
    L = _block_length(n)
    arr = np.asarray(rs, dtype=float)
    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / L))
    means = np.empty(B, dtype=float)
    for b in range(B):
        starts = rng.integers(0, n, size=n_blocks)
        # circular block indices, concatenated then trimmed to n
        idx = (starts[:, None] + np.arange(L)[None, :]) % n
        sample = arr[idx.ravel()][:n]
        means[b] = sample.mean()
    return (
        round(float(np.percentile(means, 2.5)), 4),
        round(float(np.percentile(means, 97.5)), 4),
        L,
    )


def _metrics(trades: list[dict[str, Any]], base: float = 10.0) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    pnls = [t["pnl"] for t in trades]
    rs = [t["R"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    ci_low, ci_high = _bootstrap_ci_mean_r(rs)
    blk_low, blk_high, blk_len = _block_bootstrap_ci_mean_r(rs)
    # max drawdown on a $base account, realized balance path
    equity = base
    peak = base
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    # worst losing streak
    worst = cur = 0
    for p in pnls:
        cur = cur + 1 if p < 0 else 0
        worst = max(worst, cur)
    n = len(trades)
    win_rate = len(wins) / n * 100.0
    avg_r = sum(rs) / n
    return {
        "trades": n,
        "win_rate_pct": round(win_rate, 2),
        "avg_R_after_costs": round(float(avg_r), 4),
        "mean_R_ci95": [ci_low, ci_high],
        "mean_R_ci95_block": [blk_low, blk_high],
        "block_length": blk_len,
        "expectancy_R": round(float(avg_r), 4),
        "expectancy_usd_avg_trade": round(float(sum(pnls) / n), 4),
        "breakeven_win_rate_pct_at_RR2": round(100.0 / (1.0 + TARGET_RR), 2),
        "net_pnl_usd": round(float(sum(pnls)), 4),
        "max_drawdown_usd_on_10": round(float(max_dd), 4),
        "max_drawdown_pct_on_10": round(float(max_dd / base * 100.0), 2),
        "worst_losing_streak": worst,
        "avg_bars_held": round(sum(t["bars_held"] for t in trades) / n, 2),
        "too_few": n < MIN_TRADES_TO_CONCLUDE,
        "final_equity_on_10": round(float(base + sum(pnls)), 4),
    }



def _largest_bar_move_vs_stop(candles: list[list[Any]], stop: np.ndarray) -> float:
    rng = np.array([c[2] - c[3] for c in candles], dtype=float)
    valid = stop[WINDOW - 1 :] > 0
    if not np.any(valid):
        return float("nan")
    ratios = (rng[WINDOW - 1 :][valid] / stop[WINDOW - 1 :][valid])
    return float(np.max(ratios)) if len(ratios) else float("nan")


def _cost_distribution(
    candles: list[list[Any]], vpp_min: float, tf: str
) -> dict[str, Any]:
    """p50/p90/max min-lot loss over history + % of bars under $0.50 (item 2)."""
    from core.indicators import calculate_indicators

    df = pd.DataFrame(
        {
            "time": [datetime.fromtimestamp(c[0], tz=timezone.utc) for c in candles],
            "open": [c[1] for c in candles],
            "high": [c[2] for c in candles],
            "low": [c[3] for c in candles],
            "close": [c[4] for c in candles],
            "volume": [1.0] * len(candles),
        }
    )
    enriched = calculate_indicators(df)
    atr = enriched["ATR_14"].dropna().to_numpy(dtype=float)
    if len(atr) == 0:
        return {"error": "no atr"}
    stop = atr * ATR_SL_MULTIPLIER
    loss = vpp_min * stop
    return {
        "bars": int(len(loss)),
        "p50": round(float(np.percentile(loss, 50)), 4),
        "p90": round(float(np.percentile(loss, 90)), 4),
        "max": round(float(np.max(loss)), 4),
        "min": round(float(np.min(loss)), 4),
        "pct_under_0_50": round(float((loss <= 0.50).mean() * 100.0), 2),
        "pct_under_1_00": round(float((loss <= 1.00).mean() * 100.0), 2),
    }


CANDIDATES = {
    "M1": ["FlipX 1", "SFX Vol 99", "FiboX", "FlipX 2", "PlusX 1", "SFX Vol 20"],
    "M5": ["FlipX 1", "FiboX", "FlipX 2", "PlusX 1", "SFX Vol 99"],
}


def evaluate(cache_path: str, survey_path: str, out_path: str | None,
             max_bars: int | None = None) -> dict[str, Any]:
    with gzip.open(cache_path, "rt", encoding="utf-8") as handle:
        cache = json.load(handle)
    # The canonical regime detector logs at INFO on every call; over ~500k
    # bar evaluations that would churn the rotating log file. Silence just
    # that module for this offline run (no config change, no behavior change).
    from core.logger import logger as _logger

    _logger.disable("intelligence.market_regime")
    survey = json.loads(Path(survey_path).read_text(encoding="utf-8"))
    survey_terms = {r["symbol"]: r for r in survey["rows"]}

    results: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(),
                               "assumptions": {
                                   "window": WINDOW, "atr_sl_multiplier": ATR_SL_MULTIPLIER,
                                   "target_rr": TARGET_RR, "slippage_spread_fraction": SLIPPAGE_SPREAD_FRACTION,
                                   "sl_first_on_same_bar": True, "risk_caps": list(RISK_CAPS),
                               }, "candidates": {}}

    for tf, symbols in CANDIDATES.items():
        for symbol in symbols:
            key = f"{symbol}@{tf}"
            entry = cache["symbols"].get(symbol)
            if not entry or "timeframes" not in entry:
                results["candidates"][key] = {"error": "no cached history"}
                continue
            tf_cell = entry["timeframes"].get(tf) or {}
            candles = tf_cell.get("candles") or []
            if max_bars is not None and len(candles) > max_bars:
                candles = candles[-max_bars:]
            if len(candles) <= WINDOW + 5:
                results["candidates"][key] = {"error": "insufficient history", "bars": len(candles)}
                continue
            point = entry["point"]
            h1_cell = entry["timeframes"].get("H1") or {}
            h4_cell = entry["timeframes"].get("H4") or {}
            h1 = _direction_series(h1_cell.get("candles") or [], "H1")
            h4 = _direction_series(h4_cell.get("candles") or [], "H4")

            terms = {
                "volume_min": entry["volume_min"],
                "volume_step": entry["volume_step"],
                "value_per_point_min_lot_broker": (survey_terms.get(symbol) or {}).get(
                    "value_per_point_min_lot_broker"
                ),
                "min_stop_distance_price": (survey_terms.get(symbol) or {}).get(
                    "min_stop_distance_price", 0.0
                ),
            }
            sp = _signal_pass_cached(symbol, tf, candles, h1, h4)
            times = [c[0] for c in candles]
            mid_ts = times[0] + (times[-1] - times[0]) // 2

            per_cap: dict[str, Any] = {}
            for cap in RISK_CAPS:
                ex = _execute(candles, point, sp, terms, cap, mid_ts)
                allm = _metrics(ex["trades"])
                first = _metrics([t for t in ex["trades"] if t["half"] == "first"])
                second = _metrics([t for t in ex["trades"] if t["half"] == "second"])
                per_cap[f"{cap:.2f}"] = {
                    "all": allm, "first_half": first, "second_half": second,
                    "rejected_sizing": ex["rejected_sizing"],
                    "rejected_minstop": ex["rejected_minstop"],
                    "R_values": [t["R"] for t in ex["trades"]],
                }
            results["candidates"][key] = {
                "symbol": symbol, "timeframe": tf,
                "bars": len(candles),
                "history_first": tf_cell.get("first"), "history_last": tf_cell.get("last"),
                "point": point, "terms": terms,
                "raw_signals": int(np.count_nonzero(sp["raw"])),
                "mtf_passed_signals": int(np.count_nonzero(sp["signal"])),
                "mtf_blocked_signals": int(np.count_nonzero(sp["blocked"])),
                "largest_bar_move_vs_stop": round(_largest_bar_move_vs_stop(candles, sp["stop"]), 3),
                "cost_distribution_min_lot_loss": _cost_distribution(
                    candles, terms["value_per_point_min_lot_broker"] or 0.0, tf
                ),
                "by_cap": per_cap,
            }
    if out_path:
        Path(out_path).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default="state/weltrade_history_cache.json.gz")
    parser.add_argument("--survey", default="state/weltrade_cost_survey.json")
    parser.add_argument("--out", default="state/weltrade_mtf_backtest.json")
    parser.add_argument("--max-bars", type=int, default=None)
    args = parser.parse_args()
    results = evaluate(args.cache, args.survey, args.out, args.max_bars)
    print(json.dumps({k: v for k, v in results.items() if k != "candidates"}, indent=2))
    for key, cell in results["candidates"].items():
        print("=" * 70)
        print(key, {kk: cell.get(kk) for kk in ("bars", "raw_signals", "mtf_passed_signals", "mtf_blocked_signals", "largest_bar_move_vs_stop")})
        if "by_cap" not in cell:
            print("  ", cell)
            continue
        print("  cost dist:", cell["cost_distribution_min_lot_loss"])
        for cap, block in cell["by_cap"].items():
            a = block["all"]
            print(f"  cap ${cap}: trades={a.get('trades')} rej_size={block['rejected_sizing']} rej_minstop={block['rejected_minstop']}")
            if a.get("trades"):
                print(f"     ALL   {a}")
                print(f"     1stH  {block['first_half']}")
                print(f"     2ndH  {block['second_half']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
