"""Candle-close observation daemon with telemetry-only capabilities."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

import pandas as pd

from broker.mt5_telemetry import MT5Telemetry, verified_demo_mt5_telemetry
from broker.types import ClosedMarketObservation, TIMEFRAME_SECONDS, Timeframe
from config.settings import Settings, settings
from core.data_validator import validate_market_data
from core.exceptions import BrokerAuthenticationError, BrokerConnectionError, MarketDataError, UnsafeBrokerAccountError
from core.indicators import calculate_indicators
from core.logger import logger
from core.regime import detect_regime
from data.market_observation import closed_observations_from_candles, provider_symbol_for
from data.watchlist import WatchPair, WatchlistStore
from notifications.telegram import InstrumentDigestSnapshot, TelegramDigestService, format_daily_digest
from research.campaign_provenance import CampaignEvidence, canonical_json
from strategy.pipeline import generate_trading_signal

if TYPE_CHECKING:
    from execution.daily_instrument_guard import DailyInstrumentTradeGuard


def parse_watch_list(value: str) -> tuple[WatchPair, ...]:
    pairs: list[WatchPair] = []
    seen: set[str] = set()
    for item in value.split(","):
        parts = item.strip().rsplit(":", 1)
        if len(parts) != 2 or not parts[0].strip():
            raise ValueError("Observation symbols must use SYMBOL:TIMEFRAME pairs")
        pair = WatchPair(parts[0].strip().upper(), Timeframe(parts[1].strip().upper()))
        if pair.scope not in seen:
            pairs.append(pair)
            seen.add(pair.scope)
    if not pairs:
        raise ValueError("At least one observation symbol is required")
    return tuple(pairs)


@dataclass(frozen=True, slots=True)
class DaemonConfig:
    watches: tuple[WatchPair, ...]
    evidence_path: Path
    close_grace_seconds: float
    max_backoff_seconds: float
    heartbeat_stale_cycles: int
    watchlist_store: WatchlistStore | None = None
    poll_interval_seconds: float = 5.0

    @classmethod
    def from_settings(cls, source: Settings) -> "DaemonConfig":
        store = (
            WatchlistStore(source.watchlist_store_path)
            if getattr(source, "watchlist_store_path", None)
            else None
        )
        return cls(
            watches=parse_watch_list(source.observation_symbols),
            evidence_path=Path(source.observation_evidence_path),
            close_grace_seconds=source.observation_close_grace_seconds,
            max_backoff_seconds=source.observation_max_backoff_seconds,
            heartbeat_stale_cycles=source.observation_heartbeat_stale_cycles,
            watchlist_store=store,
        )


@dataclass(frozen=True, slots=True)
class DaemonHeartbeat:
    running: bool
    healthy: bool
    updated_at: str
    last_success_at: str | None
    last_error: str | None
    cycles_completed: int
    session_id: str


class ObservationDaemonStore:
    """Daemon cursor and heartbeat colocated with campaign evidence."""

    def __init__(self, path: Path, session_id: str) -> None:
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS campaign(session_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,status TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS evidence(session_id TEXT NOT NULL,event_id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(session_id,event_id))")
            connection.execute("CREATE TABLE IF NOT EXISTS observation_cursor(scope TEXT PRIMARY KEY,closed_at TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS observation_heartbeat(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS digest_sent_log (
                    utc_date TEXT PRIMARY KEY,
                    sent_at  TEXT NOT NULL
                )"""
            )
            connection.execute(
                "INSERT OR IGNORE INTO campaign VALUES(?,?,?)",
                (session_id, canonical_json({"kind": "READ_ONLY_OBSERVATION_DAEMON"}), "RUNNING"),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def last_close(self, scope: str) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute("SELECT closed_at FROM observation_cursor WHERE scope=?", (scope,)).fetchone()
        return datetime.fromisoformat(row[0]) if row else None

    def append_signal(self, pair: WatchPair, observation: ClosedMarketObservation, facts: dict[str, object]) -> bool:
        event_id = f"observation-{pair.scope}-{observation.closed_at.isoformat()}"
        event = CampaignEvidence(event_id, "SIGNAL", None, observation.closed_at.isoformat(), facts)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute("SELECT closed_at FROM observation_cursor WHERE scope=?", (pair.scope,)).fetchone()
            if prior and datetime.fromisoformat(prior[0]) >= observation.closed_at:
                connection.rollback()
                return False
            connection.execute("INSERT INTO evidence VALUES(?,?,?)", (self.session_id, event_id, canonical_json(asdict(event))))
            connection.execute(
                "INSERT INTO observation_cursor VALUES(?,?) ON CONFLICT(scope) DO UPDATE SET closed_at=excluded.closed_at",
                (pair.scope, observation.closed_at.isoformat()),
            )
            connection.commit()
        return True

    def append_error(self, pair: WatchPair, category: str, observed_at: datetime) -> None:
        event = CampaignEvidence(
            f"error-{pair.scope}-{uuid4().hex}", "OBSERVATION_ERROR", None,
            observed_at.isoformat(), {"symbol": pair.symbol, "timeframe": pair.timeframe.value, "category": category},
        )
        with self._connect() as connection:
            connection.execute("INSERT INTO evidence VALUES(?,?,?)", (self.session_id, event.event_id, canonical_json(asdict(event))))

    def publish(self, heartbeat: DaemonHeartbeat) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO observation_heartbeat VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (canonical_json(asdict(heartbeat)),),
            )

    def health(self, *, now: datetime, maximum_age: timedelta) -> DaemonHeartbeat:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM observation_heartbeat WHERE id=1").fetchone()
        if not row:
            return DaemonHeartbeat(False, False, now.isoformat(), None, "NOT_STARTED", 0, self.session_id)
        heartbeat = DaemonHeartbeat(**json.loads(row[0]))
        age = now - datetime.fromisoformat(heartbeat.updated_at)
        if age > maximum_age:
            return DaemonHeartbeat(False, False, heartbeat.updated_at, heartbeat.last_success_at, "STALE_HEARTBEAT", heartbeat.cycles_completed, heartbeat.session_id)
        return heartbeat

    def digest_already_sent(self, utc_date: str) -> bool:
        """Return True if a digest has already been durably recorded for *utc_date*."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM digest_sent_log WHERE utc_date=?", (utc_date,)
            ).fetchone()
        return row is not None

    def mark_digest_sent(self, utc_date: str, sent_at: datetime) -> None:
        """Durably record that the daily digest was dispatched for *utc_date*."""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO digest_sent_log (utc_date, sent_at) VALUES (?, ?)",
                (utc_date, sent_at.isoformat()),
            )

    def last_signal_facts(self, scope: str) -> dict | None:
        """Return the most-recently stored evidence payload for *scope*, or None."""
        with self._connect() as connection:
            # evidence rows for a scope are keyed observation-<scope>-<iso-ts>;
            # fetch the lexicographically latest one.
            row = connection.execute(
                """SELECT payload FROM evidence
                   WHERE event_id LIKE ? AND json_extract(payload, '$.event_type') = 'SIGNAL'
                   ORDER BY event_id DESC LIMIT 1""",
                (f"observation-{scope}-%",),
            ).fetchone()
        if row is None:
            return None
        try:
            outer = json.loads(row[0])
            # CampaignEvidence stores facts inside the 'facts' key
            return outer.get("facts") or outer
        except (json.JSONDecodeError, AttributeError):
            return None


def next_close_boundary(pair: WatchPair, now: datetime) -> datetime:
    seconds = TIMEFRAME_SECONDS[pair.timeframe]
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(((epoch // seconds) + 1) * seconds, tz=timezone.utc)


def _evaluate(observations: list[ClosedMarketObservation], symbol: str) -> tuple[dict[str, object], str]:
    frame = pd.DataFrame([{
        "time": item.candle_opened_at, "open": item.open, "high": item.high,
        "low": item.low, "close": item.close, "volume": item.volume, "source": item.source,
    } for item in observations])
    if not validate_market_data(frame):
        raise MarketDataError("Observation market data failed validation", symbol=symbol)
    frame = calculate_indicators(frame)
    regime = detect_regime(frame)
    return generate_trading_signal(frame, symbol, regime=regime), str(regime)


# Quality labels from SignalScorer that indicate a tradeable signal
_TRADEABLE_QUALITY: frozenset[str] = frozenset({"HIGH", "GOOD"})


class DigestAssembler:
    """Assembles real InstrumentDigestSnapshot objects from durable evidence.

    Reads the latest signal facts for each watch pair from *store*, and
    optionally queries *trade_guard* for today's submission count.  This
    class has no import of execution policy or order submission code —
    it only calls the read-only ``DailyInstrumentTradeGuard.usage()``
    method when one is supplied.
    """

    def __init__(
        self,
        store: ObservationDaemonStore,
        trade_guard: "DailyInstrumentTradeGuard | None" = None,
        account_scope: str = "default",
    ) -> None:
        self._store = store
        self._trade_guard = trade_guard
        self._account_scope = account_scope

    def build_snapshots(
        self,
        pairs: tuple[WatchPair, ...],
        *,
        at: datetime | None = None,
    ) -> list[InstrumentDigestSnapshot]:
        """Return one snapshot per *pair* using the latest persisted evidence."""
        snapshots: list[InstrumentDigestSnapshot] = []
        cap_limit = getattr(self._trade_guard, "limit", 20) if self._trade_guard else 20
        for pair in pairs:
            facts = self._store.last_signal_facts(pair.scope)
            if facts is None:
                conclusion = "NO_TRADE"
                quality_score: int | float | None = None
                quality_label = "POOR"
            else:
                conclusion = str(facts.get("conclusion", "NO_TRADE"))
                raw_score = facts.get("quality_score") or facts.get("confidence")
                quality_score = float(raw_score) if raw_score is not None else None
                quality_label = str(facts.get("quality", "POOR"))
            is_steady = conclusion != "NO_TRADE" and quality_label in _TRADEABLE_QUALITY
            if self._trade_guard is not None:
                try:
                    usage = self._trade_guard.usage(
                        self._account_scope, pair.symbol, at=at
                    )
                    cap_count = usage.count
                    cap_limit = usage.limit
                except Exception:
                    cap_count = 0
            else:
                cap_count = 0
            snapshots.append(InstrumentDigestSnapshot(
                symbol=pair.symbol,
                timeframe=pair.timeframe.value,
                conclusion=conclusion,
                quality_score=quality_score,
                is_steady=is_steady,
                cap_count=cap_count,
                cap_limit=cap_limit,
            ))
        return snapshots

    async def get_digest_snapshots(self) -> list[InstrumentDigestSnapshot]:
        """Protocol-compatible async wrapper (TelegramDigestProvider)."""
        raise NotImplementedError("Call build_snapshots() directly from the daemon loop")


class ObservationDaemon:
    EXPECTED_ERRORS = (BrokerAuthenticationError, BrokerConnectionError, MarketDataError, UnsafeBrokerAccountError)

    def __init__(
        self,
        config: DaemonConfig,
        telemetry_factory: Callable[[], MT5Telemetry],
        watchlist_store: WatchlistStore | None = None,
        telegram_digest_service: TelegramDigestService | None = None,
        digest_assembler: DigestAssembler | None = None,
    ) -> None:
        self.config = config
        self.telemetry_factory = telemetry_factory
        self.watchlist_store = watchlist_store or config.watchlist_store
        self.session_id = uuid4().hex
        self.store = ObservationDaemonStore(config.evidence_path, self.session_id)
        self.cycles_completed = 0
        self.last_success_at: str | None = None
        self._telegram_digest_service = telegram_digest_service
        self._digest_assembler = digest_assembler

    def get_active_watches(self) -> tuple[WatchPair, ...]:
        if self.watchlist_store is not None:
            pairs = self.watchlist_store.get_watch_pairs()
            if pairs:
                return pairs
        return self.config.watches

    async def observe_pair(self, telemetry: MT5Telemetry, pair: WatchPair, now: datetime) -> bool:
        candles = await telemetry.get_candles(pair.symbol, pair.timeframe, 501)
        observations = closed_observations_from_candles(
            candles=candles, canonical_symbol=pair.symbol,
            provider_symbol=provider_symbol_for(canonical_symbol=pair.symbol, source="mt5"),
            source="mt5_demo", timeframe=pair.timeframe, observed_at=now,
        )
        latest = observations[-1]
        prior = self.store.last_close(pair.scope)
        if prior and latest.closed_at <= prior:
            return False
        interval = TIMEFRAME_SECONDS[pair.timeframe]
        missed = max(0, int((latest.closed_at - prior).total_seconds() // interval) - 1) if prior else 0
        if missed:
            logger.warning("OBSERVATION_GAP scope={} missed_candles={} action=SKIP_TO_LATEST", pair.scope, missed)
        signal, regime = _evaluate(observations[-500:], pair.symbol)
        age = max(0.0, (now - latest.closed_at).total_seconds())
        freshness = "fresh" if age <= interval else "stale"
        conclusion = str(signal.get("signal", "NO_TRADE"))
        appended = self.store.append_signal(pair, latest, {
            "symbol": pair.symbol, "timeframe": pair.timeframe.value,
            "conclusion": conclusion, "direction": conclusion,
            "quality_score": signal.get("confidence"), "confidence": signal.get("confidence"),
            "quality": signal.get("quality", "POOR"),
            "data_freshness": freshness, "regime": regime,
            "observed_at": now.isoformat(), "candle_closed_at": latest.closed_at.isoformat(),
            "expires_at": (latest.closed_at + timedelta(seconds=interval)).isoformat(),
            "missed_candles": missed,
        })
        if appended:
            self.cycles_completed += 1
            self.last_success_at = now.isoformat()
        return appended

    def _heartbeat(self, now: datetime, *, healthy: bool, error: str | None) -> None:
        heartbeat = DaemonHeartbeat(
            True, healthy, now.isoformat(), self.last_success_at,
            error, self.cycles_completed, self.session_id,
        )
        self.store.publish(heartbeat)
        logger.info(
            "OBSERVATION_HEARTBEAT healthy={} cycles_completed={} last_success_at={} error={}",
            healthy, self.cycles_completed, self.last_success_at, error or "NONE",
        )

    async def run_forever(self) -> None:
        backoff = 1.0
        while True:
            telemetry = self.telemetry_factory()
            try:
                await telemetry.connect()
                account = await telemetry.get_account_info()
                if (account.trade_mode or "").lower() != "demo":
                    raise UnsafeBrokerAccountError("Observation daemon requires verified demo identity")
                backoff = 1.0
                while True:
                    active_watches = self.get_active_watches()
                    if not active_watches:
                        await asyncio.sleep(self.config.poll_interval_seconds)
                        continue
                    now = datetime.now(timezone.utc)
                    target = min(next_close_boundary(pair, now) for pair in active_watches)
                    delay = max(0.0, (target - now).total_seconds()) + self.config.close_grace_seconds
                    if delay > self.config.poll_interval_seconds:
                        await asyncio.sleep(self.config.poll_interval_seconds)
                        continue
                    await asyncio.sleep(delay)
                    cycle_now = datetime.now(timezone.utc)
                    cycle_error: str | None = None
                    active_watches = self.get_active_watches()
                    for pair in active_watches:
                        try:
                            await self.observe_pair(telemetry, pair, cycle_now)
                        except self.EXPECTED_ERRORS as exc:
                            category = type(exc).__name__
                            logger.error("OBSERVATION_CYCLE_FAILED scope={} category={} action=CONTINUE", pair.scope, category)
                            self.store.append_error(pair, category, cycle_now)
                            cycle_error = category
                            if isinstance(exc, (BrokerAuthenticationError, BrokerConnectionError, UnsafeBrokerAccountError)):
                                raise
                    self._heartbeat(
                        cycle_now, healthy=cycle_error is None, error=cycle_error
                    )
                    await self._maybe_send_digest(cycle_now)
            except self.EXPECTED_ERRORS as exc:
                now = datetime.now(timezone.utc)
                category = type(exc).__name__
                logger.error("OBSERVATION_CONNECTION_FAILED category={} retry_seconds={}", category, backoff)
                self._heartbeat(now, healthy=False, error=category)
                await asyncio.sleep(backoff)
                backoff = min(self.config.max_backoff_seconds, backoff * 2)
            finally:
                try:
                    await telemetry.disconnect()
                except self.EXPECTED_ERRORS:
                    logger.warning("OBSERVATION_DISCONNECT_FAILED")

    async def _maybe_send_digest(self, now: datetime) -> None:
        """Send the daily digest once per UTC day if wired up."""
        if self._telegram_digest_service is None or self._digest_assembler is None:
            return
        utc_date = now.date().isoformat()
        if self.store.digest_already_sent(utc_date):
            return
        try:
            pairs = self.get_active_watches()
            snapshots = self._digest_assembler.build_snapshots(pairs, at=now)
            message = format_daily_digest(snapshots, as_of=now)
            await self._telegram_digest_service._gateway.send_text(message)
            self.store.mark_digest_sent(utc_date, now)
            logger.info("DAILY_DIGEST_SENT utc_date={} instruments={}", utc_date, len(snapshots))
        except Exception as exc:
            logger.error("DAILY_DIGEST_FAILED error={}", exc)


def main() -> int:
    config = DaemonConfig.from_settings(settings)
    daemon = ObservationDaemon(config, lambda: verified_demo_mt5_telemetry(settings))
    try:
        asyncio.run(daemon.run_forever())
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.exception("OBSERVATION_DAEMON_FATAL action=EXIT_NONZERO")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
