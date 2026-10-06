"""Direction-aware research does not mutate the default live feature engine."""
import pandas as pd
import pytest

from research.directional_momentum import DirectionalMomentumFeatures, experimental_engine
from strategy.features.feature_engine import FeatureEngine
from strategy.pipeline import generate_trading_signal


def frame(trend, rsi):
    return pd.DataFrame({'open': [100.0]*30, 'high': [102.0]*30, 'low': [98.0]*30,
        'close': [100.0]*30, 'EMA_50': [101.0 if trend == 'BULLISH' else 99.0]*30,
        'EMA_200': [100.0]*30, 'RSI_14': [rsi]*30, 'ATR_14': [1.0]*29+[2.0]})


@pytest.mark.parametrize('trend,rsi,expected', [('BULLISH',65,'BUY'), ('BEARISH',35,'SELL')])
def test_canonical_injected_candidate_has_symmetric_aligned_signals(trend, rsi, expected):
    result = generate_trading_signal(frame(trend,rsi), 'FX Vol 20', regime='TRENDING',
                                     engine=experimental_engine(), include_details=True)
    assert result['signal'] == expected
    assert result['confidence'] == 80
    assert result['trade_plan'].is_valid()


@pytest.mark.parametrize('trend,rsi', [('BULLISH',35), ('BEARISH',65)])
def test_opposing_momentum_cannot_emit_candidate_signal(trend, rsi):
    result = generate_trading_signal(frame(trend,rsi), 'FX Vol 20', regime='TRENDING',
                                     engine=experimental_engine())
    assert result['signal'] == 'NO_TRADE'


def test_experiment_does_not_change_default_features_or_input():
    data = frame('BEARISH',35)
    before = data.copy(deep=True)
    assert FeatureEngine().analyze(data)['momentum'] == 'WEAK'
    assert DirectionalMomentumFeatures().analyze(data)['momentum'] == 'STRONG'
    assert FeatureEngine().analyze(data)['momentum'] == 'WEAK'
    pd.testing.assert_frame_equal(data,before)


def test_missing_momentum_fails_closed():
    result = DirectionalMomentumFeatures().analyze(frame('BEARISH',float('nan')))
    assert result['confidence'] == 0
    assert result['momentum'] == 'UNKNOWN'
