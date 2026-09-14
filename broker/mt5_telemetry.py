"""Capability-restricted MT5 demo telemetry adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from broker.mt5_demo import MT5DemoGateway
from broker.types import AccountInfo, Candle, Position, Timeframe
from config.settings import Settings


class MT5Telemetry(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def get_account_info(self) -> AccountInfo: ...
    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int,
        end: datetime | None = None,
    ) -> list[Candle]: ...
    async def get_positions(self) -> list[Position]: ...


class VerifiedDemoMT5Telemetry:
    """Expose only non-mutating operations from a demo-verified gateway."""

    def __init__(self, gateway: MT5DemoGateway) -> None:
        self.__gateway = gateway

    async def connect(self) -> None:
        await self.__gateway.connect()

    async def disconnect(self) -> None:
        await self.__gateway.disconnect()

    async def get_account_info(self) -> AccountInfo:
        return await self.__gateway.get_account_info()

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int,
        end: datetime | None = None,
    ) -> list[Candle]:
        return await self.__gateway.get_candles(symbol, timeframe, count, end)

    async def get_positions(self) -> list[Position]:
        return await self.__gateway.get_positions()


def verified_demo_mt5_telemetry(settings: Settings) -> MT5Telemetry:
    if settings.mt5_expected_environment != "demo":
        raise ValueError("Observation telemetry requires MT5 demo environment")
    return VerifiedDemoMT5Telemetry(MT5DemoGateway(
        terminal_path=settings.mt5_terminal_path,
        login=settings.mt5_login,
        password=settings.mt5_password,
        server=settings.mt5_server,
        expected_environment="demo",
        strict_lifecycle=settings.environment == "production",
    ))
