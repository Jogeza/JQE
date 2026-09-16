"""DerivGateway consumption of the authoritative PAT/OTP identity session."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from broker.deriv_auth import (
    DerivAuthErrorCode,
    DerivAuthFailure,
    DerivAuthSession,
    DerivIdentityState,
)
from broker.deriv_gateway import DerivGateway
from broker.types import ExecutionQuantity, ExecutionQuantityUnit, OrderRequest, OrderSide
from core.exceptions import BrokerAuthenticationError, ExecutionError


class Connection:
    def __init__(self) -> None:
        self.closed = False
        self._messages: asyncio.Queue[str | None] = asyncio.Queue()

    async def send(self, raw_message: str) -> None:
        message = json.loads(raw_message)
        request_type = next(key for key in message if key != "req_id")
        if request_type == "balance":
            response = {"balance": {"currency": "USD"}}
        else:
            response = {"error": {"message": "multiplier is unverified"}}
        response["req_id"] = message["req_id"]
        await self._messages.put(json.dumps(response))

    async def close(self) -> None:
        self.closed = True
        await self._messages.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self._messages.get()
        if value is None:
            raise StopAsyncIteration
        return value


class AuthSession:
    def __init__(self, account="CR-DEMO", environment="demo", failure=None) -> None:
        self.connection = Connection()
        self.account = account
        self.environment = environment
        self.failure = failure
        self.connect = AsyncMock(side_effect=self._connect)
        self.close = AsyncMock(side_effect=self.connection.close)
        self.mark_expired = MagicMock()

    async def _connect(self):
        if self.failure:
            raise self.failure
        return DerivAuthSession(
            self.account,
            self.environment,
            "wss://api.derivws.com/trading/v1/options/ws/demo?otp=top-secret-otp",
        )


def gateway(session, expected="demo") -> DerivGateway:
    return DerivGateway("secret-pat", "secret-app", expected_environment=expected, auth_session=session)


@pytest.mark.asyncio
async def test_exact_demo_identity_verifies_and_redacts_endpoint() -> None:
    auth = AuthSession()
    target = gateway(auth)
    await target.connect()
    assert target.identity_state is DerivIdentityState.VERIFIED_DEMO
    assert target.account_identity is not None
    assert target.account_identity.account_id == "CR-DEMO"
    assert target.account_identity.endpoint == "wss://api.derivws.com/trading/v1/options/ws/demo"
    assert "otp" not in repr(target.account_identity)
    await target.disconnect()


@pytest.mark.asyncio
async def test_authentication_failure_is_typed_and_secret_free() -> None:
    auth = AuthSession(failure=DerivAuthFailure(DerivAuthErrorCode.ACCOUNT_MISMATCH))
    target = gateway(auth)
    with pytest.raises(BrokerAuthenticationError) as exc:
        await target.connect()
    assert target.identity_state is DerivIdentityState.MISMATCH
    assert "secret-pat" not in str(exc.value)
    assert "top-secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_otp_authentication_failure_remains_unverified() -> None:
    auth = AuthSession(failure=DerivAuthFailure(DerivAuthErrorCode.OTP_FAILURE))
    target = gateway(auth)
    with pytest.raises(BrokerAuthenticationError):
        await target.connect()
    assert target.identity_state is DerivIdentityState.AUTHENTICATION_FAILED
    assert target.account_identity is None


@pytest.mark.asyncio
async def test_live_or_ambiguous_identity_fails_closed() -> None:
    live = gateway(AuthSession(environment="real"))
    with pytest.raises(BrokerAuthenticationError, match="not DEMO"):
        await live.connect()
    assert live.identity_state is DerivIdentityState.LIVE_ACCOUNT

    ambiguous_auth = AuthSession(account="")
    ambiguous = gateway(ambiguous_auth)
    with pytest.raises(BrokerAuthenticationError, match="ambiguous"):
        await ambiguous.connect()
    assert ambiguous.identity_state is DerivIdentityState.AMBIGUOUS


@pytest.mark.asyncio
async def test_disconnect_and_reconnect_require_fresh_verification() -> None:
    auth = AuthSession()
    target = gateway(auth)
    await target.connect()
    await target.disconnect()
    assert target.account_identity is None
    assert target.identity_state is DerivIdentityState.SESSION_CLOSED
    auth.connection = Connection()
    auth.close = AsyncMock(side_effect=auth.connection.close)
    await target.connect()
    assert auth.connect.await_count == 2
    await target.disconnect()


@pytest.mark.asyncio
async def test_reconnect_to_different_account_fails_through_session_verifier() -> None:
    auth = AuthSession()
    target = gateway(auth)
    await target.connect()
    await target.disconnect()
    auth.failure = DerivAuthFailure(DerivAuthErrorCode.ACCOUNT_MISMATCH)
    with pytest.raises(BrokerAuthenticationError):
        await target.connect()
    assert target.account_identity is None


@pytest.mark.asyncio
async def test_verified_identity_never_enables_submission() -> None:
    auth = AuthSession()
    target = gateway(auth)
    await target.connect()
    order = OrderRequest(
        symbol="frxXAUUSD",
        side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.DERIV_STAKE),
        stop_loss=1.0,
    )
    with pytest.raises(ExecutionError, match="multiplier is unverified"):
        await target.submit_order(order)
    await target.disconnect()
