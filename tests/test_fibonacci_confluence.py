"""Causal Fibonacci anchors and filtering, with no trading authority."""
import pandas as pd

from research.fibonacci_confluence import confluence_allowed, fibonacci_context, FibonacciSignalFilter


def bullish():
    return pd.DataFrame({'high':[102,101,100,102,106,110,108,106,106],
                         'low':[100,99,98,100,103,106,104,102,103],
                         'close':[101,100,99,101,105,109,106,103,104],
                         'EMA_50':[105]*9,'EMA_200':[100]*9,'RSI_14':[65]*9,'ATR_14':[2]*9})


def test_confirmed_anchors_and_exact_fibonacci_levels():
    context = fibonacci_context(bullish())
    assert context['direction'] == 'BUY'
    assert context['low'] == 98 and context['high'] == 110
    assert context['levels']['0.5'] == 104
    assert confluence_allowed(bullish(),context,'BUY')


def test_unconfirmed_latest_peak_is_not_an_anchor():
    data = bullish().iloc[:6]
    assert fibonacci_context(data) is None


def test_future_extreme_cannot_rewrite_prior_observation():
    data = bullish()
    frozen = fibonacci_context(data)
    extended = pd.concat([data,pd.DataFrame([{**data.iloc[-1].to_dict(),'high':200,'low':1}])],ignore_index=True)
    assert fibonacci_context(extended.iloc[:len(data)]) == frozen
    assert fibonacci_context(extended) is None


def test_mirrored_bearish_confluence_is_symmetric():
    data = bullish()
    data['high'],data['low'] = 208-data['low'],208-data['high']
    data['close'] = 208-data['close']
    data['EMA_50'],data['EMA_200'],data['RSI_14'] = 103,108,35
    context = fibonacci_context(data)
    assert context['direction'] == 'SELL'
    assert confluence_allowed(data,context,'SELL')
    assert not confluence_allowed(data,context,'BUY')


def test_missing_confirmation_or_zone_cannot_allow_signal():
    data = bullish()
    context = fibonacci_context(data)
    data.loc[8,'close'] = 109
    assert not confluence_allowed(data,context,'BUY')
    data.loc[8,'close'],data.loc[8,'RSI_14'] = 104,50
    assert not confluence_allowed(data,context,'BUY')


def test_filter_preserves_wait_and_cannot_upgrade_confidence():
    intelligence = {'trend':'BULLISH','momentum':'STRONG','volatility':'HIGH',
                    'regime':'TRENDING','confidence':80,'fibonacci_confluence_allowed':False}
    signal = FibonacciSignalFilter().generate(intelligence)
    assert signal['action'] == 'WAIT'
    assert signal['confidence'] == 80
