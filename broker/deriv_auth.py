"""Non-network Deriv PAT/OTP authentication boundary."""

from __future__ import annotations

import asyncio
import json
import socket
import ssl
from dataclasses import dataclass, field
from enum import Enum
from http.client import InvalidURL
from typing import Awaitable, Callable, Protocol
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DerivAuthErrorCode(str, Enum):
    MISSING_APP_ID = "MISSING_APP_ID"
    MISSING_TOKEN = "MISSING_TOKEN"
    INVALID_TOKEN = "INVALID_TOKEN"
    EXPIRED_TOKEN = "EXPIRED_TOKEN"
    REVOKED_TOKEN = "REVOKED_TOKEN"
    OTP_FAILURE = "OTP_FAILURE"
    MALFORMED_OTP_RESPONSE = "MALFORMED_OTP_RESPONSE"
    WEBSOCKET_FAILURE = "WEBSOCKET_FAILURE"
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    MISSING_ACCOUNT_ID = "MISSING_ACCOUNT_ID"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    MISSING_ENVIRONMENT = "MISSING_ENVIRONMENT"
    HTTP_FAILURE = "HTTP_FAILURE"
    INVALID_SESSION_URL = "INVALID_SESSION_URL"


class DerivAuthFailureCategory(str, Enum):
    NETWORK_DNS_FAILURE = "NETWORK_DNS_FAILURE"
    NETWORK_CONNECTION_FAILURE = "NETWORK_CONNECTION_FAILURE"
    NETWORK_TLS_FAILURE = "NETWORK_TLS_FAILURE"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    NETWORK_URL_FAILURE = "NETWORK_URL_FAILURE"
    NETWORK_UNKNOWN_FAILURE = "NETWORK_UNKNOWN_FAILURE"


@dataclass(frozen=True, slots=True)
class DerivAuthConfig:
    app_id: str
    pat: str = field(repr=False)
    options_account_id: str | None = None
    expected_environment: str | None = None


@dataclass(frozen=True, slots=True)
class DerivAuthSession:
    account_id: str
    environment: str
    websocket_url: str


class DerivAuthState(str, Enum):
    UNINITIALIZED = "UNINITIALIZED"
    AUTHENTICATING = "AUTHENTICATING"
    READY = "READY"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class DerivAuthFailure(RuntimeError):
    def __init__(self, code: DerivAuthErrorCode, *, http_status: int | None = None, category: DerivAuthFailureCategory | None = None) -> None:
        super().__init__(code.value)
        self.code = code
        self.http_status = http_status
        self.category = category


def _network_category(exc: BaseException) -> DerivAuthFailureCategory:
    if isinstance(exc, InvalidURL):
        return DerivAuthFailureCategory.NETWORK_URL_FAILURE
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return DerivAuthFailureCategory.NETWORK_TIMEOUT
    if isinstance(exc, ssl.SSLError):
        return DerivAuthFailureCategory.NETWORK_TLS_FAILURE
    if isinstance(exc, socket.gaierror):
        return DerivAuthFailureCategory.NETWORK_DNS_FAILURE
    if isinstance(exc, ConnectionError):
        return DerivAuthFailureCategory.NETWORK_CONNECTION_FAILURE
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return DerivAuthFailureCategory.NETWORK_TIMEOUT
        if isinstance(reason, ssl.SSLError):
            return DerivAuthFailureCategory.NETWORK_TLS_FAILURE
        if isinstance(reason, socket.gaierror):
            return DerivAuthFailureCategory.NETWORK_DNS_FAILURE
        if isinstance(reason, ConnectionError):
            return DerivAuthFailureCategory.NETWORK_CONNECTION_FAILURE
        return DerivAuthFailureCategory.NETWORK_URL_FAILURE
    return DerivAuthFailureCategory.NETWORK_UNKNOWN_FAILURE


class DerivAuthTransport(Protocol):
    async def request_otp(
        self, *, app_id: str, authorization: str, environment: str | None,
        options_account_id: str | None = None,
    ) -> dict[str, object]: ...
    async def connect_websocket(self, url: str, *, app_id: str | None = None) -> object: ...


HttpPost = Callable[[str, dict[str, str]], Awaitable[tuple[int, object]]]
WebSocketConnect = Callable[..., Awaitable[object]]


class DerivPATOTPTransport:
    """Production PAT/OTP transport; network access occurs only when called.

    HTTP and WebSocket callables are injectable so tests never require a network
    and authentication remains independent of the execution and broker layers.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://api.derivws.com",
        http_post: HttpPost | None = None,
        websocket_connect: WebSocketConnect | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._http_post = http_post or self._default_http_post
        self._websocket_connect = websocket_connect or self._default_websocket_connect

    async def request_otp(
        self, *, app_id: str, authorization: str, environment: str | None,
        options_account_id: str | None = None,
    ) -> dict[str, object]:
        if not options_account_id or not options_account_id.strip():
            raise DerivAuthFailure(DerivAuthErrorCode.MISSING_ACCOUNT_ID)
        if environment not in {"demo", "real"}:
            raise DerivAuthFailure(DerivAuthErrorCode.MISSING_ENVIRONMENT)
        endpoint = f"{self._base_url}/trading/v1/options/accounts/{options_account_id.strip()}/otp"
        try:
            status, payload = await self._http_post(endpoint, {
                "Deriv-App-ID": app_id,
                "Authorization": authorization,
                "Content-Type": "application/json",
            })
        except HTTPError as exc:
            raise DerivAuthFailure(DerivAuthErrorCode.HTTP_FAILURE, http_status=int(exc.code)) from exc
        except Exception as exc:
            raise DerivAuthFailure(DerivAuthErrorCode.HTTP_FAILURE, category=_network_category(exc)) from exc
        if not isinstance(status, int) or status < 200 or status >= 300:
            raise DerivAuthFailure(DerivAuthErrorCode.HTTP_FAILURE, http_status=status if isinstance(status, int) else None)
        if not isinstance(payload, dict):
            raise DerivAuthFailure(DerivAuthErrorCode.MALFORMED_OTP_RESPONSE)
        errors = payload.get("errors")
        if errors:
            raise DerivAuthFailure(DerivAuthErrorCode.OTP_FAILURE)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise DerivAuthFailure(DerivAuthErrorCode.MALFORMED_OTP_RESPONSE)
        url = data.get("url")
        if not self._is_valid_demo_url(url):
            raise DerivAuthFailure(DerivAuthErrorCode.INVALID_SESSION_URL)
        expected_marker = f"/ws/{environment}"
        if expected_marker not in url:
            raise DerivAuthFailure(DerivAuthErrorCode.ENVIRONMENT_MISMATCH)
        return {"url": url, "account_id": options_account_id.strip(), "environment": environment}

    async def connect_websocket(self, url: str, *, app_id: str | None = None) -> object:
        if not self._is_valid_demo_url(url):
            raise DerivAuthFailure(DerivAuthErrorCode.INVALID_SESSION_URL)
        try:
            return await self._websocket_connect(url, app_id=app_id)
        except DerivAuthFailure:
            self._state = DerivAuthState.FAILED
            raise
        except Exception as exc:
            raise DerivAuthFailure(DerivAuthErrorCode.WEBSOCKET_FAILURE) from exc

    @staticmethod
    def _is_valid_demo_url(url: object) -> bool:
        if not isinstance(url, str):
            return False
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        return (
            parsed.scheme == "wss" and parsed.hostname == "api.derivws.com"
            and parsed.path == "/trading/v1/options/ws/demo"
            and len(query.get("otp", [])) == 1 and bool(query["otp"][0].strip())
        )

    async def _default_http_post(self, url: str, headers: dict[str, str]) -> tuple[int, object]:
        def do_request() -> tuple[int, object]:
            request = Request(url, method="POST", headers=headers)
            try:
                with urlopen(request, timeout=15) as response:  # noqa: S310 - explicit production endpoint
                    return int(response.status), json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                return int(exc.code), {}
            except (URLError, ValueError):
                raise
        return await asyncio.to_thread(do_request)

    async def _default_websocket_connect(self, url: str, *, app_id: str | None = None) -> object:
        import websockets
        headers = {"Deriv-App-ID": app_id} if app_id else None
        return await websockets.connect(url, additional_headers=headers)


class DerivPATOTPSession:
    """Authenticate through a transport supplied by the caller.

    The production transport is intentionally not created here. This object
    only validates the documented PAT/OTP/session contract and owns no token
    persistence or trading behavior.
    """

    def __init__(self, config: DerivAuthConfig, transport: DerivAuthTransport) -> None:
        self._config = config
        self._transport = transport
        self._session: DerivAuthSession | None = None
        self._connection: object | None = None
        self._state = DerivAuthState.UNINITIALIZED

    @property
    def is_ready(self) -> bool:
        return self._session is not None

    @property
    def state(self) -> DerivAuthState:
        return self._state

    @property
    def session(self) -> DerivAuthSession | None:
        return self._session

    async def connect(self) -> DerivAuthSession:
        self._session = None
        self._connection = None
        self._state = DerivAuthState.AUTHENTICATING
        if not isinstance(self._config.app_id, str) or not self._config.app_id.strip():
            raise DerivAuthFailure(DerivAuthErrorCode.MISSING_APP_ID)
        if not isinstance(self._config.pat, str) or not self._config.pat.strip():
            raise DerivAuthFailure(DerivAuthErrorCode.MISSING_TOKEN)
        try:
            response = await self._transport.request_otp(
                app_id=self._config.app_id.strip(),
                authorization=f"Bearer {self._config.pat}",
                environment=self._config.expected_environment,
                options_account_id=self._config.options_account_id,
            )
        except DerivAuthFailure:
            self._state = DerivAuthState.FAILED
            raise
        except Exception as exc:
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.OTP_FAILURE) from exc
        if not isinstance(response, dict):
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.MALFORMED_OTP_RESPONSE)
        if response.get("error") in {"invalid_token", "invalid_pat"}:
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.INVALID_TOKEN)
        if response.get("error") == "expired_token":
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.EXPIRED_TOKEN)
        if response.get("error") == "revoked_token":
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.REVOKED_TOKEN)
        if response.get("error"):
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.OTP_FAILURE)
        url = response.get("url")
        account_id = response.get("account_id")
        environment = response.get("environment")
        if not isinstance(url, str) or not url.strip():
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.MALFORMED_OTP_RESPONSE)
        if not isinstance(account_id, str) or not account_id.strip():
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.MISSING_ACCOUNT_ID)
        if environment not in {"demo", "real"}:
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.MISSING_ENVIRONMENT)
        if self._config.options_account_id is not None and account_id.strip() != self._config.options_account_id.strip():
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.ACCOUNT_MISMATCH)
        if self._config.expected_environment is not None and environment != self._config.expected_environment:
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.ENVIRONMENT_MISMATCH)
        try:
            self._connection = await self._transport.connect_websocket(
                url.strip(), app_id=self._config.app_id.strip()
            )
        except Exception as exc:
            self._state = DerivAuthState.FAILED
            raise DerivAuthFailure(DerivAuthErrorCode.WEBSOCKET_FAILURE) from exc
        self._session = DerivAuthSession(account_id.strip(), environment, url.strip())
        self._state = DerivAuthState.READY
        return self._session

    async def close(self) -> None:
        connection, self._connection = self._connection, None
        self._session = None
        self._state = DerivAuthState.CLOSED
        if connection is not None and hasattr(connection, "close"):
            result = connection.close()
            if hasattr(result, "__await__"):
                await result

    def mark_expired(self) -> None:
        self._session = None
        self._connection = None
        self._state = DerivAuthState.FAILED
