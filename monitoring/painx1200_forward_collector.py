"""Read-only prospective collector for the locked PainX 1200 M1 candidate."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from broker.mt5_telemetry import MT5Telemetry, verified_weltrade_demo_telemetry
from broker.types import Timeframe
from config.settings import Settings, get_settings
from data.watchlist import WatchPair
from monitoring.forward_shadow_sampler import ForwardShadowSamplerStore, gap_aware_resolver_kwargs
from monitoring.observation_daemon import DaemonConfig, ObservationDaemon, next_close_boundary
from monitoring.observation_supervisor import ObservationMutex
from research.painx1200_forward_candidate import candidate_record
from research.current_research_status import current_research_status
from research.shadow_outcomes import ShadowOutcomeStore, bars_from_mt5_rates, resolve_signal


# Provider spelling is case-sensitive in the Weltrade MT5 catalogue.  The
# sampler canonicalizes persisted plans to PAINX 1200.
PAIR = WatchPair("PainX 1200", Timeframe.M1)


class PainX1200ForwardCollector:
    def __init__(self, settings: Settings | None = None, *, root: str | Path = "state/painx1200_forward") -> None:
        self.settings = settings or get_settings()
        if self.settings.broker_execution_enabled:
            raise RuntimeError("forward collector refuses to start while broker execution is enabled")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        locked = Path("state/painx1200_m1_forward_candidate.json")
        if not locked.is_file() or json.loads(locked.read_text(encoding="utf-8")) != candidate_record():
            raise RuntimeError("locked PainX 1200 forward candidate record is missing or changed")
        self.sampler = ForwardShadowSamplerStore(self.root / "plans.sqlite3")
        config = DaemonConfig(
            watches=(PAIR,), evidence_path=self.root / "observations.sqlite3",
            close_grace_seconds=self.settings.observation_close_grace_seconds,
            max_backoff_seconds=self.settings.observation_max_backoff_seconds,
            heartbeat_stale_cycles=self.settings.observation_heartbeat_stale_cycles,
            watchlist_store=None, poll_interval_seconds=5.0,
        )
        self.daemon = ObservationDaemon(
            config, lambda: verified_weltrade_demo_telemetry(self.settings),
            watchlist_store=None, forward_sampler=self.sampler,
        )
        self.outcomes = ShadowOutcomeStore(self.root / "outcomes.sqlite3")
        self.mutex = ObservationMutex(self.root / "collector.lock")
        self.progress_path = self.root / "progress.json"

    @staticmethod
    def _key(value: str) -> str:
        return "".join(char.lower() for char in value if char.isalnum())

    async def _market_bars(self, count: int = 10000) -> list[Any]:
        catalogue = {self._key(info.name): info for info in (mt5.symbols_get() or ())}
        info = catalogue.get(self._key(PAIR.symbol))
        if info is None:
            return []
        raw = await asyncio.to_thread(mt5.copy_rates_from_pos, info.name, mt5.TIMEFRAME_M1, 0, count)
        return bars_from_mt5_rates(raw if raw is not None else [], point=float(info.point), source="mt5-forward-read-only")

    async def resolve(self) -> int:
        bars = await self._market_bars()
        outcomes = []
        for spec in self.sampler.load_specs():
            outcomes.append(resolve_signal(
                spec, bars, source="painx1200_forward_candidate",
                **gap_aware_resolver_kwargs(spec, bars),
            ))
        return self.outcomes.upsert(outcomes)

    def publish_progress(self, *, observed: bool, resolutions_written: int, error: str | None = None) -> dict[str, Any]:
        specs = self.sampler.load_specs()
        report = self.outcomes.report(source="painx1200_forward_candidate")
        payload = {
            "candidate_id": candidate_record()["candidate_id"],
            "research_status": current_research_status(),
            "mode": "READ_ONLY_FORWARD_SHADOW",
            "execution_enabled": False,
            "pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "fresh_closed_bar_received": observed,
            "plans_persisted": len(specs),
            "plans_by_side": {side: sum(spec.side == side for spec in specs) for side in ("BUY", "SELL")},
            "first_plan_close": specs[0].signal_close.isoformat() if specs else None,
            "last_plan_close": specs[-1].signal_close.isoformat() if specs else None,
            "resolutions_written": resolutions_written,
            "outcome_report": report,
            "error": error,
        }
        temporary = self.progress_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.progress_path)
        return payload

    async def cycle(self, telemetry: MT5Telemetry) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        observed = await self.daemon.observe_pair(telemetry, PAIR, now)
        written = await self.resolve()
        return self.publish_progress(observed=observed, resolutions_written=written)

    async def run_forever(self) -> None:
        with self.mutex:
            telemetry = verified_weltrade_demo_telemetry(self.settings)
            await telemetry.connect()
            try:
                account = await telemetry.get_account_info()
                if (account.trade_mode or "").lower() != "demo":
                    raise RuntimeError("forward collector requires a verified demo account")
                await self.cycle(telemetry)
                while True:
                    now = datetime.now(timezone.utc)
                    target = next_close_boundary(PAIR, now)
                    await asyncio.sleep(max(0.0, (target - now).total_seconds()) + self.settings.observation_close_grace_seconds)
                    try:
                        await self.cycle(telemetry)
                    except Exception as exc:
                        self.publish_progress(observed=False, resolutions_written=0, error=type(exc).__name__)
            finally:
                await telemetry.disconnect()


async def run_painx1200_forward_collector() -> None:
    await PainX1200ForwardCollector().run_forever()
