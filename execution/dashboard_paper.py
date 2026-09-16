"""Durable, offline-only paper records for dashboard-submitted setups."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3

from broker.types import OrderRequest, OrderResult, OrderStatus, Position
from execution.market_setup import MarketSetup, PaperExecutionOutcomeDTO
from execution.paper_contract import PaperContractEngine, PaperContractSpecification
from execution.simulation_daily_guard import SQLiteSimulationDailySubmissionGuard


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class DashboardPaperStore:
    """Persist setup snapshots and paper outcomes without broker connectivity."""

    def __init__(self, path: str | Path) -> None:
        resolved = Path(path).expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(resolved)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS market_setups ("
                "setup_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS paper_outcomes ("
                "outcome_id TEXT PRIMARY KEY, setup_id TEXT NOT NULL UNIQUE, "
                "symbol TEXT NOT NULL, side TEXT NOT NULL, order_id TEXT, "
                "execution_price TEXT, quantity TEXT, quantity_unit TEXT, "
                "status TEXT NOT NULL, payload TEXT NOT NULL, recorded_at TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def save_setup(self, setup: MarketSetup) -> None:
        payload = setup.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO market_setups(setup_id,payload,created_at) VALUES(?,?,?) "
                "ON CONFLICT(setup_id) DO UPDATE SET payload=excluded.payload",
                (setup.setup_id, payload, setup.observed_at.isoformat()),
            )

    def get_setup(self, setup_id: str) -> MarketSetup | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM market_setups WHERE setup_id=?", (setup_id,)
            ).fetchone()
        return None if row is None else MarketSetup.model_validate_json(row["payload"])

    def latest_setup(self) -> MarketSetup | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM market_setups ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return None if row is None else MarketSetup.model_validate_json(row["payload"])

    def get_outcome(self, setup_id: str) -> PaperExecutionOutcomeDTO | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM paper_outcomes WHERE setup_id=?", (setup_id,)
            ).fetchone()
        return None if row is None else PaperExecutionOutcomeDTO.model_validate_json(row["payload"])

    def latest_outcome(self) -> PaperExecutionOutcomeDTO | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM paper_outcomes ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
        return None if row is None else PaperExecutionOutcomeDTO.model_validate_json(row["payload"])

    def record_outcome(self, setup: MarketSetup, outcome: PaperExecutionOutcomeDTO) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO paper_outcomes("
                "outcome_id,setup_id,symbol,side,order_id,execution_price,quantity,"
                "quantity_unit,status,payload,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    outcome.outcome_id,
                    setup.setup_id,
                    setup.symbol,
                    setup.direction,
                    outcome.order_id,
                    _decimal_text(outcome.execution_price),
                    _decimal_text(outcome.quantity),
                    outcome.quantity_unit,
                    outcome.status,
                    outcome.model_dump_json(),
                    outcome.recorded_at.isoformat(),
                ),
            )

    def open_positions(self) -> list[Position]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_outcomes WHERE status='OPENED' ORDER BY recorded_at"
            ).fetchall()
        positions: list[Position] = []
        for row in rows:
            setup = self.get_setup(row["setup_id"])
            if setup is None or setup.entry_price is None or setup.stop_loss is None or not setup.targets:
                raise ValueError("Persisted paper position is incomplete")
            try:
                quantity = Decimal(row["quantity"])
            except (InvalidOperation, TypeError) as exc:
                raise ValueError("Persisted paper quantity is invalid") from exc
            positions.append(
                Position(
                    position_id=row["order_id"], symbol=setup.symbol, side=setup.direction,
                    volume=float(quantity), open_price=float(setup.entry_price),
                    stop_loss=float(setup.stop_loss), take_profit=float(setup.targets[0]),
                    opened_at=datetime.fromisoformat(row["recorded_at"]),
                )
            )
        return positions

    def daily_counts(self, now: datetime) -> tuple[int, Decimal]:
        day = now.astimezone(timezone.utc).date().isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM paper_outcomes WHERE substr(recorded_at,1,10)=?", (day,)
            ).fetchall()
        outcomes = [PaperExecutionOutcomeDTO.model_validate_json(row["payload"]) for row in rows]
        realized_loss = sum(
            (-item.realized_pnl for item in outcomes if item.realized_pnl is not None and item.realized_pnl < 0),
            Decimal("0"),
        )
        return sum(item.status == "OPENED" for item in outcomes), realized_loss


class DashboardPaperGateway:
    """Offline execution gateway backed by JQE's deterministic paper engine."""

    def __init__(
        self, store: DashboardPaperStore, setup: MarketSetup,
        submission_guard: SQLiteSimulationDailySubmissionGuard, account_scope: str,
    ) -> None:
        self.store = store
        self.setup = setup
        self.submission_guard = submission_guard
        self.account_scope = account_scope

    async def get_positions(self) -> list[Position]:
        return self.store.open_positions()

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        if self.setup.entry_price is None or self.setup.stop_loss is None or not self.setup.targets:
            raise ValueError("Paper setup has incomplete price levels")
        engine = PaperContractEngine(PaperContractSpecification(
            minimum_stake=Decimal("0.000000000001"),
            stake_increment=Decimal("0.000000000001"),
        ))
        # The setup was built from a proven closed candle; the paper venue binds
        # execution to that exact close rather than obtaining a live quote.
        from broker.types import ClosedMarketObservation, Timeframe

        seconds = {
            "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
            "H1": 3600, "H4": 14400, "D1": 86400,
        }[self.setup.timeframe]
        opened_at = self.setup.candle_close_time - timedelta(seconds=seconds)
        price = float(self.setup.entry_price)
        observation = ClosedMarketObservation(
            canonical_symbol=self.setup.symbol,
            source="dashboard_paper",
            provider_symbol=self.setup.symbol,
            timeframe=Timeframe(self.setup.timeframe),
            candle_opened_at=opened_at,
            closed_at=self.setup.candle_close_time,
            open=price, high=price, low=price, close=price,
        )
        proposal = engine.propose(
            idempotency_key=order.idempotency_key or "",
            side=order.side,
            stake=Decimal(str(order.quantity.value)),
            stop_loss=Decimal(str(order.stop_loss)),
            take_profit=Decimal(str(order.take_profit)),
            observation=observation,
            entry_price=self.setup.entry_price,
        )
        # Offline mutation boundary: all policy checks have already passed.
        self.submission_guard.consume(self.account_scope)
        position = engine.open(proposal)
        return OrderResult(
            order_id=position.contract_id,
            status=OrderStatus.FILLED,
            symbol=position.symbol,
            side=position.side,
            volume=float(position.stake),
            filled_price=float(position.entry),
            raw={"paper": True, "network": False, "setup_id": self.setup.setup_id},
        )
