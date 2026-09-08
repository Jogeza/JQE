from datetime import datetime, timedelta, timezone

from broker.types import Candle
from research.signal_diagnostics import diagnose_signals


def series(count=240):
    return [Candle(time=datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(minutes=15*i),
        open=100+i*.1, high=101+i*.1, low=99+i*.1, close=100.5+i*.1,
        volume=None, source="test") for i in range(count)]


def test_signal_diagnostics_are_deterministic_and_bounded():
    first = diagnose_signals(series())
    second = diagnose_signals(series())
    assert first == second
    assert first.evaluations == 40
    assert sum(first.regime_counts.values()) == 40
    assert first.buy_signals + first.sell_signals + first.no_signal == 40
    assert sum(first.reason_counts.values()) == first.no_signal
    assert all(stats["valid"] + stats["missing"] == 40 for stats in first.indicator_sanity.values())


def test_bearish_trending_rsi_below_40_does_not_emit_sell():
    candles = series()
    # Reverse the real price direction while retaining valid OHLC values.
    falling = [candle.model_copy(update={
        "open": 200-(i*.2), "high": 201-(i*.2),
        "low": 199-(i*.2), "close": 199.5-(i*.2),
    }) for i, candle in enumerate(candles)]
    result = diagnose_signals(falling)
    assert result.sell_signals == 0
    assert result.reason_counts["BEARISH_MOMENTUM_NOT_STRONG"] > 0
