"""Serialized, broker-independent continuous paper runtime."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Iterable

from broker.types import ClosedMarketObservation
from core.exceptions import BrokerConnectionError, MarketDataError
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.paper_contract import PaperContractEngine, PaperContractExecutionGateway
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService


class ObservationClaim(str, Enum):
    NEW = "NEW"
    DUPLICATE = "DUPLICATE"
    OLD = "OLD"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class PaperEntry:
    intent: ExecutionIntent
    context: ExecutionContext


@dataclass(frozen=True, slots=True)
class PaperRuntimeHeartbeat:
    runtime_mode: str = "paper_continuous"
    running: bool = False
    started_at: str | None = None
    last_cycle_at: str | None = None
    last_processed_observation: str | None = None
    symbols_monitored: tuple[str, ...] = ()
    open_paper_positions: int = 0
    cycles_completed: int = 0
    last_signal: str | None = None
    last_action: str = "IDLE"
    last_error: str | None = None
    notification_state: str = "DISABLED"
    shutdown_state: str = "STOPPED"
    paper_execution_enabled: bool = False
    broker_execution_enabled: bool = False
    market_data_source: str = "UNSPECIFIED"


class PaperRuntimeStateStore:
    """Durable observation dedupe and read-only heartbeat projection."""

    def __init__(self, path: str | Path, *, initialize: bool = True) -> None:
        resolved = Path(path).expanduser().resolve()
        self.path = str(resolved)
        if initialize:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS observations (scope TEXT PRIMARY KEY, closed_at TEXT NOT NULL, state TEXT NOT NULL)")
                connection.execute("CREATE TABLE IF NOT EXISTS heartbeat (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    def begin(self, observation: ClosedMarketObservation) -> ObservationClaim:
        scope = f"{observation.canonical_symbol.strip().upper()}:{observation.timeframe.value}"
        timestamp = observation.closed_at.astimezone(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT closed_at, state FROM observations WHERE scope=?", (scope,)).fetchone()
            if row is not None:
                prior = datetime.fromisoformat(row[0])
                if row[1] == "PROCESSING":
                    return ObservationClaim.UNRESOLVED
                if observation.closed_at == prior:
                    return ObservationClaim.DUPLICATE
                if observation.closed_at < prior:
                    return ObservationClaim.OLD
            connection.execute(
                "INSERT INTO observations(scope, closed_at, state) VALUES(?,?,?) ON CONFLICT(scope) DO UPDATE SET closed_at=excluded.closed_at,state=excluded.state",
                (scope, timestamp, "PROCESSING"),
            )
        return ObservationClaim.NEW

    def complete(self, observation: ClosedMarketObservation) -> None:
        scope = f"{observation.canonical_symbol.strip().upper()}:{observation.timeframe.value}"
        with self._connect() as connection:
            connection.execute("UPDATE observations SET state='COMPLETE' WHERE scope=?", (scope,))

    def publish(self, heartbeat: PaperRuntimeHeartbeat) -> None:
        payload = json.dumps(asdict(heartbeat), sort_keys=True)
        with self._connect() as connection:
            connection.execute("INSERT INTO heartbeat(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))

    def read(self) -> PaperRuntimeHeartbeat:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM heartbeat WHERE id=1").fetchone()
        if row is None:
            return PaperRuntimeHeartbeat()
        # Persisted payloads may outlive the running code version; unknown
        # fields must not make the projection unreadable.
        payload = json.loads(row[0])
        known = {field.name for field in fields(PaperRuntimeHeartbeat)}
        return PaperRuntimeHeartbeat(**{key: value for key, value in payload.items() if key in known})


ObservationSource = Callable[[], Awaitable[list[ClosedMarketObservation]]]
DecisionBuilder = Callable[[list[ClosedMarketObservation]], Awaitable[PaperEntry | None]]


def _venue_block_code(reason: str) -> str:
    """Return a stable heartbeat label without changing execution semantics."""
    normalized = reason.casefold().replace("-", "_").replace(" ", "_")
    if (
        ("minimum" in normalized and any(token in normalized for token in ("stake", "quantity", "lot", "volume")))
        or "min_stake" in normalized
        or "min_quantity" in normalized
        or "min_lot" in normalized
    ):
        return "MIN_STAKE"
    return "VENUE_REJECTED"


class ContinuousPaperRuntime:
    """One serialized loop; all opens enter through ``AsyncTradeExecutor``."""

    def __init__(
        self, *, observation_source: ObservationSource, decision_builder: DecisionBuilder,
        intent_records: SQLiteIntentRecordStore, state_store: PaperRuntimeStateStore,
        symbols: Iterable[str], enabled: bool, runtime_mode: str,
        poll_seconds: float = 60.0, max_backoff_seconds: float = 300.0,
        engine: PaperContractEngine | None = None,
        notifications: JQENotificationEvents | None = None,
        clock: Callable[[], datetime] | None = None,
        market_data_source: str = "UNSPECIFIED",
    ) -> None:
        if not enabled or runtime_mode != "paper_continuous":
            raise ValueError("continuous paper runtime requires explicit opt-in")
        if poll_seconds < 1 or max_backoff_seconds < poll_seconds:
            raise ValueError("paper runtime polling configuration is invalid")
        previous = state_store.read()
        if previous.open_paper_positions:
            raise RuntimeError("paper restart blocked: open position reconstruction is unavailable")
        self.source, self.decide, self.records, self.state_store = observation_source, decision_builder, intent_records, state_store
        self.engine = engine or PaperContractEngine()
        self.events = notifications or JQENotificationEvents(NotificationService())
        self.poll_seconds, self.max_backoff_seconds = poll_seconds, max_backoff_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stop_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self.heartbeat = replace(
            previous,
            symbols_monitored=tuple(symbols),
            paper_execution_enabled=True,
            broker_execution_enabled=False,
            market_data_source=market_data_source,
        )

    def request_stop(self) -> None:
        self.stop_event.set()

    async def run_once(self) -> PaperRuntimeHeartbeat:
        if self._lock.locked():
            raise RuntimeError("paper runtime cycle overlap rejected")
        async with self._lock:
            now = self.clock()
            try:
                observations = await self.source()
                if not observations:
                    raise RuntimeError("market data unavailable")
                if any(not item.is_closed_at(now) for item in observations):
                    raise ValueError("forming paper observation rejected")
                if any(
                    current.closed_at <= previous.closed_at
                    for previous, current in zip(observations, observations[1:])
                ):
                    raise ValueError("out-of-order paper observations rejected")
                observation = observations[-1]
                claim = self.state_store.begin(observation)
                if claim is ObservationClaim.UNRESOLVED:
                    raise RuntimeError("unresolved observation processing state")
                if claim is not ObservationClaim.NEW:
                    action = "DUPLICATE_IGNORED" if claim is ObservationClaim.DUPLICATE else "OLD_IGNORED"
                    self.heartbeat = replace(self.heartbeat, last_cycle_at=now.isoformat(), last_action=action, last_error=None)
                    self.state_store.publish(self.heartbeat)
                    return self.heartbeat
                closed_count = 0
                for position in self.engine.positions:
                    if position.state.value == "CLOSED":
                        continue
                    if observation.canonical_symbol == position.symbol and observation.closed_at > position.last_observed_at:
                        closed = self.engine.observe(position.contract_id, observation)
                        if closed is not None:
                            closed_count += 1
                            reconciled = self.engine.reconcile(position.contract_id)
                            if reconciled.state.value != "CLOSED":
                                raise RuntimeError("paper reconciliation mismatch")
                            await self.events.paper_event(kind=closed.reason.value, facts={"Contract": closed.contract_id, "P/L": str(closed.realized_profit)})
                            await self.events.paper_event(kind="CLOSED", facts={"Contract": closed.contract_id, "P/L": str(closed.realized_profit)})
                entry = await self.decide(observations)
                action, last_signal, cycle_error = (
                    ("POSITION_CLOSED", None, None)
                    if closed_count
                    else ("NO_SIGNAL", "NO_TRADE", None)
                )
                if entry is not None:
                    last_signal = entry.intent.side.value if hasattr(entry.intent.side, "value") else str(entry.intent.side)
                    await self.events.paper_event(kind="SIGNAL", facts={"Symbol": entry.intent.symbol, "Signal": last_signal})
                    venue = PaperContractExecutionGateway(
                        self.engine, observation, observed_at=now,
                        authorized_risk_amount=__import__("decimal").Decimal(str(entry.intent.authorized_risk_amount)),
                        entry_price=__import__("decimal").Decimal(str(entry.intent.entry)),
                    )
                    result = await AsyncTradeExecutor(venue, self.records).submit(entry.intent, entry.context)
                    if result.state is ReconciliationState.ALREADY_EXECUTED and result.order_id:
                        action = "POSITION_OPENED"
                        await self.events.paper_event(kind="OPENED", facts={"Contract": result.order_id, "Symbol": entry.intent.symbol})
                    elif result.decision.allowed and result.state is ReconciliationState.UNKNOWN:
                        cycle_error = result.reason or "Submission outcome unknown"
                        action = f"BLOCKED:{_venue_block_code(cycle_error)}"
                        await self.events.paper_event(kind="BLOCKED", facts={"Decision": action.split(":", 1)[1], "Details": cycle_error})
                    elif result.decision.allowed and result.state is ReconciliationState.REJECTED:
                        cycle_error = result.reason or "Broker rejected order"
                        action = "BLOCKED:VENUE_REJECTED"
                        await self.events.paper_event(kind="BLOCKED", facts={"Decision": "VENUE_REJECTED", "Details": cycle_error})
                    else:
                        action = f"BLOCKED:{result.decision.code.value}"
                        await self.events.paper_event(kind="BLOCKED", facts={"Decision": result.decision.code.value})
                self.state_store.complete(observation)
                open_count = sum(1 for item in self.engine.positions if item.state.value != "CLOSED")
                self.heartbeat = replace(
                    self.heartbeat, last_cycle_at=now.isoformat(), last_processed_observation=observation.closed_at.isoformat(),
                    open_paper_positions=open_count, cycles_completed=self.heartbeat.cycles_completed + 1,
                    last_signal=last_signal, last_action=action, last_error=cycle_error,
                    notification_state=self.events.service.observation.status.value,
                )
            except Exception as exc:
                action = "BLOCKED:MARKET_DATA" if isinstance(exc, (MarketDataError, BrokerConnectionError)) else "ERROR"
                self.heartbeat = replace(self.heartbeat, last_cycle_at=now.isoformat(), last_action=action, last_error=type(exc).__name__)
                await self.events.paper_event(kind="RUNTIME_ERROR", facts={"Category": type(exc).__name__})
            self.state_store.publish(self.heartbeat)
            return self.heartbeat

    async def run(self, *, once: bool = False) -> PaperRuntimeHeartbeat:
        started = self.clock().isoformat()
        self.heartbeat = replace(self.heartbeat, running=True, started_at=started, shutdown_state="RUNNING")
        self.state_store.publish(self.heartbeat)
        await self.events.paper_event(kind="RUNTIME_STARTED", facts={"Mode": "PAPER_CONTINUOUS"})
        backoff = self.poll_seconds
        try:
            while not self.stop_event.is_set():
                result = await self.run_once()
                if once:
                    break
                backoff = min(self.max_backoff_seconds, backoff * 2) if result.last_error else self.poll_seconds
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=backoff)
                except TimeoutError:
                    pass
        finally:
            self.heartbeat = replace(self.heartbeat, running=False, shutdown_state="STOPPED")
            self.state_store.publish(self.heartbeat)
            await self.events.paper_event(kind="RUNTIME_STOPPED", facts={"State": "STOPPED"})
        return self.heartbeat
