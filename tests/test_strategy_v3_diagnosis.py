from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from broker.types import Candle
from research.strategy_v3_diagnosis import (
    calculate_excursion, diagnosis_gate, excursion_record, holdout_refusal_check, path_excursion,
    state_bucket_definitions, state_labels,
)


class Trade:
    direction = "BUY"
    entry_timestamp = datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)
    exit_timestamp = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)
    entry_price = 100.0
    stop_price = 98.0
    target_price = 104.0


def candle(t, o, h, l, c):
    return Candle(time=datetime(2026, 1, 1, 0, t, tzinfo=timezone.utc), open=o, high=h, low=l, close=c, source="test")


def test_buy_excursion_and_time_to_extremes() -> None:
    result = calculate_excursion(Trade(), [candle(0, 100, 101, 99, 100), candle(15, 100, 103, 98, 102), candle(30, 102, 102, 97, 99)], 2.0)
    assert result.mfe_price == 3.0
    assert result.mae_price == 3.0
    assert result.time_to_mfe_candles == 0
    assert result.time_to_mae_candles == 1
    assert result.mfe_r == 1.5


def test_post_exit_favorable_and_adverse_moves_are_excluded() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(15, 100, 103, 98, 102),
        candle(30, 102, 102, 99, 101),
        candle(45, 101, 150, 50, 120),
    ]
    result = calculate_excursion(Trade(), candles, 2.0)
    assert result.mfe_price == 3.0
    assert result.mae_price == 2.0
    assert result.time_to_mfe_candles <= 1
    assert result.time_to_mae_candles <= 1


def test_sell_excursion_reverses_price_direction() -> None:
    Trade.direction = "SELL"
    Trade.exit_timestamp = Trade.entry_timestamp
    result = calculate_excursion(Trade(), [candle(0, 100, 101, 99, 100), candle(15, 100, 102, 96, 98)], 2.0)
    assert result.mfe_price == 4.0
    assert result.mae_price == 2.0
    Trade.direction = "BUY"
    Trade.exit_timestamp = datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)


def test_path_analysis_is_post_entry_only() -> None:
    candles = [
        candle(0, 100, 101, 99, 100), candle(15, 100, 103, 98, 102),
        candle(30, 102, 102, 99, 101),
    ]
    assert path_excursion(Trade(), candles, (1,))[1] == (3.0, 2.0)


def test_path_analysis_never_crosses_exit_boundary() -> None:
    candles = [
        candle(0, 100, 101, 99, 100), candle(15, 100, 101, 99, 100),
        candle(30, 100, 102, 98, 100), candle(45, 100, 140, 60, 100),
    ]
    assert path_excursion(Trade(), candles, (16,))[16] == (2.0, 2.0)


def test_state_labels_and_holdout_gate_are_deterministic() -> None:
    frame = pd.DataFrame({"EMA50": [100.0, 101.0], "EMA200": [100.0, 100.5], "ATR": [2.0, 2.0], "RSI": [50, 50], "close": [100.0, 101.0]})
    buckets = state_bucket_definitions([frame])
    assert state_labels(frame, 1, buckets)["ema_structure"] == "bullish"
    assert holdout_refusal_check()


def test_excursion_record_uses_last_closed_pre_entry_state() -> None:
    candles = [
        candle(0, 100, 101, 99, 100), candle(15, 100, 120, 95, 115),
        candle(30, 115, 116, 110, 112),
    ]
    frame = pd.DataFrame({
        "time": [item.time for item in candles],
        "EMA50": [99.0, 110.0, 111.0],
        "EMA200": [101.0, 105.0, 106.0],
        "ATR": [2.0, 8.0, 4.0],
        "RSI": [35.0, 75.0, 55.0],
        "close": [100.0, 115.0, 112.0],
    })
    trade = SimpleNamespace(
        trade_id=1, direction="BUY", signal_timestamp=candles[0].time,
        entry_timestamp=candles[1].time, exit_timestamp=candles[2].time,
        entry_price=100.0, stop_price=98.0, target_price=104.0,
        net_pnl=1.0, holding_candles=2,
    )
    buckets = {"trend_strength": (0.5, 1.5), "volatility": (0.03, 0.06)}
    record = excursion_record(trade, candles, frame, buckets)
    assert record["feature_timestamp"] == candles[0].time.isoformat()
    assert record["state"]["ema_structure"] == "bearish"
    assert record["state"]["recent_direction"] == "neutral"


def test_v3_gate_requires_three_windows_and_max_two_hypotheses() -> None:
    classification, proposed = diagnosis_gate([{"supporting_windows": 4, "supports_v3": False}, {"supporting_windows": 1, "supports_v3": True}])
    assert classification == "NO_CLEAR_EDGE_STRUCTURE"
    assert len(proposed) <= 2
