"""Experimental closed-bar Fibonacci confluence, excluded from live settings.

Confirmed two-bar pivots establish a completed directional impulse. Entries
must retrace into its 38.2--61.8% band, then turn with EMA trend/RSI momentum.
ATR gives a fixed 0.15-ATR boundary tolerance. No future bars or new risk rules.
"""
from __future__ import annotations

import math

from research.directional_momentum import DirectionalMomentumFeatures
from strategy.signal_engine import SignalEngine
from strategy.strategy_engine import StrategyEngine


def fibonacci_context(df, *, lookback=100, pivot_width=2):
    """Return latest confirmed impulse and levels, using supplied closed bars."""
    bars = df.tail(lookback).reset_index(drop=True)
    if len(bars) < 2*pivot_width+3:
        return None
    values = bars[['high','low','close']].to_numpy(dtype=float)
    if not all(math.isfinite(value) for value in values.ravel()):
        return None
    highs, lows = [], []
    # Two right-hand bars must already exist; the newest potential pivots
    # cannot be used. Strict comparisons reject flat/ambiguous extrema.
    for i in range(pivot_width, len(bars)-pivot_width):
        neighbors = list(range(i-pivot_width,i)) + list(range(i+1,i+pivot_width+1))
        if all(values[i,0] > values[j,0] for j in neighbors):
            highs.append(i)
        if all(values[i,1] < values[j,1] for j in neighbors):
            lows.append(i)
    if not highs or not lows:
        return None
    end_high, end_low = highs[-1], lows[-1]
    if end_high == end_low:
        return None
    upward = end_high > end_low
    end = end_high if upward else end_low
    starts = [i for i in (lows if upward else highs) if i < end]
    if not starts:
        return None
    start = starts[-1]
    low = values[start,1] if upward else values[end,1]
    high = values[end,0] if upward else values[start,0]
    span = high-low
    if span <= 0:
        return None
    levels = {str(ratio): float(high-ratio*span if upward else low+ratio*span)
              for ratio in (0.382,0.5,0.618,0.786)}
    # A new price violation invalidates the completed impulse.
    tail = values[end+1:]
    if (upward and any(tail[:,1] < low)) or (not upward and any(tail[:,0] > high)):
        return None
    return {'direction': 'BUY' if upward else 'SELL', 'anchor_start_index': start,
            'anchor_end_index': end, 'anchor_window_size': len(bars),
            'low': float(low), 'high': float(high), 'levels': levels}


def confluence_allowed(df, context, action):
    if context is None or context['direction'] != action or len(df) < 2:
        return False
    latest, previous = df.iloc[-1], df.iloc[-2]
    atr = float(latest.get('ATR',latest.get('ATR_14',float('nan'))))
    price, previous_price = float(latest['close']),float(previous['close'])
    ema50 = float(latest.get('EMA50',latest.get('EMA_50',float('nan'))))
    ema200 = float(latest.get('EMA200',latest.get('EMA_200',float('nan'))))
    rsi = float(latest.get('RSI',latest.get('RSI_14',float('nan'))))
    if not all(math.isfinite(v) for v in (atr,price,previous_price,ema50,ema200,rsi)) or atr <= 0:
        return False
    a,b = context['levels']['0.382'],context['levels']['0.618']
    in_zone = min(a,b)-atr*.15 <= price <= max(a,b)+atr*.15
    if action == 'BUY':
        confirmed = ema50 > ema200 and rsi > 60 and price > previous_price
    elif action == 'SELL':
        confirmed = ema50 < ema200 and rsi < 40 and price < previous_price
    else:
        return False
    return bool(in_zone and confirmed)


class FibonacciSignalFilter(SignalEngine):
    def generate(self, intelligence):
        signal = super().generate(intelligence)
        if signal['action'] in ('BUY','SELL') and not intelligence.get('fibonacci_confluence_allowed',False):
            return {**signal, 'action': 'WAIT', 'reason': 'Unconfirmed Fibonacci confluence'}
        return signal


class FibonacciFeatures(DirectionalMomentumFeatures):
    def analyze(self, df):
        features = super().analyze(df)
        context = fibonacci_context(df)
        action = 'BUY' if features['trend'] == 'BULLISH' else 'SELL'
        return {**features, 'fibonacci': context,
                'fibonacci_confluence_allowed': confluence_allowed(df,context,action)}


def experimental_engine():
    return StrategyEngine(feature_engine=FibonacciFeatures(), signal_engine=FibonacciSignalFilter())
