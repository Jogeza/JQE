"""Single-shot, non-trading Deriv demo authentication harness."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable

from broker.deriv_auth import (
    DerivAuthConfig,
    DerivAuthFailure,
    DerivPATOTPTransport,
    DerivPATOTPSession,
    DerivAuthTransport,
)
from config.settings import Settings


def _configured(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


async def run_authentication(
    *, settings: Settings | None = None,
    transport: DerivAuthTransport | None = None,
    emit: Callable[[str], None] = print,
) -> int:
    """Run exactly one authentication attempt; returns a process exit code."""
    settings = settings or Settings()
    app_ok = _configured(settings.deriv_app_id)
    pat_ok = _configured(settings.deriv_api_token)
    account_ok = _configured(settings.deriv_options_account_id)
    demo_ok = settings.deriv_expected_environment == "demo"
    emit(f"APP_ID={'configured' if app_ok else 'missing'}")
    emit(f"PAT={'configured' if pat_ok else 'missing'}")
    emit(f"OPTIONS_ACCOUNT_ID={'configured' if account_ok else 'missing'}")
    emit(f"ENVIRONMENT={'demo' if demo_ok else 'invalid_or_missing'}")
    if not (app_ok and pat_ok and account_ok and demo_ok):
        emit("RESULT=PRE_FLIGHT_FAILED")
        return 2

    session = DerivPATOTPSession(
        DerivAuthConfig(
            settings.deriv_app_id,
            settings.deriv_api_token,
            settings.deriv_options_account_id,
            "demo",
        ),
        transport or DerivPATOTPTransport(),
    )
    try:
        result = await session.connect()
        emit("RESULT=AUTHENTICATED")
        emit("SESSION_READY=true")
        emit("ACCOUNT_IDENTITY=WEBSOCKET_VERIFIED")
        emit(f"WEBSOCKET_ACCOUNT_ID={result.account_id}")
        emit(f"ENVIRONMENT={result.environment}")
        return 0
    except DerivAuthFailure as exc:
        emit("RESULT=AUTHENTICATION_FAILED")
        emit(f"ERROR_CODE={exc.code.value}")
        emit(f"HTTP_STATUS={exc.http_status if exc.http_status is not None else 'none'}")
        emit(f"FAILURE_CATEGORY={exc.category.value if exc.category is not None else 'none'}")
        return 1
    finally:
        await session.close()
        emit("SESSION_CLOSED=true")


def main() -> int:
    return asyncio.run(run_authentication())


if __name__ == "__main__":
    sys.exit(main())
