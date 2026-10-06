"""Offline canonical-engine screening; never authorizes or submits an order.

Freeze provider-pinned cached bars, separate chronological partitions, and
compare two stricter confidence gates with the unchanged canonical baseline.
Money and quantities are simulation units, not verified broker fill forecasts.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExecutionAssumptions, BacktestRiskConfiguration
from broker.types import Candle, Timeframe, TIMEFRAME_SECONDS
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.dataset import canonical_dataset_hash
from strategy.pipeline import generate_trading_signal


GATES = (75, 80, 85)


def metrics(trades):
    rs = [t.net_pnl / (t.balance_before * 0.005) for t in trades]
    if not rs:
        return {'trades': 0, 'mean_r': None, 'ci95': [None, None], 'net_simulation_pnl': 0}
    arr = np.asarray(rs)
    n, length = len(arr), max(2, round(len(arr) ** (1/3)))
    rng = np.random.default_rng(20261005)
    means = []
    for _ in range(2000):
        indices = (rng.integers(0, n, size=(int(np.ceil(n/length)), 1)) + np.arange(length)) % n
        means.append(float(arr[indices.ravel()[:n]].mean()))
    pnls = [t.net_pnl for t in trades]
    wins, losses = sum(p for p in pnls if p > 0), -sum(p for p in pnls if p < 0)
    return {'trades': n, 'mean_r': float(arr.mean()),
            'ci95': [float(x) for x in np.percentile(means, [2.5, 97.5])],
            'win_rate': sum(p > 0 for p in pnls)/n,
            'profit_factor': wins/losses if losses else None,
            'net_simulation_pnl': sum(pnls),
            'exit_reasons': dict(Counter(t.exit_reason.value for t in trades))}


def freeze(db, symbol, tf, count, now):
    step = TIMEFRAME_SECONDS[tf]
    rows = db.execute(
        'SELECT time,open,high,low,close,volume,source FROM candles '
        'WHERE provider=? AND symbol=? AND timeframe=? AND time<=? '
        'ORDER BY time DESC LIMIT ?',
        ('weltrade', symbol, tf.value, int(now.timestamp())-step, count*4),
    ).fetchall()[::-1]
    segments, current = [], []
    for row in rows:
        if current and row[0]-current[-1][0] != step:
            segments.append(current)
            current = []
        current.append(row)
    segments.append(current)
    longest = max(segments, key=lambda segment: (len(segment), segment[-1][0] if segment else 0))
    selected = longest[-count:]
    if len(selected) < 1000:
        raise ValueError('Insufficient contiguous closed history')
    candles = [Candle(time=datetime.fromtimestamp(r[0], timezone.utc), open=r[1], high=r[2],
                      low=r[3], close=r[4], volume=r[5] or 0, source=r[6]) for r in selected]
    return candles, len(segments)-1


def evaluate(df, signals, symbol, tf, begin, end, gate, spread):
    engine = BacktestEngine(100.0, symbol=symbol, timeframe=tf,
        risk=BacktestRiskConfiguration(risk_percent=0.5, minimum_confidence=75),
        execution=BacktestExecutionAssumptions(spread=spread, slippage=spread*0.5))
    for i in range(begin, end):
        engine.process_candle(i, df)
        signal = signals[i]
        if signal['confidence'] < gate:
            signal = {**signal, 'signal': 'NO_TRADE'}
        engine.queue_signal(signal, i, df)
    engine.finish(end-1, df)
    return engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path('data/historical.sqlite3'))
    parser.add_argument('--bars', type=int, default=3000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    with sqlite3.connect(Path('state/watchlist.sqlite3').resolve().as_uri()+'?mode=ro', uri=True) as db:
        pairs = db.execute('SELECT symbol,timeframe FROM watchlist ORDER BY symbol,timeframe').fetchall()
    survey_bytes = Path('state/weltrade_cost_survey.json').read_bytes()
    survey = json.loads(survey_bytes)
    costs = {row['symbol'].upper(): row['spread_price'] for row in survey['rows']}
    protocol = {'as_of': now.isoformat(), 'provider': 'weltrade', 'pairs': pairs,
        'gates': GATES, 'bars_per_pair': args.bars, 'split': '60/20/20 after 200 warmup bars',
        'selection': 'validation mean R, minimum 30 trades and positive lower CI; otherwise baseline',
        'cost_survey_hash': hashlib.sha256(survey_bytes).hexdigest(),
        'cost_survey_date': survey['generated_at'],
        'costs': 'historical surveyed fixed spread; half-spread entry slippage; double-spread stress',
        'execution_authority': 'NONE_RESEARCH_ONLY', 'risk_percent': 0.5,
        'limitations': ['Simulation units, not verified Weltrade lot sizing or account-currency forecasts',
            'Historical cost survey is stale; costs are sensitivity assumptions',
            'No observed exit slippage/commission; bar-level stop-first collision and trigger-price gaps',
            'Single position per pair; no shared portfolio/daily-cap model',
            'Previously explored cache is not a pristine untouched holdout',
            'Canonical backtest expanding indicator history differs from live rolling 500 bars']}
    (args.output/'protocol.json').write_text(json.dumps(protocol, indent=2))
    aggregate = []
    with sqlite3.connect(args.cache.resolve().as_uri()+'?mode=ro', uri=True) as db:
        for symbol, tf_name in pairs:
            tf = Timeframe(tf_name)
            native = db.execute('SELECT symbol FROM candles WHERE provider=? AND upper(symbol)=? '
                                'AND timeframe=? GROUP BY symbol ORDER BY count(*) DESC LIMIT 1',
                                ('weltrade', symbol.upper(), tf_name)).fetchone()
            try:
                if native is None or symbol.upper() not in costs:
                    raise ValueError('Provider history or cost evidence missing')
                candles, gaps = freeze(db, native[0], tf, args.bars, now)
                digest = canonical_dataset_hash(candles, symbol=symbol, timeframe=tf)
                name = symbol.replace(' ', '_')+'_'+tf_name
                (args.output/(name+'-dataset.json')).write_text(json.dumps(
                    [c.model_dump(mode='json') for c in candles], separators=(',', ':')))
                df = calculate_indicators(pd.DataFrame([c.model_dump() for c in candles]))
                signals = {}
                for i in range(200, len(df)):
                    history = df.iloc[:i+1]
                    signals[i] = generate_trading_signal(history, symbol, regime=detect_regime(history), include_details=True)
                n = len(df)-200
                first, second = 200+int(n*.6), 200+int(n*.8)
                development, validation = {}, {}
                for gate in GATES:
                    development[str(gate)] = metrics(evaluate(df, signals, symbol, tf, 200, first, gate, costs[symbol.upper()]).trades)
                    validation[str(gate)] = metrics(evaluate(df, signals, symbol, tf, first, second, gate, costs[symbol.upper()]).trades)
                eligible = [gate for gate in GATES if validation[str(gate)]['trades'] >= 30
                            and validation[str(gate)]['ci95'][0] > 0]
                selected = max(eligible, key=lambda gate: validation[str(gate)]['mean_r']) if eligible else 75
                # Selection is locked before examining the final chronological partition.
                holdout = {str(gate): metrics(evaluate(df, signals, symbol, tf, second, len(df), gate, costs[symbol.upper()]).trades)
                           for gate in sorted({75, selected})}
                stress = metrics(evaluate(df, signals, symbol, tf, second, len(df), selected, costs[symbol.upper()]*2).trades)
                report = {'symbol': symbol, 'timeframe': tf_name, 'dataset_hash': digest,
                    'start': candles[0].time.isoformat(), 'end': candles[-1].time.isoformat(),
                    'bars': len(candles), 'excluded_gaps': gaps, 'development': development,
                    'validation': validation, 'selected_gate': selected, 'holdout': holdout,
                    'stress': stress, 'signal_counts': dict(Counter(s['signal'] for s in signals.values())),
                    'decision': 'NO_LIVE_PROMOTION_UNVERIFIED_ECONOMICS_AND_PRIOR_DATA_EXPOSURE'}
                (args.output/(name+'-result.json')).write_text(json.dumps(report, indent=2, allow_nan=False))
                aggregate.append(report)
                print(json.dumps({'symbol': symbol, 'timeframe': tf_name, 'holdout': holdout, 'selected_gate': selected}), flush=True)
            except ValueError as exc:
                aggregate.append({'symbol': symbol, 'timeframe': tf_name, 'blocked': str(exc)})
                print(symbol, tf_name, 'BLOCKED', str(exc), flush=True)
            (args.output/'results.json').write_text(json.dumps(aggregate, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
