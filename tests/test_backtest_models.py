from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from backtesting.engine import BacktestEngine
from backtesting.models import BacktestExitReason
from broker.types import Candle, Timeframe
from data.storage import CandleStore


def _frame() -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return pd.DataFrame({
        "time": [start + timedelta(minutes=15 * i) for i in range(4)],
        "open": [100.0, 101.0, 101.0, 101.0],
        "high": [100.5, 104.0, 101.5, 101.5],
        "low": [99.5, 100.5, 100.5, 100.5],
        "close": [100.0, 103.0, 101.0, 101.0],
        "ATR": [1.0] * 4,
        "spread": [0.0] * 4,
    })


def test_event_engine_enters_at_next_candle_open_and_uses_typed_quantity() -> None:
    frame = _frame()
    engine = BacktestEngine(starting_balance=1000.0, symbol="XAUUSD", timeframe=Timeframe.M15)
    engine.queue_signal({"signal": "BUY", "confidence": 90}, 0, frame)
    engine.process_candle(0, frame)
    assert not engine.trades
    engine.process_candle(1, frame)
    assert engine.trades[0].entry_price == 101.0
    assert engine.trades[0].quantity.unit.value == "SIMULATION_UNITS"
    assert engine.trades[0].exit_reason is BacktestExitReason.TAKE_PROFIT


def test_provider_is_part_of_candle_cache_identity(tmp_path) -> None:
    candle = Candle(
        time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=1.0, high=2.0, low=0.5, close=1.5, source="public",
    )
    store = CandleStore(tmp_path / "history.sqlite3")
    assert store.save_candles("XAUUSD", Timeframe.M15, [candle], provider="public") == 1
    other = candle.model_copy(update={"source": "other"})
    assert store.save_candles("XAUUSD", Timeframe.M15, [other], provider="other") == 1
    assert store.count("XAUUSD", Timeframe.M15, provider="public") == 1
    assert store.count("XAUUSD", Timeframe.M15, provider="other") == 1

    conflict = candle.model_copy(update={"close": 1.6})
    with pytest.raises(Exception):
        store.save_candles("XAUUSD", Timeframe.M15, [conflict], provider="public")
