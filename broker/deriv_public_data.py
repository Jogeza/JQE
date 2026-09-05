"""Unauthenticated read-only Deriv public market-data adapter."""

from __future__ import annotations

import asyncio
import itertools
import json
import math
from datetime import datetime, timezone
from typing import Any

import websockets

from broker.types import Candle, Timeframe, TIMEFRAME_SECONDS
from core.exceptions import BrokerConnectionError, MarketDataError


DEFAULT_ENDPOINT = "wss://api.derivws.com/trading/v1/options/ws/public"
_REQUEST_TIMEOUT_SECONDS = 10.0


class DerivPublicMarketData:
    """Read-only public Deriv market data.

    This adapter has no API token, account methods, or execution methods.
    """

    def __init__(
        self,
        app_id: str = "",
        endpoint: str = DEFAULT_ENDPOINT,
        request_timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.app_id = app_id
        self.endpoint = endpoint
        self._request_timeout = request_timeout
        self._connection = None
        self._reader_task: asyncio.Task[None] | None = None
        self._connected = False
        self._request_ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def __aenter__(self) -> "DerivPublicMarketData":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        try:
            self._connection = await websockets.connect(self.endpoint)
        except Exception as exc:
            raise BrokerConnectionError(
                "Failed to connect to Deriv public market data",
                endpoint=self.endpoint,
            ) from exc

        self._reader_task = asyncio.create_task(self._read_loop())
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

        if self._connection is not None:
            await self._connection.close()
            self._connection = None

        for future in self._pending.values():
            if not future.done():
                future.set_exception(
                    BrokerConnectionError("Deriv public connection closed")
                )
        self._pending.clear()

    async def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int,
        end: datetime | None = None,
        start: datetime | None = None,
    ) -> list[Candle]:
        if not self._connected:
            raise BrokerConnectionError("Deriv public market data is not connected")

        if count <= 0:
            raise MarketDataError("Candle count must be positive", count=count)
        if (start is not None and start.tzinfo is None) or (end is not None and end.tzinfo is None):
            raise MarketDataError("Historical candle bounds must be timezone-aware")

        request = {
            "ticks_history": symbol,
            "style": "candles",
            "granularity": TIMEFRAME_SECONDS[timeframe],
            "count": count,
            "end": int(end.timestamp()) if end is not None else "latest",
        }
        if start is not None:
            request = {**request, "start": int(start.timestamp())}
        response = await self._request(request)

        if response.get("error"):
            error = response["error"]
            reason = error.get("message") if isinstance(error, dict) else str(error)
            raise MarketDataError(
                "Failed to retrieve Deriv public candle history",
                symbol=symbol,
                reason=reason,
            )

        candles = response.get("candles", [])
        if not isinstance(candles, list):
            raise MarketDataError(
                "Malformed Deriv public candle response",
                symbol=symbol,
            )
        if not candles:
            raise MarketDataError("Deriv public candle response was empty", symbol=symbol)

        result: list[Candle] = []
        seen: set[datetime] = set()
        for raw in candles:
            if not isinstance(raw, dict):
                raise MarketDataError("Malformed Deriv public candle", symbol=symbol)
            required = ("epoch", "open", "high", "low", "close")
            if any(field not in raw for field in required):
                raise MarketDataError("Deriv public candle is missing required fields", symbol=symbol)
            try:
                if any(isinstance(raw[field], bool) for field in required):
                    raise ValueError("boolean candle field")
                timestamp = datetime.fromtimestamp(float(raw["epoch"]), tz=timezone.utc)
                values = {field: float(raw[field]) for field in required[1:]}
            except (TypeError, ValueError, OverflowError, OSError) as exc:
                raise MarketDataError("Malformed Deriv public candle values", symbol=symbol) from exc
            if not all(math.isfinite(value) and value > 0 for value in values.values()):
                raise MarketDataError("Deriv public candle values must be positive and finite", symbol=symbol)
            if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]) or values["high"] < values["low"]:
                raise MarketDataError("Deriv public candle OHLC invariants failed", symbol=symbol)
            if timestamp in seen:
                raise MarketDataError("Deriv public candle timestamps contain duplicates", symbol=symbol)
            seen.add(timestamp)
            result.append(Candle(time=timestamp, **values, volume=None, source="deriv"))
        result.sort(key=lambda candle: candle.time)
        if any(current.time <= previous.time for previous, current in zip(result, result[1:])):
            raise MarketDataError("Deriv public candle timestamps are not monotonic", symbol=symbol)
        return result

    async def get_active_symbols(self) -> dict[str, Any]:
        """Return the unauthenticated current public catalogue payload."""
        if not self._connected:
            raise BrokerConnectionError("Deriv public market data is not connected")
        response = await self._request({"active_symbols": "full"})
        if response.get("error"):
            raise MarketDataError("Failed to retrieve Deriv public active symbols")
        if not isinstance(response.get("active_symbols"), list):
            raise MarketDataError("Malformed Deriv active_symbols response")
        return response

    async def get_candles_range(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime,
        count: int | None = None,
    ) -> list[Candle]:
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise MarketDataError("Historical candle range must be ordered and timezone-aware")
        span_count = int((end - start).total_seconds() // TIMEFRAME_SECONDS[timeframe]) + 1
        requested = count or span_count
        if requested <= 0:
            raise MarketDataError("Historical candle count must be positive")
        candles = await self.get_candles(symbol, timeframe, requested, end=end)
        start_utc, end_utc = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        return [candle for candle in candles if start_utc <= candle.time <= end_utc]

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._connection is None:
            raise BrokerConnectionError("Deriv public market data is not connected")

        request_id = next(self._request_ids)
        message = dict(payload)
        message["req_id"] = request_id

        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        try:
            await self._connection.send(json.dumps(message))
            return await asyncio.wait_for(
                future,
                timeout=self._request_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise BrokerConnectionError(
                "Deriv public market-data request timed out"
            ) from exc
        finally:
            self._pending.pop(request_id, None)

    async def _read_loop(self) -> None:
        assert self._connection is not None

        try:
            async for raw in self._connection:
                message = json.loads(raw)
                request_id = message.get("req_id")

                if request_id is None:
                    continue

                future = self._pending.get(request_id)
                if future is not None and not future.done():
                    future.set_result(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(
                        BrokerConnectionError(
                            "Deriv public market-data reader failed"
                        )
                    )
            self._pending.clear()
            raise BrokerConnectionError(
                "Deriv public market-data reader failed"
            ) from exc
