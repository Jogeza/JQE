"""Offline baseline audit, invoked only by the canonical backtest CLI.

No candidate search or alternate signal implementation lives here. Missing
terminal economics are explicitly unavailable, never inferred from OHLC.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path

import numpy as np

from backtesting.models import BacktestExecutionAssumptions
from broker.weltrade_symbols import require_weltrade_synthetic
from data.dataset import load_dataset_bundle


def eligibility(candles, manifest):
    """Fail closed on provider and closed-bar provenance; gaps stay unfilled."""
    require_weltrade_synthetic(manifest.canonical_symbol)
    if manifest.provider != "weltrade" or manifest.provider_symbol != manifest.canonical_symbol:
        return "Provider or exact native symbol mismatch"
    step = timedelta(seconds=manifest.granularity_seconds)
    if any(c.time + step > manifest.retrieved_at for c in candles):
        return "Bar closes after manifest retrieval time; closed-bar provenance unverified"
    if len(candles) < 400:
        return "Insufficient bars for warmup and chronological split"
    return None


def summarize(engine, candles, start, end):
    trades = engine.trades
    observations = {o.timestamp: o for o in engine.result.indicators}
    indices = {c.time: i for i, c in enumerate(candles)}
    rows = []
    for t in trades:
        distance = abs(t.entry_price - t.stop_price)
        segment = candles[indices[t.entry_timestamp]:indices[t.exit_timestamp] + 1]
        # Full exit-bar extremes are upper bounds: OHLC cannot order extrema
        # relative to an intrabar exit. Never call these realized excursions.
        if t.direction == "BUY":
            mae = max(0, t.entry_price - min(c.low for c in segment)) / distance
            mfe = max(0, max(c.high for c in segment) - t.entry_price) / distance
        else:
            mae = max(0, max(c.high for c in segment) - t.entry_price) / distance
            mfe = max(0, t.entry_price - min(c.low for c in segment)) / distance
        o = observations[t.signal_timestamp]
        signal = candles[indices[t.signal_timestamp]]
        rows.append({**asdict(t), "net_r": t.net_pnl / (distance * t.quantity.value),
                     "mae_r_upper_bound": mae, "mfe_r_upper_bound": mfe,
                     "regime": o.regime, "rsi": o.rsi,
                     "ema_distance_atr": abs(signal.close - o.ema50) / o.atr,
                     "entry_gap_atr": abs(t.entry_price - signal.close) / o.atr})
    pnl = [t.net_pnl for t in trades]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p < 0]
    returns = np.array([t.net_pnl / t.balance_before for t in trades])
    downside = np.minimum(returns, 0)
    def distribution(key):
        return dict(zip(("p10", "p50", "p90"), map(float, np.quantile([r[key] for r in rows], [.1, .5, .9])))) if rows else None
    clusters = defaultdict(list)
    for row in rows:
        key = f"{row['regime']}|{row['direction']}|{'extended>=2ATR' if row['ema_distance_atr'] >= 2 else 'near<2ATR'}"
        clusters[key].append(row["net_r"])
    n = len(trades)
    return {
        "trades": n, "expectancy_account_currency": None,
        "expectancy_simulation_cash": float(np.mean(pnl)) if n else None,
        "expectancy_r": float(np.mean([r['net_r'] for r in rows])) if n else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "win_rate_percent": 100 * len(wins) / n if n else None,
        "average_win_simulation_cash": float(np.mean(wins)) if wins else None,
        "average_loss_simulation_cash": float(np.mean(losses)) if losses else None,
        "max_realized_drawdown_simulation_cash": engine.result.maximum_drawdown,
        "max_realized_drawdown_percent": engine.result.maximum_drawdown_percent,
        "sharpe_unannualized_trade_returns": float(returns.mean() / returns.std(ddof=1)) if n > 1 and returns.std(ddof=1) > 0 else None,
        "sortino_unannualized_trade_returns": float(returns.mean() / np.sqrt(np.mean(downside**2))) if n and np.any(downside) else None,
        "exposure_bar_fraction": sum(t.holding_candles for t in trades) / (end - start),
        "holding_bars": distribution("holding_candles"),
        "mae_r_upper_bound": distribution("mae_r_upper_bound"),
        "mfe_r_upper_bound": distribution("mfe_r_upper_bound"),
        "decision_states": dict(Counter(d.state for d in engine.decisions)),
        "clusters": {k: {"trades": len(v), "losses": sum(x < 0 for x in v), "mean_r": float(np.mean(v))} for k, v in clusters.items()},
        "trade_details": rows,
    }


async def audit_baseline(output: Path, runner):
    output.mkdir(parents=True, exist_ok=False)
    from core.logger import logger
    logger.remove()
    logger.add(output / "backtest.log", level="WARNING")
    costs = {
        "existing_zero_cost": BacktestExecutionAssumptions(),
        "illustrative_cost": BacktestExecutionAssumptions(spread_atr_fraction=.10, adverse_slippage_atr_fraction=.05, fee_per_trade=.01),
        "double_spread_commission": BacktestExecutionAssumptions(spread_atr_fraction=.20, adverse_slippage_atr_fraction=.05, fee_per_trade=.02),
    }
    protocol = {"strategy_configurations_tried": 1, "candidate_configurations_tried": 0,
                "split": "floor(70% of bars) train / remaining test; 200-bar warmup; flat at boundary",
                "costs": {k: asdict(v) for k, v in costs.items()},
                "currency": "SIMULATION CASH ONLY; terminal contract economics and costs unavailable",
                "universe": "All frozen data/bundles/*_M5; M1 excluded by predeclared timeframe",
                "protocol_revision": "First provenance-only pass rejected gaps; before any replay, allow disclosed unfilled gaps. No strategy outcomes inspected.",
                "promotion": "Blocked without verified closed-bar provenance, terminal economics, costs and adequate untouched samples"}
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2, default=str), encoding="utf-8")
    evidence = []
    for path in sorted(Path("data/bundles").glob("*_M5")):
        candles, manifest = load_dataset_bundle(path)
        step = timedelta(seconds=manifest.granularity_seconds)
        gaps = [{"after_index": i, "elapsed_seconds": (b.time-a.time).total_seconds()}
                for i, (a, b) in enumerate(zip(candles, candles[1:])) if b.time-a.time != step]
        record = {"bundle": str(path), "manifest": asdict(manifest), "gaps": gaps,
                  "exclusion": eligibility(candles, manifest), "runs": []}
        if record["exclusion"] is None:
            split = int(len(candles) * .7)
            for partition, start, end in (("train_diagnostic", 200, split), ("test", split, len(candles))):
                for cost_name, assumptions in costs.items():
                    engine = await runner(symbol=manifest.canonical_symbol, timeframe=manifest.timeframe,
                                          dataset=candles, manifest=manifest, provider=manifest.provider,
                                          execution_assumptions=assumptions, start_index=start, end_index=end)
                    record["runs"].append({"partition": partition, "cost": cost_name,
                        "start_index": start, "end_index_exclusive": end,
                        "first_signal_bar": candles[start].time, "last_signal_bar": candles[end-1].time,
                        "run_fingerprint": engine.result.run_fingerprint,
                        "metrics": summarize(engine, candles, start, end)})
        evidence.append(record)
        (output / "baseline.json").write_text(json.dumps(evidence, indent=2, default=str, allow_nan=False), encoding="utf-8")
        print(f"{path.name}: {record['exclusion'] or 'baseline complete'}", flush=True)
