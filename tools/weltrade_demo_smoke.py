"""Explicitly opted-in, read-only Weltrade SyntX MT5 smoke diagnostic."""

from __future__ import annotations

import asyncio
import json
import os

import MetaTrader5 as mt5

from broker.factory import get_gateway
from broker.weltrade_gateway import WeltradeGateway
from broker.types import Timeframe
from config.settings import Settings


def _synthetic(name: str) -> bool:
    value = name.upper()
    return any(token in value for token in ("VOL", "PAINX", "GAINX", "TRENDX", "FIBOX", "QUADX", "BOOM", "CRASH"))


async def run() -> None:
    if os.environ.get("JQE_RUN_LIVE_WELTRADE_TESTS") != "1":
        raise SystemExit("Set JQE_RUN_LIVE_WELTRADE_TESTS=1 to authorize the read-only smoke test")
    settings = Settings()
    if settings.weltrade_terminal_path is None:
        raise SystemExit("Set JQE_WELTRADE_TERMINAL_PATH to the Weltrade terminal executable")
    gateway = (
        get_gateway(settings)
        if settings.broker in {"weltrade", "weltrade_demo"}
        and settings.weltrade_login is not None
        and settings.weltrade_server
        else WeltradeGateway(
            terminal_path=settings.weltrade_terminal_path,
            expected_environment="demo",
            strict_lifecycle=True,
        )
    )
    async with gateway:
        account = await gateway.get_account_info()
        terminal = mt5.terminal_info()
        symbols = [item.name for item in (mt5.symbols_get() or ()) if _synthetic(str(item.name))]
        requested = os.environ.get("JQE_WELTRADE_SMOKE_SYMBOL") or (symbols[0] if symbols else "")
        if not requested:
            raise RuntimeError("Weltrade terminal returned no recognizable synthetic symbols")
        resolved = gateway._resolve_symbol(requested)
        candles = await gateway.get_candles(requested, Timeframe.H1, 2)
        tick = mt5.symbol_info_tick(resolved) if resolved else None
        print(json.dumps({
            "connected": gateway.is_connected,
            "account_id_suffix": account.account_id[-4:],
            "server": account.server,
            "trade_mode": account.trade_mode,
            "terminal_path": getattr(terminal, "path", None),
            "terminal_data_path": getattr(terminal, "data_path", None),
            "synthetic_symbol_count": len(symbols),
            "synthetic_symbols": symbols,
            "requested_symbol": requested,
            "resolved_symbol": resolved,
            "candle_count": len(candles),
            "latest_candle": candles[-1].model_dump(mode="json") if candles else None,
            "tick": None if tick is None else {
                "bid": getattr(tick, "bid", None), "ask": getattr(tick, "ask", None),
                "time": getattr(tick, "time", None),
            },
        }, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(run())
