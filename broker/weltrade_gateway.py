"""Weltrade SyntX demo gateway implemented through the MT5 terminal API."""

from __future__ import annotations

import asyncio
import re

import MetaTrader5 as mt5

from pathlib import Path

from broker.mt5_demo import MT5DemoGateway
from broker.mt5_gateway import _DEFAULT_TICK_POLL_INTERVAL_SECONDS
from core.exceptions import BrokerConnectionError
from core.logger import logger


_WELTRADE_SYNTHETIC_ALIASES: dict[str, tuple[str, ...]] = {
    "R_10": ("Volatility 10", "Volatility 10 Index", "FX Vol.10", "FX Vol 10"),
    "R_25": ("Volatility 25", "Volatility 25 Index", "FX Vol.25", "FX Vol 25"),
    "R_50": ("Volatility 50", "Volatility 50 Index", "FX Vol.50", "FX Vol 50"),
    "R_75": ("Volatility 75", "Volatility 75 Index", "FX Vol.75", "FX Vol 75"),
    "R_100": ("Volatility 100", "Volatility 100 Index", "FX Vol.100", "FX Vol 100"),
    "BOOM_500": ("Boom 500", "Boom 500 Index"),
    "BOOM_1000": ("Boom 1000", "Boom 1000 Index"),
    "CRASH_500": ("Crash 500", "Crash 500 Index"),
    "CRASH_1000": ("Crash 1000", "Crash 1000 Index"),
}


def _symbol_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


class WeltradeGateway(MT5DemoGateway):
    """Weltrade-only identity and symbol policy over shared MT5 mechanics."""

    def __init__(
        self,
        tick_poll_interval: float = _DEFAULT_TICK_POLL_INTERVAL_SECONDS,
        *,
        terminal_path: Path | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        expected_environment: str | None = "demo",
        strict_lifecycle: bool = True,
        session_id: str | None = None,
    ) -> None:
        from config import settings
        terminal_path = terminal_path or settings.weltrade_terminal_path
        login = login if login is not None else settings.effective_weltrade_login
        password = password if password is not None else settings.effective_weltrade_password
        server = server if server is not None else settings.effective_weltrade_server

        super().__init__(
            tick_poll_interval=tick_poll_interval,
            terminal_path=terminal_path,
            login=login,
            password=password,
            server=server,
            expected_environment=expected_environment,
            strict_lifecycle=strict_lifecycle,
            session_id=session_id,
        )

    def _initialize_session(self) -> bool:
        if self.login is None or not self.password or not self.server:
            missing: list[str] = []
            if self.login is None:
                missing.append("JQE_WELTRADE_DEMO_LOGIN (or JQE_WELTRADE_LOGIN)")
            if not self.password:
                missing.append("JQE_WELTRADE_DEMO_PASSWORD (or JQE_WELTRADE_PASSWORD)")
            if not self.server:
                missing.append("JQE_WELTRADE_DEMO_SERVER (or JQE_WELTRADE_SERVER)")
            raise BrokerConnectionError(
                f"Weltrade demo login configuration missing: {', '.join(missing)}. "
                "Explicit demo credentials are required for deterministic demo connection."
            )
        return super()._initialize_session()

    async def connect(self) -> None:
        await super().connect()
        info = await asyncio.to_thread(mt5.account_info)
        server = str(getattr(info, "server", "") or "").strip()
        if "WELTRADE" not in server.upper():
            await self.disconnect()
            raise BrokerConnectionError(
                "Weltrade terminal identity verification failed",
                expected_broker="WELTRADE",
                observed_server=server,
            )

    def _resolve_symbol(self, symbol: str) -> str | None:
        aliases = _WELTRADE_SYNTHETIC_ALIASES.get(symbol.strip().upper(), (symbol,))
        for candidate in aliases:
            info = mt5.symbol_info(candidate)
            if info is not None:
                if not getattr(info, "visible", True):
                    mt5.symbol_select(candidate, True)
                logger.info("Weltrade symbol mapped: {} -> {}", symbol, candidate)
                return candidate

        available = mt5.symbols_get() or ()
        targets = {_symbol_key(candidate) for candidate in aliases}
        for item in available:
            name = str(getattr(item, "name", "") or "")
            if _symbol_key(name) in targets:
                if not getattr(item, "visible", True):
                    mt5.symbol_select(name, True)
                logger.info("Weltrade symbol mapped from terminal catalogue: {} -> {}", symbol, name)
                return name
        logger.error("No Weltrade symbol found for {}", symbol)
        return None
