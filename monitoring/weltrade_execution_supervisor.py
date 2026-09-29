"""Explicitly armed Weltrade demo loop; all orders use ``main.run`` guards."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from broker.scope import enforce_weltrade_only
from config.settings import settings
from execution.safety import DailyStateAuthority, EmergencyStopState
from main import _armed_by_supervisor, run_watchlist
from monitoring.weltrade_close_monitor import monitor_weltrade_closes
from monitoring.observation_supervisor import ObservationMutex
from tools.evaluate_execution_safety import evaluate


HEARTBEAT_PATH = Path("state/weltrade_execution_supervisor_heartbeat.json")
MUTEX_PATH = Path("state/weltrade_execution_supervisor.lock")


def _publish(*, cycle: int, status: str, reason: str | None = None) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(), "cycle_number": cycle,
        "status": status, "reason": reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "broker": "weltrade", "execution_enabled": settings.broker_execution_enabled,
    }
    temporary = HEARTBEAT_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(HEARTBEAT_PATH)


def _require_process_authorization() -> None:
    # A shared .env value cannot arm this process. The operator must place the
    # flag in this supervisor's own environment when launching it.
    if os.environ.get("JQE_BROKER_EXECUTION_ENABLED", "").strip().lower() != "true":
        raise RuntimeError("Weltrade execution requires a process-local true flag")
    if settings.broker_execution_enabled is not True:
        raise RuntimeError("Weltrade execution setting is disabled")
    enforce_weltrade_only(broker=settings.effective_broker, market_data_source=settings.market_data_source)
    if settings.emergency_stop is not EmergencyStopState.CLEAR:
        raise RuntimeError("Emergency stop is not CLEAR")


async def run_cycle_once() -> tuple:
    """Preflight, then delegate every candidate to the canonical guarded path."""
    _require_process_authorization()
    await monitor_weltrade_closes(settings)
    preflight = evaluate(settings)
    if (
        preflight.daily_state_authority is not DailyStateAuthority.AUTHORITATIVE
        or preflight.reason_codes != ("READ_ONLY_PREFLIGHT_NO_ORDER_INTENT",)
    ):
        raise RuntimeError("Read-only Weltrade preflight blocked the execution cycle")
    with _armed_by_supervisor():
        return await run_watchlist()


async def run_forever() -> None:
    cycle = 0
    reason = None
    try:
        _require_process_authorization()
        with ObservationMutex(MUTEX_PATH):
            await monitor_weltrade_closes(settings)  # Catch up before the first timed cycle.
            _publish(cycle=cycle, status="STARTING")
            while True:
                now = datetime.now(timezone.utc)
                wait_seconds = 300 - (int(now.timestamp()) % 300)
                await asyncio.sleep(wait_seconds + settings.observation_close_grace_seconds)
                try:
                    results = await run_cycle_once()
                except Exception as exc:
                    reason = type(exc).__name__
                    _publish(cycle=cycle, status="BLOCKED", reason=reason)
                    raise
                cycle += 1
                _publish(cycle=cycle, status="RUNNING", reason=f"{len(results)} pairs evaluated")
    except BaseException as exc:
        reason = type(exc).__name__
        raise
    finally:
        _publish(cycle=cycle, status="STOPPED", reason=reason)
