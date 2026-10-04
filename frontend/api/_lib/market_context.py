"""Bounded market-only projection for advisory AI; excludes account data."""
from datetime import datetime, timezone
import math


def market_context(snapshot, symbol, timeframe, now=None):
    context = snapshot.get('context', {})
    candles = snapshot.get('candles', {})
    now = now or datetime.now(timezone.utc)
    try:
        observed = datetime.fromisoformat(context['market_data_observation_time'].replace('Z', '+00:00'))
        age = (now - observed).total_seconds()
        fresh = (0 <= age <= 90 and candles.get('stale') is False
                 and candles.get('degraded') is False and candles.get('market_data_source') == 'BROKER'
                 and str(candles.get('symbol', '')).upper() == symbol.upper()
                 and candles.get('timeframe') == timeframe)
    except (KeyError, ValueError, TypeError):
        fresh = False
    if not fresh:
        return {'state': 'UNAVAILABLE', 'symbol': symbol, 'timeframe': timeframe,
                'reason': 'Fresh verified market evidence unavailable. Do not infer current prices or signals.'}
    signal = snapshot.get('signal', {})
    rows = []
    for candle in candles.get('candles', [])[-8:]:
        prices = {k: candle.get(k) for k in ('open', 'high', 'low', 'close')}
        if any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in prices.values()):
            return {'state': 'UNAVAILABLE', 'symbol': symbol, 'timeframe': timeframe}
        rows.append({'time': str(candle.get('time', ''))[:40], **prices})
    if not rows:
        return {'state': 'UNAVAILABLE', 'symbol': symbol, 'timeframe': timeframe}
    return {'state': 'CURRENT', 'provider': 'weltrade', 'symbol': symbol, 'timeframe': timeframe,
            'observed_at': observed.isoformat(), 'candles': rows,
            'signal': {k: signal[k] for k in ('signal', 'confidence', 'regime', 'quality')
                       if k in signal and isinstance(signal[k], (str, int, float))},
            'decision_reasons': [r[:160] for r in signal.get('reasons', [])[:6] if isinstance(r, str)],
            'execution_authorization': 'NONE — research context only'}
