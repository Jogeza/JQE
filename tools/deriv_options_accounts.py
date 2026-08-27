"""One-shot, non-trading discovery of Deriv Options accounts."""

from __future__ import annotations

import asyncio
import sys

from broker.deriv_auth import DerivPATOTPTransport
from config.settings import Settings


async def run() -> int:
    settings = Settings()
    if not isinstance(settings.deriv_app_id, str) or not settings.deriv_app_id.strip():
        print("RESULT=PRE_FLIGHT_FAILED")
        return 2
    if not isinstance(settings.deriv_api_token, str) or not settings.deriv_api_token.strip():
        print("RESULT=PRE_FLIGHT_FAILED")
        return 2
    transport = DerivPATOTPTransport()
    status, payload = await transport.get_options_accounts(
        app_id=settings.deriv_app_id.strip(),
        authorization=f"Bearer {settings.deriv_api_token}",
    )
    print(f"HTTP_STATUS={status}")
    if status < 200 or status >= 300 or not isinstance(payload, dict):
        print("RESULT=FAILED")
        return 1
    data = payload.get("data")
    if not isinstance(data, list):
        print("RESULT=MALFORMED_RESPONSE")
        return 1
    for account in data:
        if isinstance(account, dict):
            account_id = account.get("account_id")
            account_type = account.get("account_type")
            if isinstance(account_id, str) and isinstance(account_type, str):
                print(f"OPTIONS_ACCOUNT_ID={account_id} ENVIRONMENT={account_type}")
    print("RESULT=SUCCESS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
