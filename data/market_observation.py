"""Read-only market-input resolution for bounded execution cycles."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from broker.base import BrokerGateway
from broker.deriv_public_data import DerivPublicMarketData
from broker.simulation_gateway import SimulationGateway
from broker.types import Candle, ClosedMarketObservation, Timeframe, TIMEFRAME_SECONDS
from config.settings import Settings
from core.exceptions import MarketDataError
from data.historical import CandleDataSource


_DERIV_PUBLIC_SYMBOLS = {"XAUUSD": "frxXAUUSD"}


def provider_symbol_for(*, canonical_symbol: str, source: str) -> str:
    """Map a JQE canonical symbol only at the read-only provider boundary."""
    normalized = canonical_symbol.strip().upper()
    return _DERIV_PUBLIC_SYMBOLS.get(normalized, normalized) if source == "deriv_public" else normalized


@asynccontextmanager
async def resolved_market_source(
    settings: Settings,
    *,
    broker_gateway: BrokerGateway | None = None,
) -> AsyncIterator[tuple[CandleDataSource, str]]:
    """Yield a source independent of the execution gateway.

    ``deriv_public`` is unauthenticated and exposes no execution methods.
    The simulation fallback is a separate source instance, never the gateway
    that can receive an order in the same cycle.

    ``broker`` is the explicit exception for broker-native instruments such as
    Weltrade SyntX.  The caller supplies the already-connected gateway and
    this context only consumes its read-only ``get_candles`` capability; it
    does not manage the gateway lifecycle or submit orders.
    """
    if settings.market_data_source == "broker":
        if broker_gateway is None:
            raise MarketDataError("Broker market data requires the active broker gateway")
        yield broker_gateway, "broker"
        return

    if settings.market_data_source == "deriv_public":
        source: CandleDataSource = DerivPublicMarketData(
            app_id=settings.deriv_app_id, endpoint=settings.deriv_public_endpoint
        )
        source_name = "deriv_public"
    else:
        source = SimulationGateway(starting_balance=settings.account_balance)
        source_name = "simulation"
    connect = getattr(source, "connect", None)
    disconnect = getattr(source, "disconnect", None)
    if connect is not None:
        await connect()
    try:
        yield source, source_name
    finally:
        if disconnect is not None:
            await disconnect()


def closed_observations_from_candles(
    *,
    candles: list[Candle],
    canonical_symbol: str,
    provider_symbol: str,
    source: str,
    timeframe: Timeframe,
    observed_at: datetime | None = None,
) -> list[ClosedMarketObservation]:
    """Convert provider candles to only those whose full interval has elapsed.

    Providers report a candle's opening timestamp.  A candle is usable only
    when ``observed_at >= opened_at + timeframe``.  A malformed/ambiguous
    timestamp fails closed rather than being treated as an executable candle.
    """
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise MarketDataError("Market observation clock must be timezone-aware")
    duration = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    observations: list[ClosedMarketObservation] = []
    for candle in candles:
        if candle.time.tzinfo is None:
            raise MarketDataError("Provider candle timestamp is not timezone-aware")
        closed_at = candle.time.astimezone(timezone.utc) + duration
        observation = ClosedMarketObservation(
            canonical_symbol=canonical_symbol.strip().upper(),
            source=source,
            provider_symbol=provider_symbol,
            timeframe=timeframe,
            candle_opened_at=candle.time,
            closed_at=closed_at,
            open=float(candle.open),
            high=float(candle.high),
            low=float(candle.low),
            close=float(candle.close),
            volume=None if candle.volume is None else float(candle.volume),
        )
        if observation.is_closed_at(now):
            observations.append(observation)
    if not observations:
        raise MarketDataError("No provider candles are provably closed", symbol=canonical_symbol)
    return observations
