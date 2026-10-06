"""Frozen follow-up experiment on existing datasets; no broker calls or orders."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from broker.types import Candle, Timeframe
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.dataset import canonical_dataset_hash
from research.directional_momentum import experimental_engine
from strategy.pipeline import generate_trading_signal
from strategy.strategy_engine import StrategyEngine
from tools.audit_engine_expectancy import evaluate, metrics


def summary(engine, evaluated_bars):
    result = metrics(engine.trades)
    peak, drawdown = 100.0, 0.0
    for balance in engine.equity_curve:
        peak = max(peak, balance)
        drawdown = max(drawdown, (peak-balance)/peak*100)
    result['maximum_realized_drawdown_percent'] = drawdown
    result['exposure_fraction'] = sum(t.holding_candles for t in engine.trades)/evaluated_bars
    result['decisions'] = dict(Counter(d.state for d in engine.decisions))
    result['directions'] = dict(Counter(t.direction for t in engine.trades))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--datasets', type=Path, default=Path('reports/engine-expectancy-20261005'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--with-fibonacci', action='store_true', help='Freeze an additional Fibonacci confluence candidate')
    parser.add_argument('--reference', type=Path, help='Reuse matching completed baseline/directional comparisons')
    parser.add_argument('--reuse-completed', type=Path, help='Reuse available completed pairs; evaluate missing pairs normally')
    args = parser.parse_args()
    if args.reference and args.reuse_completed:
        parser.error('Choose one reference mode')
    if args.reference and not args.with_fibonacci:
        parser.error('--reference requires --with-fibonacci')
    args.output.mkdir(parents=True, exist_ok=False)
    previous = json.loads((args.datasets/'results.json').read_text())
    survey_path = Path('state/weltrade_cost_survey.json')
    survey_bytes = survey_path.read_bytes()
    survey = json.loads(survey_bytes)
    spreads = {row['symbol'].upper(): row['spread_price'] for row in survey['rows']}
    variants = {'baseline': StrategyEngine(), 'directional_momentum': experimental_engine()}
    if args.with_fibonacci:
        from research.fibonacci_confluence import experimental_engine as fibonacci_engine
        variants['fibonacci_confluence'] = fibonacci_engine()
        if args.reference:
            variants = {'fibonacci_confluence': variants['fibonacci_confluence']}
    code_paths = ('research/directional_momentum.py', 'tools/test_directional_momentum.py',
                  'strategy/pipeline.py', 'strategy/strategy_engine.py', 'backtesting/engine.py')
    if args.with_fibonacci:
        code_paths += ('research/fibonacci_confluence.py',)
    protocol = {'created_at': datetime.now(timezone.utc).isoformat(),
        'hypothesis': 'RSI momentum aligned with bullish or bearish trend improves net expectancy',
        'variants': list(variants), 'risk_percent': 0.5, 'confidence_floor': 75,
        'indicator_window': 500, 'folds': 'three chronological independent forward blocks after 500 warmup bars',
        'costs': 'historical fixed spread plus half-spread entry slippage; double-spread stress',
        'cost_survey_date': survey['generated_at'],
        'cost_survey_hash': hashlib.sha256(survey_bytes).hexdigest(),
        'screening_rule': 'candidate >=30 trades, positive lower CI and positive mean in all three blocks; stress lower CI positive',
        'trial_count': len(previous)*(len(variants) if args.reference else len(variants)-1), 'execution_authority': 'NONE_RESEARCH_ONLY',
        'reused_reference': str(args.reference) if args.reference else None,
        'reused_completed_reference': str(args.reuse_completed) if args.reuse_completed else None,
        'fibonacci_definition': ('100-bar window; strict confirmed two-bar swing pivots; 38.2--61.8% zone; '
            '0.15 ATR tolerance; EMA50/200, RSI >60/<40, closing-price turn; no changed stop/risk') if args.with_fibonacci else None,
        'code_hashes': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in code_paths},
        'limitations': ['Dataset was already exposed: this is diagnostic follow-up, not pristine confirmation',
            'Simulated quantities and P&L; no verified lot/margin feasibility or portfolio/daily-limit model',
            'Stale cost survey; no observed exit slippage/commission; trigger-price gaps and 19-bar timeout',
            '500-bar indicators mirror live window; historical fills still differ from live execution']}
    (args.output/'protocol.json').write_text(json.dumps(protocol, indent=2))
    results = []
    for original in previous:
        symbol, tf = original['symbol'], Timeframe(original['timeframe'])
        name = symbol.replace(' ', '_')+'_'+tf.value
        raw = (args.datasets/(name+'-dataset.json')).read_bytes()
        candles = [Candle.model_validate(c) for c in json.loads(raw)]
        digest = canonical_dataset_hash(candles, symbol=symbol, timeframe=tf)
        if digest != original['dataset_hash']:
            raise ValueError('Frozen dataset hash mismatch')
        base = pd.DataFrame([c.model_dump() for c in candles])
        comparisons, traces = {}, {}
        reference_hash = None
        reference_directory = args.reference or args.reuse_completed
        reference_file = reference_directory/(name+'-result.json') if reference_directory else None
        if reference_file and (args.reference or reference_file.exists()):
            reference_bytes = reference_file.read_bytes()
            reference = json.loads(reference_bytes)
            reference_protocol = json.loads((reference_directory/'protocol.json').read_text())
            if (reference['dataset_hash'] != digest or reference_protocol['indicator_window'] != 500
                    or reference_protocol['risk_percent'] != 0.5 or reference_protocol['confidence_floor'] != 75
                    or reference_protocol['cost_survey_hash'] != protocol['cost_survey_hash']):
                raise ValueError('Reference assumptions or dataset mismatch')
            for path in ('research/directional_momentum.py','strategy/pipeline.py',
                         'strategy/strategy_engine.py','backtesting/engine.py'):
                if reference_protocol['code_hashes'][path] != protocol['code_hashes'][path]:
                    raise ValueError('Reference strategy/engine code mismatch')
            comparisons.update(reference['comparisons'])
            reference_hash = hashlib.sha256(reference_bytes).hexdigest()
        active_variants = {v:engine for v,engine in variants.items() if v not in comparisons}
        # ATR stored for simulated sizing comes from the same causal rolling window.
        frame = base.copy()
        frame['ATR'] = float('nan')
        signals = {variant: {} for variant in active_variants}
        for i in range(499, len(base)):
            history = calculate_indicators(base.iloc[i-499:i+1])
            frame.loc[i, 'ATR'] = float(history.iloc[-1]['ATR'])
            regime = detect_regime(history)
            for variant, engine in active_variants.items():
                signals[variant][i] = generate_trading_signal(history, symbol, regime=regime,
                                                               engine=engine, include_details=True)
        boundaries = [499+int((len(base)-499)*fraction/3) for fraction in range(4)]
        for variant in active_variants:
            folds, stress_folds, trades, stressed = [], [], [], []
            traces[variant] = []
            for begin, end in zip(boundaries, boundaries[1:]):
                engine = evaluate(frame, signals[variant], symbol, tf, begin, end, 75, spreads[symbol])
                stress = evaluate(frame, signals[variant], symbol, tf, begin, end, 75, spreads[symbol]*2)
                folds.append(summary(engine, end-begin))
                stress_folds.append(summary(stress, end-begin))
                trades.extend(engine.trades)
                stressed.extend(stress.trades)
                traces[variant].append([asdict(trade) for trade in engine.trades])
            comparisons[variant] = {'folds': folds, 'aggregate': metrics(trades),
                'stress_folds': stress_folds, 'stress_aggregate': metrics(stressed),
                'signals': dict(Counter(s['signal'] for s in signals[variant].values()))}
        qualifications = {}
        for variant in variants:
            if variant == 'baseline':
                continue
            candidate = comparisons[variant]
            qualifies = (candidate['aggregate']['trades'] >= 30
                     and candidate['aggregate']['ci95'][0] > 0
                     and all(f['mean_r'] is not None and f['mean_r'] > 0 for f in candidate['folds'])
                     and candidate['stress_aggregate']['trades'] >= 30
                     and candidate['stress_aggregate']['ci95'][0] > 0)
            qualifications[variant] = bool(qualifies)
        record = {'symbol': symbol, 'timeframe': tf.value, 'dataset_hash': digest,
                  'dataset_file_sha256': hashlib.sha256(raw).hexdigest(),
                  'reference_result_sha256': reference_hash,
                  'bars': len(base), 'comparisons': comparisons,
                  'screen_qualified': qualifications,
                  'live_promotion': 'BLOCKED_UNVERIFIED_ECONOMICS_AND_EXPOSED_DATA'}
        (args.output/(name+'-trades.json')).write_text(json.dumps(traces, default=str, indent=2))
        (args.output/(name+'-result.json')).write_text(json.dumps(record, indent=2, allow_nan=False))
        results.append(record)
        (args.output/'results.json').write_text(json.dumps(results, indent=2, allow_nan=False))
        print(json.dumps({'pair': name, 'candidates': {v:comparisons[v]['aggregate'] for v in qualifications},
                          'screen_qualified': qualifications}), flush=True)


if __name__ == '__main__':
    main()
