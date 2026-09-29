"""Start the explicitly armed Weltrade demo execution supervisor."""

from __future__ import annotations

import asyncio

from monitoring.weltrade_execution_supervisor import run_forever


if __name__ == "__main__":
    asyncio.run(run_forever())
