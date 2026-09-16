"""Capability-restricted MT5 demo telemetry adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

import MetaTrader5 as mt5

from broker.mt5_demo import MT5DemoGateway
from broker.types import AccountInfo, Candle, Position, Timeframe
from config.settings import Settings
from core.exceptions import BrokerConnectionError


class _PortableObservationGateway(MT5DemoGateway):
    """MT5 demo gateway whose connection is isolated to a portable profile."""

    def __init__(self, *, portable_data_path: Path, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._portable_data_path = Path(portable_data_path).expanduser().resolve()

    def _initialize_session(self) -> bool:
        terminal_path = Path(self.terminal_path or "").expanduser().resolve()
        if not terminal_path.is_file():
            raise BrokerConnectionError("Observation MT5 terminal does not exist")
        if terminal_path.parent != self._portable_data_path:
            raise BrokerConnectionError("Observation MT5 executable must reside in its portable data directory")
        if mt5.initialize(str(terminal_path), portable=True) is not True:
            return False
        if self.login is not None and mt5.login(
            self.login, password=self.password, server=self.server
        ) is not True:
            raise BrokerConnectionError("Observation MT5 account login failed")
        terminal = mt5.terminal_info()
        actual_data_path = None if terminal is None else Path(terminal.data_path).resolve()
        if actual_data_path != self._portable_data_path:
            raise BrokerConnectionError("Observation MT5 terminal did not use the configured portable profile")
        return True


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
    if settings.observation_mt5_terminal_path is None:
        raise ValueError("Observation telemetry requires an isolated MT5 terminal path")
    if settings.observation_mt5_portable_data_path is None:
        raise ValueError("Observation telemetry requires an isolated MT5 portable data path")
    return VerifiedDemoMT5Telemetry(_PortableObservationGateway(
        terminal_path=settings.observation_mt5_terminal_path,
        portable_data_path=settings.observation_mt5_portable_data_path,
        login=settings.mt5_login,
        password=settings.mt5_password,
        server=settings.mt5_server,
        expected_environment="demo",
        strict_lifecycle=settings.environment == "production",
    ))
