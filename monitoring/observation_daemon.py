"""Candle-close observation daemon with telemetry-only capabilities."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable
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
from research.campaign_provenance import CampaignEvidence, canonical_json
from strategy.pipeline import generate_trading_signal


@dataclass(frozen=True, slots=True)
class WatchPair:
    symbol: str
    timeframe: Timeframe

    @property
    def scope(self) -> str:
        return f"{self.symbol}:{self.timeframe.value}"


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

    @classmethod
    def from_settings(cls, source: Settings) -> "DaemonConfig":
        return cls(
            watches=parse_watch_list(source.observation_symbols),
            evidence_path=Path(source.observation_evidence_path),
            close_grace_seconds=source.observation_close_grace_seconds,
            max_backoff_seconds=source.observation_max_backoff_seconds,
            heartbeat_stale_cycles=source.observation_heartbeat_stale_cycles,
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


class ObservationDaemon:
    EXPECTED_ERRORS = (BrokerAuthenticationError, BrokerConnectionError, MarketDataError, UnsafeBrokerAccountError)

    def __init__(self, config: DaemonConfig, telemetry_factory: Callable[[], MT5Telemetry]) -> None:
        self.config = config
        self.telemetry_factory = telemetry_factory
        self.session_id = uuid4().hex
        self.store = ObservationDaemonStore(config.evidence_path, self.session_id)
        self.cycles_completed = 0
        self.last_success_at: str | None = None

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
        self.store.publish(DaemonHeartbeat(True, healthy, now.isoformat(), self.last_success_at, error, self.cycles_completed, self.session_id))

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
                    now = datetime.now(timezone.utc)
                    target = min(next_close_boundary(pair, now) for pair in self.config.watches)
                    await asyncio.sleep(max(0.0, (target - now).total_seconds()) + self.config.close_grace_seconds)
                    cycle_now = datetime.now(timezone.utc)
                    cycle_error: str | None = None
                    for pair in self.config.watches:
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
