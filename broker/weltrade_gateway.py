"""Weltrade SyntX demo gateway implemented through the MT5 terminal API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
from typing import Any

import MetaTrader5 as mt5

from pathlib import Path

from broker.mt5_demo import MT5DemoGateway
from broker.mt5_gateway import _DEFAULT_TICK_POLL_INTERVAL_SECONDS
from broker.types import Tick
from core.exceptions import BrokerConnectionError
from core.logger import logger
from broker.weltrade_symbols import is_weltrade_synthetic, weltrade_symbol_key


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


class WeltradeGateway(MT5DemoGateway):
    """Weltrade-only identity and symbol policy over shared MT5 mechanics."""

    demo_guard_broker = "weltrade"
    market_data_provider = "weltrade"

    async def get_price_point(self, symbol: str) -> float:
        """Read the connected terminal's price quantum for fill verification."""
        self._require_connected()
        if not is_weltrade_synthetic(symbol):
            raise BrokerConnectionError("Symbol outside Weltrade synthetic scope")
        info = await asyncio.to_thread(mt5.symbol_info, symbol)
        point = getattr(info, "point", None)
        if not isinstance(point, (int, float)) or not math.isfinite(point) or point <= 0:
            raise BrokerConnectionError("Weltrade symbol price precision unavailable")
        return float(point)

    async def get_latest_tick(self, symbol: str) -> Tick | None:
        """Read one terminal tick; return no price when server time is unresolved."""
        self._require_connected()
        if not is_weltrade_synthetic(symbol):
            return None
        raw = await asyncio.to_thread(mt5.symbol_info_tick, symbol)
        stamp = getattr(raw, "time", None)
        if type(stamp) is not int or stamp <= 0:
            return None
        now = datetime.now(timezone.utc)
        offsets = [hours * 3600 for hours in range(-12, 15)
                   if abs(stamp - hours * 3600 - now.timestamp()) <= 120]
        if len(offsets) != 1:
            return None
        stamp_milliseconds = getattr(raw, "time_msc", None)
        if type(stamp_milliseconds) is int and stamp_milliseconds > 0:
            tick_time = datetime.fromtimestamp(
                (stamp_milliseconds - offsets[0] * 1000) / 1000,
                tz=timezone.utc,
            )
        else:
            tick_time = datetime.fromtimestamp(stamp - offsets[0], tz=timezone.utc)
        bid = float(getattr(raw, "bid", 0.0))
        ask = float(getattr(raw, "ask", 0.0))
        if not all(math.isfinite(value) and value > 0 for value in (bid, ask)):
            return None
        return Tick(
            time=tick_time,
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=(
                float(raw.last)
                if isinstance(getattr(raw, "last", None), (int, float))
                and math.isfinite(float(raw.last))
                and float(raw.last) > 0
                else None
            ),
        )

    async def get_terminal_permissions(self) -> dict[str, bool | None]:
        """Return current terminal-side connection and trade permission flags."""
        self._require_connected()
        info = await asyncio.to_thread(mt5.terminal_info)
        if info is None:
            raise BrokerConnectionError("Weltrade terminal status is unavailable")
        return {
            "connected": bool(getattr(info, "connected", False)),
            "terminal_trading_allowed": bool(getattr(info, "trade_allowed", False)),
            "trade_api_disabled": bool(getattr(info, "tradeapi_disabled", True)),
        }

    async def get_symbol_specification(self, symbol: str) -> dict[str, str | int | float | None]:
        """Read terminal-reported contract economics without submitting an order."""
        self._require_connected()
        if not is_weltrade_synthetic(symbol):
            raise BrokerConnectionError("Symbol outside Weltrade synthetic scope")
        real_symbol = self._resolve_symbol(symbol)
        if not real_symbol:
            raise BrokerConnectionError("Weltrade terminal symbol is unavailable")
        info = await asyncio.to_thread(mt5.symbol_info, real_symbol)
        if info is None:
            raise BrokerConnectionError("Weltrade symbol specification is unavailable")

        def numeric(name: str) -> float | None:
            value = getattr(info, name, None)
            return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None

        return {
            "name": str(getattr(info, "name", real_symbol)),
            "description": str(getattr(info, "description", "") or ""),
            "digits": int(info.digits),
            "point": numeric("point"),
            "trade_tick_size": numeric("trade_tick_size"),
            "trade_tick_value": numeric("trade_tick_value"),
            "contract_size": numeric("trade_contract_size"),
            "volume_min": numeric("volume_min"),
            "volume_step": numeric("volume_step"),
            "volume_max": numeric("volume_max"),
            "trade_mode": int(getattr(info, "trade_mode", 0)),
        }

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

    def _assert_broker_terminal_identity(self, account_info: Any) -> None:
        """Reject any terminal that is not authoritatively a Weltrade server.

        Runs before DemoOnlyGuard so demo evidence is never attributed to
        Weltrade for a terminal that is not actually Weltrade.
        """
        server = str(getattr(account_info, "server", "") or "").strip()
        if "WELTRADE" not in server.upper():
            raise BrokerConnectionError(
                "Weltrade terminal identity verification failed",
                expected_broker="WELTRADE",
                observed_server=server,
            )

    def _resolve_symbol(self, symbol: str) -> str | None:
        if not is_weltrade_synthetic(symbol):
            logger.error("Outside Weltrade synthetic scope: {}", symbol)
            return None
        aliases = (symbol.strip(),)
        for candidate in aliases:
            info = mt5.symbol_info(candidate)
            if info is not None:
                if not getattr(info, "visible", True):
                    mt5.symbol_select(candidate, True)
                logger.info("Weltrade symbol mapped: {} -> {}", symbol, candidate)
                return candidate

        available = mt5.symbols_get() or ()
        targets = {weltrade_symbol_key(candidate) for candidate in aliases}
        for item in available:
            name = str(getattr(item, "name", "") or "")
            if weltrade_symbol_key(name) in targets:
                if not getattr(item, "visible", True):
                    mt5.symbol_select(name, True)
                logger.info("Weltrade symbol mapped from terminal catalogue: {} -> {}", symbol, name)
                return name
        logger.error("No Weltrade symbol found for {}", symbol)
        return None

    async def get_candles_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        count: int | None = None,
    ) -> list[Candle]:
        self._require_connected()
        import asyncio
        from broker.mt5_gateway import _mt5_timeframe, _mt5_ts_to_utc
        from broker.types import Candle
        from core.exceptions import MarketDataError

        real_symbol = self._resolve_symbol(symbol)
        if not real_symbol:
            raise MarketDataError("Unknown Weltrade MT5 symbol", symbol=symbol)
        raw_rates = await asyncio.to_thread(
            mt5.copy_rates_range,
            str(real_symbol),
            int(_mt5_timeframe(timeframe)),
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
        )
        if raw_rates is None or len(raw_rates) == 0:
            raise MarketDataError("No candle data returned from MT5", symbol=symbol)
        return [
            Candle(
                time=_mt5_ts_to_utc(rate["time"]),
                open=float(rate["open"]),
                high=float(rate["high"]),
                low=float(rate["low"]),
                close=float(rate["close"]),
                volume=(
                    float(rate["tick_volume"])
                    if not isinstance(rate, dict) or "tick_volume" in rate
                    else None
                ),
                source=self.market_data_provider,
            )
            for rate in raw_rates
        ]
