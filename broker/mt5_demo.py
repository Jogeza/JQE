"""MT5DemoGateway — MetaTrader 5 gateway restricted strictly to DEMO accounts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import MetaTrader5 as mt5

from broker.demo_guard import DemoOnlyGuard
from broker.mt5_gateway import _DEFAULT_TICK_POLL_INTERVAL_SECONDS, MT5Gateway
from broker.types import OrderRequest, OrderResult
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
        self.session_id = session_id or f"mt5-demo-{uuid4().hex[:8]}"
        self._demo_verified = False

    async def connect(self) -> None:
        """Connect to MT5 terminal and authoritatively verify that the account is DEMO."""
        await super().connect()

        # Fetch account info from terminal to verify trade_mode via DemoOnlyGuard
        info = await asyncio.to_thread(mt5.account_info)
        try:
            DemoOnlyGuard.assert_demo_account(
                "mt5",
                info,
                session_id=self.session_id,
            )
            self._demo_verified = True
        except UnsafeBrokerAccountError:
            self._demo_verified = False
            await self.disconnect()
            raise

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order to MT5, strictly verifying demo account status first."""
        self._require_connected()

        # Authoritatively verify live broker state immediately prior to submission
        info = await asyncio.to_thread(mt5.account_info)
        DemoOnlyGuard.assert_demo_account(
            "mt5",
            info,
            session_id=self.session_id,
        )

        return await _mt5_base_submit(self, order)
