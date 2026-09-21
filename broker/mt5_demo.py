"""MT5DemoGateway — MetaTrader 5 gateway restricted strictly to DEMO accounts."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import MetaTrader5 as mt5

from broker.demo_guard import DemoOnlyGuard
from broker.mt5_gateway import _DEFAULT_TICK_POLL_INTERVAL_SECONDS, MT5Gateway
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderRequest, OrderResult, OrderSide
from core.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    UnsafeBrokerAccountError,
)
from core.logger import logger


_mt5_base_submit = MT5Gateway.submit_order


class MT5DemoGateway(MT5Gateway):
    """MetaTrader 5 gateway restricted strictly to verified DEMO accounts.

    No order or session can be initiated or submitted against a real account.
    """

    #: Broker identity recorded with DemoOnlyGuard evidence. Subclasses that
    #: reach the market through the MT5 terminal but are a distinct broker
    #: (Weltrade) override this so their evidence is never attributed to MT5.
    demo_guard_broker: str = "mt5"

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
        if expected_environment != "demo":
            raise BrokerAuthenticationError(
                "MT5DemoGateway requires expected_environment='demo'"
            )
        super().__init__(
            tick_poll_interval=tick_poll_interval,
            terminal_path=terminal_path,
            login=login,
            password=password,
            server=server,
            expected_environment="demo",
            strict_lifecycle=strict_lifecycle,
        )
        self.session_id = session_id or f"{self.demo_guard_broker}-demo-{uuid4().hex[:8]}"
        self._demo_verified = False

    def _assert_broker_terminal_identity(self, account_info: Any) -> None:
        """Hook for subclasses that must prove terminal/server identity pre-guard."""

    async def connect(self) -> None:
        """Connect to MT5 terminal and authoritatively verify that the account is DEMO."""
        await super().connect()

        # Fetch account info from terminal to verify trade_mode via DemoOnlyGuard
        info = await asyncio.to_thread(mt5.account_info)
        try:
            self._assert_broker_terminal_identity(info)
            DemoOnlyGuard.assert_demo_account(
                self.demo_guard_broker,
                info,
                session_id=self.session_id,
            )
            self._demo_verified = True
        except (UnsafeBrokerAccountError, BrokerConnectionError):
            self._demo_verified = False
            await self.disconnect()
            raise

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order to MT5, strictly verifying demo account status first."""
        self._require_connected()

        # Authoritatively verify live broker state immediately prior to submission
        info = await asyncio.to_thread(mt5.account_info)
        DemoOnlyGuard.assert_demo_account(
            self.demo_guard_broker,
            info,
            session_id=self.session_id,
        )

        return await _mt5_base_submit(self, order)

    async def verify_instrument_risk_spec(self, symbol: str) -> dict[str, float | str]:
        """Verify real broker metadata needed for account-currency risk sizing."""
        self._require_connected()
        real_symbol = await asyncio.to_thread(self._resolve_symbol, symbol)
        info = await asyncio.to_thread(mt5.symbol_info, real_symbol) if real_symbol else None
        tick = await asyncio.to_thread(mt5.symbol_info_tick, real_symbol) if real_symbol else None
        account = await asyncio.to_thread(mt5.account_info)
        if info is None or tick is None or account is None:
            raise BrokerConnectionError("MT5 instrument risk preflight data is unavailable")
        values = {
            "contract_size": float(getattr(info, "trade_contract_size", 0) or 0),
            "tick_size": float(getattr(info, "trade_tick_size", 0) or 0),
            "tick_value": float(getattr(info, "trade_tick_value", 0) or 0),
            "tick_value_profit": float(getattr(info, "trade_tick_value_profit", 0) or 0),
            "tick_value_loss": float(getattr(info, "trade_tick_value_loss", 0) or 0),
            "point": float(getattr(info, "point", 0) or 0),
            "volume_min": float(getattr(info, "volume_min", 0) or 0),
        }
        if any(not math.isfinite(value) or value <= 0 for value in values.values()):
            raise BrokerConnectionError("MT5 instrument risk preflight contains invalid specifications")
        price = float(getattr(tick, "ask", 0) or 0)
        margin = await asyncio.to_thread(
            mt5.order_calc_margin, mt5.ORDER_TYPE_BUY, real_symbol, values["volume_min"], price
        )
        if margin is None or not math.isfinite(float(margin)) or float(margin) <= 0:
            raise BrokerConnectionError("MT5 margin requirement could not be verified")
        return {
            "symbol": real_symbol,
            "account_currency": str(getattr(account, "currency", "")),
            **values,
            "point_value": values["tick_value"] * values["point"] / values["tick_size"],
            "minimum_volume_margin": float(margin),
        }

    async def authorize_account_currency_risk(
        self, *, symbol: str, side: OrderSide, balance: float, risk_percent: float,
        entry: float, stop_loss: float,
    ) -> tuple[ExecutionQuantity, dict[str, float | str]]:
        """Size lots using MT5's authoritative account-currency P/L and margin models."""
        spec = await self.verify_instrument_risk_spec(symbol)
        real_symbol = str(spec["symbol"])
        order_type = mt5.ORDER_TYPE_BUY if side is OrderSide.BUY else mt5.ORDER_TYPE_SELL
        one_lot_profit = await asyncio.to_thread(
            mt5.order_calc_profit, order_type, real_symbol, 1.0, entry, stop_loss
        )
        one_lot_loss = abs(float(one_lot_profit)) if one_lot_profit is not None else 0.0
        authorized_risk = balance * risk_percent / 100.0
        if not math.isfinite(one_lot_loss) or one_lot_loss <= 0 or authorized_risk <= 0:
            raise BrokerConnectionError("MT5 account-currency stop loss could not be verified")
        info = await asyncio.to_thread(mt5.symbol_info, real_symbol)
        step = float(getattr(info, "volume_step", 0) or 0)
        minimum = float(getattr(info, "volume_min", 0) or 0)
        maximum = float(getattr(info, "volume_max", 0) or 0)
        raw_lots = authorized_risk / one_lot_loss
        lots = math.floor((raw_lots + 1e-12) / step) * step if step > 0 else 0.0
        lots = min(lots, maximum) if maximum > 0 else lots
        if lots + 1e-12 < minimum:
            raise BrokerConnectionError("MT5 authorized risk is below the broker minimum lot risk")
        lots = round(lots, 8)
        actual_profit = await asyncio.to_thread(
            mt5.order_calc_profit, order_type, real_symbol, lots, entry, stop_loss
        )
        margin = await asyncio.to_thread(mt5.order_calc_margin, order_type, real_symbol, lots, entry)
        actual_loss = abs(float(actual_profit)) if actual_profit is not None else 0.0
        account = await asyncio.to_thread(mt5.account_info)
        free_margin = float(getattr(account, "margin_free", 0) or 0) if account else 0.0
        tolerance = max(0.01, authorized_risk * 1e-6)
        if (
            actual_profit is None or float(actual_profit) >= 0 or actual_loss > authorized_risk + tolerance
            or margin is None or float(margin) <= 0 or float(margin) > free_margin
        ):
            raise BrokerConnectionError("MT5 computed quantity failed stop-risk or margin verification")
        return ExecutionQuantity(value=lots, unit=ExecutionQuantityUnit.MT5_LOTS), {
            **spec, "authorized_risk_amount": authorized_risk,
            "expected_loss_at_stop": actual_loss, "margin_requirement": float(margin),
            "volume": lots, "entry": entry, "stop_loss": stop_loss,
        }
