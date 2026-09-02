"""Tests for fixed-dataset backtesting with zero broker connectivity."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backtesting import backtest
from core.exceptions import MarketDataError


class TestModuleImport:
    def test_importing_module_has_no_side_effects(self) -> None:
        # Regression guard: backtesting/backtest.py used to be a top-level
        # script that connected to MT5 and ran a full backtest at import
        # time. Importing it now must be inert.
        assert callable(backtest.run_backtest)


class TestRunBacktest:
    async def test_raises_market_data_error_when_no_data(self) -> None:
        with pytest.raises(MarketDataError):
            await backtest.run_backtest(dataset=[])

    async def test_backtest_never_constructs_a_broker_gateway(self) -> None:
        with patch("broker.factory.get_gateway") as gateway_factory:
            with pytest.raises(MarketDataError):
                await backtest.run_backtest(dataset=[])
        gateway_factory.assert_not_called()

    async def test_rejects_non_monotonic_dataset(self) -> None:
        from datetime import datetime, timezone
        from broker.types import Candle
        candle = Candle(time=datetime(2024, 1, 1, tzinfo=timezone.utc), open=1, high=1, low=1, close=1)
        with pytest.raises(MarketDataError):
            await backtest.run_backtest(dataset=[candle, candle])

    async def test_cache_backtest_requires_explicit_provider(self, tmp_path) -> None:
        from broker.types import Timeframe
        from data.storage import CandleStore

        with pytest.raises(MarketDataError, match="provider is required"):
            await backtest.run_backtest(
                store=CandleStore(tmp_path / "provider-required.sqlite3"),
                timeframe=Timeframe.M15,
            )

    async def test_canonical_runner_never_uses_legacy_execute_trade(self) -> None:
        from datetime import datetime, timedelta, timezone
        from broker.types import Candle, Timeframe

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        candles = [
            Candle(
                time=start + timedelta(minutes=15 * i), open=100 + i,
                high=102 + i, low=99 + i, close=101 + i,
                source="canonical-fixture",
            )
            for i in range(205)
        ]
        with patch.object(
            backtest.BacktestEngine,
            "execute_trade",
            side_effect=AssertionError("legacy shim must not be called"),
        ) as legacy:
            await backtest.run_backtest(
                symbol="XAUUSD", timeframe=Timeframe.M15,
                dataset=candles, provider="canonical-fixture",
            )
        legacy.assert_not_called()

@pytest.mark.asyncio
async def test_candle_store_backtest_is_deterministic(tmp_path) -> None:
    """Persisted canonical candles produce identical repeated backtests."""
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.storage import CandleStore

    symbol = "XAUUSD"
    timeframe = Timeframe.M15
    store = CandleStore(tmp_path / "backtest-candles.sqlite3")

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    persisted = []

    # More than the runner's 200-candle indicator warmup.
    for i in range(260):
        base = 2600.0 + (i * 0.25)

        persisted.append(
            Candle(
                time=start + timedelta(minutes=15 * i),
                open=base,
                high=base + 1.0,
                low=base - 1.0,
                close=base + 0.20,
                volume=None,
                source="deterministic-test",
            )
        )

    saved = store.save_candles(symbol, timeframe, persisted)

    assert saved == 260
    assert store.count(symbol, timeframe) == 260

    first = await backtest.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        candles=260,
        starting_balance=50.0,
        store=store,
        provider="deterministic-test",
    )

    second = await backtest.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        candles=260,
        starting_balance=50.0,
        store=store,
        provider="deterministic-test",
    )

    assert first.statistics() == second.statistics()
    assert first.trades == second.trades
    assert first.equity_curve == second.equity_curve
    assert first.balance == second.balance

@pytest.mark.asyncio
async def test_backtest_accepts_matching_frozen_manifest() -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest

    symbol = "XAUUSD"
    timeframe = Timeframe.M15
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    candles = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i * 0.25,
            high=2601.0 + i * 0.25,
            low=2599.0 + i * 0.25,
            close=2600.2 + i * 0.25,
            volume=None,
            source="frozen-test",
        )
        for i in range(260)
    ]

    manifest = build_dataset_manifest(
        candles,
        provider="fixture",
        source="frozen backtest fixture",
        provider_symbol="fixture-XAUUSD",
        canonical_symbol=symbol,
        timeframe=timeframe,
        retrieved_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    engine = await backtest.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        candles=len(candles),
        dataset=candles,
        manifest=manifest,
    )

    assert engine is not None


@pytest.mark.asyncio
async def test_backtest_rejects_dataset_that_does_not_match_manifest() -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest

    symbol = "XAUUSD"
    timeframe = Timeframe.M15
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    original = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="frozen-test",
        )
        for i in range(260)
    ]

    manifest = build_dataset_manifest(
        original,
        provider="fixture",
        source="frozen backtest fixture",
        provider_symbol="fixture-XAUUSD",
        canonical_symbol=symbol,
        timeframe=timeframe,
    )

    modified = list(original)
    target = modified[100]
    modified[100] = Candle(
        time=target.time,
        open=target.open,
        high=target.high,
        low=target.low,
        close=target.close + 0.01,
        volume=target.volume,
        source=target.source,
    )

    with pytest.raises(MarketDataError):
        await backtest.run_backtest(
            symbol=symbol,
            timeframe=timeframe,
            dataset=modified,
            manifest=manifest,
        )


@pytest.mark.asyncio
async def test_manifest_mismatch_fails_before_indicator_or_strategy_evaluation() -> None:
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import build_dataset_manifest

    symbol = "XAUUSD"
    timeframe = Timeframe.M15
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    original = [
        Candle(
            time=start + timedelta(minutes=15 * i),
            open=2600.0 + i,
            high=2601.0 + i,
            low=2599.0 + i,
            close=2600.5 + i,
            volume=None,
            source="frozen-test",
        )
        for i in range(260)
    ]

    manifest = build_dataset_manifest(
        original,
        provider="fixture",
        source="frozen backtest fixture",
        provider_symbol="fixture-XAUUSD",
        canonical_symbol=symbol,
        timeframe=timeframe,
    )

    modified = list(original)
    target = modified[50]
    modified[50] = Candle(
        time=target.time,
        open=target.open,
        high=target.high,
        low=target.low,
        close=target.close + 0.01,
        volume=target.volume,
        source=target.source,
    )

    with (
        patch("backtesting.backtest.calculate_indicators") as indicators,
        patch("backtesting.backtest.generate_trading_signal") as strategy,
    ):
        with pytest.raises(MarketDataError):
            await backtest.run_backtest(
                symbol=symbol,
                timeframe=timeframe,
                dataset=modified,
                manifest=manifest,
            )

    indicators.assert_not_called()
    strategy.assert_not_called()

@pytest.mark.asyncio
async def test_frozen_dataset_bundle_reproduces_backtest(tmp_path) -> None:
    """Exported and reloaded frozen candles reproduce the original backtest."""
    from datetime import datetime, timedelta, timezone

    from broker.types import Candle, Timeframe
    from data.dataset import (
        build_dataset_manifest,
        export_dataset_bundle,
        load_dataset_bundle,
    )

    symbol = "XAUUSD"
    timeframe = Timeframe.M15
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    candles = []
    for i in range(260):
        base = 2600.0 + (i * 0.25)
        candles.append(
            Candle(
                time=start + timedelta(minutes=15 * i),
                open=base,
                high=base + 1.0,
                low=base - 1.0,
                close=base + 0.20,
                volume=None,
                source="reproducibility-fixture",
            )
        )

    manifest = build_dataset_manifest(
        candles,
        provider="fixture",
        source="reproducibility fixture",
        provider_symbol="fixture-XAUUSD",
        canonical_symbol=symbol,
        timeframe=timeframe,
        retrieved_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )

    original = await backtest.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        candles=len(candles),
        starting_balance=50.0,
        dataset=candles,
        manifest=manifest,
    )

    bundle = tmp_path / "XAUUSD_M15_frozen"
    export_dataset_bundle(bundle, candles, manifest)

    loaded_candles, loaded_manifest = load_dataset_bundle(bundle)

    replay = await backtest.run_backtest(
        symbol=symbol,
        timeframe=timeframe,
        candles=len(loaded_candles),
        starting_balance=50.0,
        dataset=loaded_candles,
        manifest=loaded_manifest,
    )

    assert loaded_candles == candles
    assert loaded_manifest == manifest

    assert replay.statistics() == original.statistics()
    assert replay.trades == original.trades
    assert replay.equity_curve == original.equity_curve
    assert replay.balance == original.balance
