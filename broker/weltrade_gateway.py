"""Weltrade SyntX demo gateway implemented through the MT5 terminal API."""

from __future__ import annotations

import asyncio
import re

import MetaTrader5 as mt5

from broker.mt5_demo import MT5DemoGateway
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
