from datetime import datetime, timedelta, timezone

import pytest

from broker.types import Candle, Timeframe
from data.storage import CandleStore
from research.experiments import ExperimentCatalog
from research.simulation_session import run_cached_simulation_experiment


def candles(count: int = 260) -> list[Candle]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    values = []
    price = 100.0
    for index in range(count):
        price += 0.15 if index % 3 else -0.05
        values.append(Candle(
            time=start + timedelta(minutes=15 * index), open=price,
            high=price + 2.0, low=max(0.01, price - 2.0), close=price + 0.1,
            volume=100.0, source="fixture",
        ))
    return values


@pytest.mark.asyncio
async def test_simulation_experiment_is_offline_deterministic_and_cataloged(tmp_path, monkeypatch):
    store = CandleStore(tmp_path / "candles.db")
    store.save_candles("XAUUSD", Timeframe.M15, candles(), provider="fixture")
    catalog = ExperimentCatalog(tmp_path / "experiments")
    observed_history_lengths = []

    def signal(history, symbol, regime=None, include_details=False):
        observed_history_lengths.append(len(history))
        return {"signal": "NO_TRADE", "confidence": 0, "symbol": symbol, "reasons": []}

    monkeypatch.setattr("backtesting.backtest.generate_trading_signal", signal)
    first = await run_cached_simulation_experiment(store=store, catalog=catalog)
    second = await run_cached_simulation_experiment(store=store, catalog=catalog)

    assert first.result.initial_capital == 50.0
    assert first.result.result_hash == second.result.result_hash
    assert first.experiment.experiment_id == second.experiment.experiment_id
    assert first.experiment.configuration["execution_mode"] == "SIMULATION"
    assert first.experiment.configuration["starting_balance"] == {"amount": 50.0, "currency": "USD"}
    assert first.experiment.metrics["Cost Model Status"] == "COST_MODEL_INCOMPLETE"
    assert catalog.load(first.experiment.experiment_id).result_hash == first.result.result_hash
    assert observed_history_lengths
    assert max(observed_history_lengths) <= len(candles())


@pytest.mark.asyncio
async def test_simulation_experiment_fails_closed_without_cached_history(tmp_path):
    store = CandleStore(tmp_path / "empty.db")
    with pytest.raises(ValueError, match="No locally cached historical dataset"):
        await run_cached_simulation_experiment(store=store, catalog=ExperimentCatalog(tmp_path / "experiments"))
