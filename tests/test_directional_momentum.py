"""Direction-relative momentum is now canonical FeatureEngine behaviour."""
import pandas as pd
import pytest

from research.directional_momentum import (
    DirectionalMomentumFeatures,
    experimental_engine,
)
from strategy.features.feature_engine import FeatureEngine
from strategy.pipeline import generate_trading_signal


def frame(trend, rsi):
    return pd.DataFrame({'open': [100.0]*30, 'high': [102.0]*30, 'low': [98.0]*30,
        'close': [100.0]*30, 'EMA_50': [101.0 if trend == 'BULLISH' else 99.0]*30,
        'EMA_200': [100.0]*30, 'RSI_14': [rsi]*30, 'ATR_14': [1.0]*30})


@pytest.mark.parametrize('trend,rsi,expected', [('BULLISH',65,'BUY'), ('BEARISH',35,'SELL')])
def test_canonical_engine_has_symmetric_aligned_signals(trend, rsi, expected):
    result = generate_trading_signal(frame(trend, rsi), 'FX Vol 20', regime='TRENDING',
                                     include_details=True)
    assert result['signal'] == expected
    assert result['confidence'] == 75  # trend 30 + aligned STRONG 30 + NORMAL 15
    assert result['trade_plan'].is_valid()


@pytest.mark.parametrize('trend,rsi', [('BULLISH',35), ('BEARISH',65)])
def test_opposing_momentum_cannot_emit_signal(trend, rsi):
    result = generate_trading_signal(frame(trend, rsi), 'FX Vol 20', regime='TRENDING')
    assert result['signal'] == 'NO_TRADE'


def test_opposing_momentum_scores_weak_and_fails_confidence_gate():
    features = FeatureEngine().analyze(frame('BEARISH', 65))
    assert features['momentum'] == 'WEAK'
    assert features['confidence'] == 55  # trend 30 + WEAK 10 + NORMAL 15


def test_missing_momentum_fails_closed_but_keeps_volatility():
    features = FeatureEngine().analyze(frame('BEARISH', float('nan')))
    assert features['momentum'] == 'UNKNOWN'
    assert features['confidence'] == 0
    assert features['volatility'] == 'NORMAL'


def test_research_shim_matches_canonical_engine_and_preserves_input():
    data = frame('BEARISH', 35)
    before = data.copy(deep=True)
    canonical = FeatureEngine().analyze(data)
    shim = DirectionalMomentumFeatures().analyze(data)
    assert shim == canonical
    pd.testing.assert_frame_equal(data, before)


def test_experimental_engine_still_builds():
    engine = experimental_engine()
    assert engine.feature_engine.__class__ is DirectionalMomentumFeatures
