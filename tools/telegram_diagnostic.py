"""Validate Telegram configuration; send only with explicit --send-test."""

from __future__ import annotations

import argparse
import asyncio

from config.settings import Settings
from notifications.telegram import TelegramConfigurationError, telegram_gateway_from_settings


async def run(*, send_test: bool = False) -> int:
    settings = Settings()
    try:
        gateway = telegram_gateway_from_settings(settings)
    except TelegramConfigurationError:
        print("TELEGRAM=UNAVAILABLE")
        print("CONFIGURATION=INCOMPLETE")
        return 2
    if gateway is None:
        print("TELEGRAM=DISABLED")
        return 0
    print("TELEGRAM=CONFIGURED")
    if not send_test:
        print("NETWORK=NOT_CONTACTED")
        return 0
    try:
        await gateway.send_text("JQE Telegram observability diagnostic")
    except Exception:
        print("SEND_TEST=FAILED")
        return 1
    print("SEND_TEST=DELIVERED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-test", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(send_test=args.send_test))


if __name__ == "__main__":
    raise SystemExit(main())
