"""Supervised, broker-order-free observation loop.

The supervisor deliberately owns no execution objects.  It uses the
capability-restricted MT5 telemetry adapter and the existing observation
daemon's cursor/evidence store.  A stale, incomplete, or failed cycle is
recorded as unhealthy and never becomes an execution authorization.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Awaitable, Callable

from broker.mt5_telemetry import MT5Telemetry, verified_demo_mt5_telemetry
from broker.types import TIMEFRAME_SECONDS, Timeframe
from config.settings import Settings, get_settings
from core.exceptions import BrokerAuthenticationError, BrokerConnectionError, MarketDataError, UnsafeBrokerAccountError
from data.watchlist import WatchPair, WatchlistStore
from monitoring.observation_daemon import DaemonConfig, ObservationDaemon, DaemonHeartbeat


class SupervisorAlreadyRunning(RuntimeError):
    """Another supervisor instance owns the observation mutex."""


class ObservationMutex:
    """One-process lock that works across Windows Task Scheduler instances."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = None

    def __enter__(self) -> "ObservationMutex":
        self._handle = self.path.open("a+")
        if os.name == "nt":
            import msvcrt
            try:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                self._handle.close()
                self._handle = None
                raise SupervisorAlreadyRunning("observation supervisor mutex is already held") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        if os.name == "nt":
            import msvcrt
            try:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self._handle.close()
        self._handle = None


class SupervisorHeartbeat:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, payload: dict) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(self.path)


class ObservationSupervisor:
    EXPECTED_ERRORS = (BrokerAuthenticationError, BrokerConnectionError, MarketDataError, UnsafeBrokerAccountError)

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        telemetry_factory: Callable[[], MT5Telemetry] | None = None,
        resolver: Callable[[], Awaitable[dict]] | None = None,
        mutex_path: str | Path = "state/observation_supervisor.lock",
        heartbeat_path: str | Path = "state/observation_supervisor_heartbeat.json",
    ) -> None:
        self.settings = settings or get_settings()
        if self.settings.broker_execution_enabled:
            raise RuntimeError("observation supervisor refuses to start while broker execution is enabled")
        self.watchlist = WatchlistStore(self.settings.watchlist_store_path)
        self.pairs = tuple(self.watchlist.get_watch_pairs())
        if len(self.pairs) != 34:
            raise RuntimeError(f"observation supervisor requires all 34 durable watch entries; found {len(self.pairs)}")
        self.config = DaemonConfig.from_settings(self.settings)
        self.daemon = ObservationDaemon(
            self.config,
            telemetry_factory or (lambda: verified_demo_mt5_telemetry(self.settings)),
            watchlist_store=self.watchlist,
        )
        self.telemetry_factory = telemetry_factory or (lambda: verified_demo_mt5_telemetry(self.settings))
        self.resolver = resolver or self._resolve_live_daily
        self.mutex = ObservationMutex(mutex_path)
        self.heartbeat = SupervisorHeartbeat(heartbeat_path)
        self.last_resolver_day: str | None = None
        self.cycle_number = 0

    @staticmethod
    def next_m5_close(now: datetime) -> datetime:
        now = now.astimezone(timezone.utc)
        seconds = TIMEFRAME_SECONDS[Timeframe.M5]
        epoch = int(now.timestamp())
        return datetime.fromtimestamp(((epoch // seconds) + 1) * seconds, tz=timezone.utc)

    def _publish(self, *, status: str, healthy: bool, error: str | None = None, cycle_started: datetime | None = None, cycle_finished: datetime | None = None, resolver_status: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        self.heartbeat.publish({
            "mode": "OBSERVATION_ONLY",
            "execution_enabled": False,
            "status": status,
            "healthy": healthy,
            "error": error,
            "pid": os.getpid(),
            "watch_entries": len(self.pairs),
            "cycle_number": self.cycle_number,
            "cycle_started_at": cycle_started.isoformat() if cycle_started else None,
            "cycle_finished_at": cycle_finished.isoformat() if cycle_finished else None,
            "last_heartbeat_at": now.isoformat(),
            "last_resolver_day": self.last_resolver_day,
            "resolver_status": resolver_status,
            "deduplication": "ObservationDaemonStore.observation_cursor",
            "cadence": "one cycle per M5 close",
        })

    async def run_cycle_once(self, telemetry: MT5Telemetry) -> dict:
        """Observe all durable pairs once; duplicate closes are skipped by the store."""
        started = datetime.now(timezone.utc)
        errors: list[str] = []
        appended = 0
        for pair in self.pairs:
            try:
                if await self.daemon.observe_pair(telemetry, pair, started):
                    appended += 1
            except self.EXPECTED_ERRORS as exc:
                category = type(exc).__name__
                errors.append(f"{pair.scope}:{category}")
                self.daemon.store.append_error(pair, category, started)
        self.cycle_number += 1
        finished = datetime.now(timezone.utc)
        healthy = not errors and (finished - started).total_seconds() <= float(self.settings.risk_observation_freshness_seconds)
        self._publish(
            status="RUNNING" if healthy else "STALE_OR_INCOMPLETE",
            healthy=healthy,
            error=None if healthy else (";".join(errors) if errors else "CYCLE_EXCEEDED_FRESHNESS"),
            cycle_started=started, cycle_finished=finished,
        )
        return {"healthy": healthy, "appended": appended, "errors": errors, "duration_seconds": (finished - started).total_seconds()}

    async def _resolve_live_daily(self) -> dict:
        # Lazy import keeps this supervisor's module structurally free of any
        # execution boundary.  The resolver only reads rates/ticks and writes
        # shadow outcome rows; it never submits an order.
        from tools.run_shadow_outcomes import run_live
        from research.shadow_outcomes import ShadowOutcomeStore
        return await run_live(ShadowOutcomeStore(self.settings.dashboard_paper_store_path.parent / "shadow_outcomes.sqlite3"))

    async def _maybe_resolve_daily(self, now: datetime) -> dict | None:
        day = now.date().isoformat()
        if self.last_resolver_day == day:
            return None
        try:
            result = await self.resolver()
        except Exception as exc:
            self.last_resolver_day = day
            self._publish(status="RESOLVER_FAILED", healthy=False, error=type(exc).__name__, resolver_status="FAILED")
            return {"status": "FAILED", "error": type(exc).__name__}
        self.last_resolver_day = day
        self._publish(status="RUNNING", healthy=True, resolver_status="COMPLETED")
        return {"status": "COMPLETED", **result}

    async def run_forever(self) -> None:
        self._publish(status="STARTING", healthy=False, error="AWAITING_FIRST_CYCLE")
        with self.mutex:
            telemetry = self.telemetry_factory()
            await telemetry.connect()
            try:
                account = await telemetry.get_account_info()
                if (account.trade_mode or "").lower() != "demo":
                    raise UnsafeBrokerAccountError("observation supervisor requires verified demo identity")
                while True:
                    now = datetime.now(timezone.utc)
                    target = self.next_m5_close(now)
                    await asyncio.sleep(max(0.0, (target - now).total_seconds()) + float(self.settings.observation_close_grace_seconds))
                    cycle = await self.run_cycle_once(telemetry)
                    await self._maybe_resolve_daily(datetime.now(timezone.utc))
                    if not cycle["healthy"]:
                        # Continue observing for diagnostics, but the durable
                        # heartbeat stays unhealthy: a stale cycle is fail-closed.
                        await asyncio.sleep(float(self.settings.observation_close_grace_seconds))
            finally:
                await telemetry.disconnect()


async def run_observation_supervisor() -> None:
    await ObservationSupervisor().run_forever()

