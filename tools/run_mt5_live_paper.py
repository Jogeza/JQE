"""Bounded command-line launcher for MT5 DEMO live-paper campaigns only."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from broker.factory import get_gateway
from broker.types import Timeframe
from config.settings import Settings
from core.exceptions import ConfigurationError
from tools import live_paper_campaign


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a bounded MT5 DEMO live-paper campaign")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", choices=[item.value for item in Timeframe], default="M15")
    parser.add_argument("--max-candles", type=int, default=1)
    parser.add_argument("--max-duration-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    configured = Settings()
    if not configured.broker_execution_enabled:
        raise ConfigurationError(
            "JQE_BROKER_EXECUTION_ENABLED is disabled; MT5 live-paper execution refused"
        )
    runtime = Settings(
        broker="mt5_demo",
        broker_execution_enabled=configured.broker_execution_enabled,
        campaign_mode="live_paper",
        mt5_expected_environment="demo",
        live_paper_max_candles=args.max_candles,
        live_paper_max_duration_seconds=args.max_duration_seconds,
    )
    if runtime.mt5_expected_environment != "demo" or runtime.broker != "mt5_demo":
        raise RuntimeError("MT5 live-paper launcher refuses non-DEMO configuration")
    live_paper_campaign.settings = runtime
    gateway = get_gateway(runtime)
    summary = await live_paper_campaign.run_live_paper_campaign(
        symbol=args.symbol,
        timeframe=Timeframe(args.timeframe),
        gateway=gateway,
        output=args.output,
        evidence_path=args.evidence,
        ledger_path=args.ledger,
        max_candles=args.max_candles,
        max_duration_seconds=args.max_duration_seconds,
        poll_interval_seconds=args.poll_seconds,
    )
    print(f"RESULT={summary['session']['status']}")
    print(f"SESSION_ID={summary['session']['session_id']}")
    print(f"EVIDENCE={summary['session']['evidence_path']}")
    print(f"LEDGER={summary['session']['position_ledger_path']}")
    return 0


def main() -> int:
    args = _arguments()
    if args.max_candles <= 0 or args.max_duration_seconds <= 0:
        raise SystemExit("All campaign bounds must be positive")
    try:
        return asyncio.run(_run(args))
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
