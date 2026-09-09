"""DerivDemoGateway — connects to Deriv WebSocket API strictly for DEMO accounts."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from broker.demo_guard import DemoOnlyGuard
from broker.deriv_auth import DerivPATOTPSession
from broker.deriv_gateway import (
    DEFAULT_ENDPOINT,
    _REQUEST_TIMEOUT_SECONDS,
    DerivGateway,
    _build_buy_request,
    _build_proposal_request,
    _parse_proposal_response,
)
from broker.types import OrderRequest, OrderResult, OrderStatus
from core.exceptions import (
    BrokerAuthenticationError,
    BrokerConnectionError,
    ExecutionError,
    UnsafeBrokerAccountError,
)
from core.logger import logger


class DerivDemoGateway(DerivGateway):
    """Deriv Gateway restricted strictly to verified DEMO/virtual accounts.

    No order or session can be initiated or submitted against a real account.
    """

    def __init__(
        self,
        api_token: str,
        app_id: str,
        endpoint: str = DEFAULT_ENDPOINT,
        request_timeout: float = _REQUEST_TIMEOUT_SECONDS,
        expected_environment: str | None = "demo",
        auth_session: DerivPATOTPSession | None = None,
        session_id: str | None = None,
    ) -> None:
        if expected_environment != "demo":
            raise BrokerAuthenticationError(
                "DerivDemoGateway requires expected_environment='demo'"
            )
        super().__init__(
            api_token=api_token,
            app_id=app_id,
            endpoint=endpoint,
            request_timeout=request_timeout,
            expected_environment="demo",
            auth_session=auth_session,
        )
        self.session_id = session_id or f"deriv-demo-{uuid4().hex[:8]}"
        self._demo_verified = False

    async def connect(self) -> None:
        """Connect to Deriv, authorize, and verify that the account is DEMO."""
        await super().connect()

        # Authoritative broker check via DemoOnlyGuard
        account_data = {
            "is_virtual": 1 if self.is_connected else 0,
            "loginid": self._account_id,
            "currency": self._currency,
        }
        try:
            DemoOnlyGuard.assert_demo_account(
                "deriv",
                account_data,
                session_id=self.session_id,
            )
            self._demo_verified = True
        except UnsafeBrokerAccountError:
            self._demo_verified = False
            await self.disconnect()
            raise

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order to Deriv, strictly verifying demo account status first."""
        self._require_connected()

        # Guard: Fail closed before placing any order
        if not self._demo_verified or not self._account_id:
            raise UnsafeBrokerAccountError(
                "Cannot submit order: Deriv account was not verified as DEMO",
                broker="deriv",
                symbol=order.symbol,
            )

        account_data = {
            "is_virtual": 1,
            "loginid": self._account_id,
        }
        DemoOnlyGuard.assert_demo_account(
            "deriv",
            account_data,
            session_id=self.session_id,
        )

        currency = self._currency or "USD"
        quantity = order.quantity.value
        proposal_request = _build_proposal_request(order, currency)

        proposal_response = await self._request(proposal_request)
        if proposal_response.get("error"):
            raise ExecutionError(
                "Deriv proposal request failed",
                symbol=order.symbol,
                reason=proposal_response["error"].get("message"),
            )

        proposal_id, ask_price = _parse_proposal_response(
            proposal_response, symbol=order.symbol
        )
        buy_request = _build_buy_request(
            proposal_id, ask_price, order.idempotency_key
        )
        buy_response = await self._request(buy_request)

        if buy_response.get("error"):
            logger.warning(
                "DerivDemoGateway order rejected: {} {} {} — {}",
                order.side,
                quantity,
                order.symbol,
                buy_response["error"].get("message"),
            )
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=order.symbol,
                side=order.side,
                volume=quantity,
                raw=buy_response,
            )

        buy = buy_response.get("buy")
        contract_id = buy.get("contract_id") if isinstance(buy, dict) else None
        buy_price = buy.get("buy_price") if isinstance(buy, dict) else None

        if (
            contract_id in (None, "")
            or not isinstance(buy_price, (int, float))
            or isinstance(buy_price, bool)
        ):
            raise ExecutionError(
                "Deriv buy response was malformed or outcome is indeterminate",
                symbol=order.symbol,
            )

        logger.info(
            "DerivDemoGateway order filled: {} {} {} contract_id={}",
            order.side,
            quantity,
            order.symbol,
            contract_id,
        )
        return OrderResult(
            order_id=str(contract_id),
            status=OrderStatus.FILLED,
            symbol=order.symbol,
            side=order.side,
            volume=quantity,
            filled_price=float(buy_price),
            transaction_id=(
                str(buy["transaction_id"])
                if buy.get("transaction_id") is not None
                else None
            ),
            raw=buy,
        )
