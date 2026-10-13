"""Weltrade SyntX demo gateway implemented through the MT5 terminal API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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
        # Specification observation must not select a Market Watch symbol or
        # execute synchronous catalogue lookups on the API event loop.
        real_symbol = symbol.strip()
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
        from broker.mt5_gateway import _mt5_timeframe, _mt5_ts_to_utc, _MT5_SERVER_UTC_OFFSET_SECONDS
        from broker.types import Candle
        from core.exceptions import MarketDataError

        if start.utcoffset() is None or end.utcoffset() is None or start > end:
            raise MarketDataError('Historical range requires ordered aware UTC bounds')
        utc_start,utc_end=start.astimezone(timezone.utc),end.astimezone(timezone.utc)
        # Invert the same server-clock normalization used for returned candles.
        # The fixed offset is an existing Weltrade transport assumption, not a
        # claim of verified historical DST/calendar behavior.
        shift=timedelta(seconds=_MT5_SERVER_UTC_OFFSET_SECONDS)

        real_symbol = self._resolve_symbol(symbol)
        if not real_symbol:
            raise MarketDataError("Unknown Weltrade MT5 symbol", symbol=symbol)
        raw_rates = await asyncio.to_thread(
            mt5.copy_rates_range,
            str(real_symbol),
            int(_mt5_timeframe(timeframe)),
            utc_start + shift,
            utc_end + shift,
        )
        if raw_rates is None or len(raw_rates) == 0:
            raise MarketDataError("No candle data returned from MT5", symbol=symbol)
        candles = [
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
        if any(not utc_start<=c.time<=utc_end for c in candles) or any(b.time<=a.time for a,b in zip(candles,candles[1:])):
            raise MarketDataError('Normalized historical response violates requested UTC bounds/order')
        return candles

    async def partial_management_snapshot(self, position_id: str) -> dict | None:
        """Authoritative demo position/quote/spec facts without selecting symbols."""
        self._require_connected()
        if await asyncio.to_thread(self._verify_connection_identity, require_trading=True) is not True:
            raise BrokerConnectionError('Demo position-management identity/readiness failed')
        positions=await asyncio.to_thread(mt5.positions_get,ticket=int(position_id))
        if positions is None:raise BrokerConnectionError('Position snapshot unavailable')
        if not positions:return None
        if len(positions)!=1:raise BrokerConnectionError('Position identity ambiguous')
        p=positions[0]
        if p.type not in (mt5.ORDER_TYPE_BUY,mt5.ORDER_TYPE_SELL) or not all(math.isfinite(float(x)) and float(x)>0 for x in (p.volume,p.price_open,p.sl,p.tp)):
            raise BrokerConnectionError('Protective position facts unavailable')
        if not is_weltrade_synthetic(p.symbol) or p.magic!=20260802:
            raise BrokerConnectionError('Position outside owned native demo scope')
        info=await asyncio.to_thread(mt5.symbol_info,p.symbol)
        tick=await self.get_latest_tick(p.symbol)
        if info is None or tick is None or abs((datetime.now(timezone.utc)-tick.time).total_seconds())>15:
            raise BrokerConnectionError('Fresh executable quote/spec unavailable')
        fields={k:float(getattr(info,k)) for k in ('volume_min','volume_step','trade_tick_size','point','trade_stops_level','trade_freeze_level')}
        if any(not math.isfinite(x) or x<0 for x in fields.values()) or min(fields[k] for k in ('volume_min','volume_step','trade_tick_size','point'))<=0:
            raise BrokerConnectionError('Position-management contract rules unavailable')
        return {'ticket':str(p.ticket),'symbol':p.symbol,'side':'BUY' if p.type==mt5.ORDER_TYPE_BUY else 'SELL','volume':float(p.volume),'entry':float(p.price_open),'sl':float(p.sl),'tp':float(p.tp),'quote':tick.bid if p.type==mt5.ORDER_TYPE_BUY else tick.ask,'distance':max(fields['trade_stops_level'],fields['trade_freeze_level'])*fields['point'],**fields}

    async def partial_close_confirmed(self, position_id: str, *, original_volume: float, portion: float) -> None:
        """Reduce one exact owned position and require broker deal/volume evidence."""
        snapshot=await self.partial_management_snapshot(position_id)
        if snapshot is None or not math.isclose(snapshot['volume'],original_volume,abs_tol=1e-8):
            raise BrokerConnectionError('Partial close original volume changed')
        from execution.partial_policy import split_lots
        total,half=split_lots(original_volume,snapshot['volume_min'],snapshot['volume_step'])
        if not math.isclose(total,original_volume,abs_tol=1e-8) or not math.isclose(half,portion,abs_tol=1e-8):
            raise BrokerConnectionError('Partial close must leave an equal valid portion')
        await self.close_position(position_id,volume=portion,expected_volume=original_volume)
        if not await self.partial_volume_confirmed(position_id,original_volume=original_volume,portion=portion):
            raise BrokerConnectionError('Partial close outcome requires reconciliation; do not resend')

    async def partial_volume_confirmed(self, position_id: str, *, original_volume: float, portion: float) -> bool:
        snapshot=await self.partial_management_snapshot(position_id)
        if snapshot is None or not math.isclose(snapshot['volume'],portion,abs_tol=1e-8):return False
        deals=await asyncio.to_thread(mt5.history_deals_get,position=int(position_id))
        if deals is None:raise BrokerConnectionError('Position-scoped deal evidence unavailable')
        opening=sum(float(d.volume) for d in deals if d.entry==mt5.DEAL_ENTRY_IN)
        closing=sum(float(d.volume) for d in deals if d.entry==mt5.DEAL_ENTRY_OUT)
        return (all(str(d.position_id)==position_id and d.symbol==snapshot['symbol'] and d.magic==20260802 for d in deals)
                and math.isclose(opening,original_volume,abs_tol=1e-8) and math.isclose(closing,portion,abs_tol=1e-8))

    async def protect_partial_stop(self, position_id: str, *, remaining_volume: float, stop: float) -> bool:
        """Tighten a confirmed remainder's stop; preserve its broker target."""
        from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
        snapshot=await self.partial_management_snapshot(position_id)
        if snapshot is None:return False
        if not math.isclose(snapshot['volume'],remaining_volume,abs_tol=1e-8):
            raise BrokerConnectionError('Remainder volume changed')
        buy=snapshot['side']=='BUY';sign=1 if buy else -1
        quantum=Decimal(str(snapshot['trade_tick_size']))
        stop=float((Decimal(str(stop))/quantum).to_integral_value(rounding=ROUND_CEILING if buy else ROUND_FLOOR)*quantum)
        if not math.isfinite(stop) or stop<=0 or sign*(stop-snapshot['entry'])<=0:
            raise BrokerConnectionError('Profit-zone stop required')
        if snapshot['sl']>0 and sign*(snapshot['sl']-stop)>=-1e-8:return True
        if sign*(snapshot['quote']-stop)<=snapshot['distance']:return False
        if snapshot['tp']<=0 or sign*(snapshot['tp']-stop)<=0:
            raise BrokerConnectionError('Stop/target relationship invalid')
        request={'action':mt5.TRADE_ACTION_SLTP,'position':int(position_id),'symbol':snapshot['symbol'],'sl':stop,'tp':snapshot['tp'],'magic':20260802}
        check=await asyncio.to_thread(mt5.order_check,request)
        if check is None or check.retcode!=0:return False
        # Last-moment demo readiness/identity check precedes every mutation.
        if await asyncio.to_thread(self._verify_connection_identity,require_trading=True) is not True:
            raise BrokerConnectionError('Demo identity changed before stop update')
        result=await asyncio.to_thread(mt5.order_send,request)
        if result is None:raise BrokerConnectionError('Stop update outcome unavailable')
        updated=await self.partial_management_snapshot(position_id)
        if updated is None:return False
        return updated['sl']>0 and sign*(updated['sl']-stop)>=-1e-8 and math.isclose(updated['tp'],snapshot['tp'],abs_tol=1e-8)
