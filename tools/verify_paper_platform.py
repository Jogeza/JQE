"""Isolated end-to-end verification of JQE's supported simulation paper path.

The fixture is a deterministic rising M5 market with ordinary pullbacks and a
larger final closed-candle range.  Those prices naturally produce bullish
trend, strong momentum, and the existing legacy confidence needed by the
unchanged strategy/risk gates.  No signal or authorization result is injected.
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from api.service import ApplicationService
from broker.simulation_gateway import SimulationGateway
from broker.types import Candle, ClosedMarketObservation, OrderSide, Timeframe, TIMEFRAME_SECONDS
from config.settings import settings
from execution.dashboard_paper import DashboardPaperStore
from execution.paper_contract import PaperContractEngine, PaperContractSpecification


class PassingFixtureSimulationGateway(SimulationGateway):
    """Network-free SimulationGateway whose candles are a documented fixture."""

    async def get_candles(
        self, symbol: str, timeframe: Timeframe, count: int, end: datetime | None = None,
    ) -> list[Candle]:
        self._require_connected()
        step = TIMEFRAME_SECONDS[timeframe]
        anchor = (end or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
        start = anchor - timedelta(seconds=step * count)
        price = Decimal("100")
        candles: list[Candle] = []
        for index in range(count):
            opened = start + timedelta(seconds=step * index)
            move = Decimal("0.16") if index % 7 else Decimal("-0.04")
            close = price + move
            wick = Decimal("0.55") if index < count - 1 else Decimal("0.90")
            candles.append(Candle(
                time=opened, open=float(price), high=float(max(price, close) + wick),
                low=float(min(price, close) - wick), close=float(close), volume=50.0,
                source="simulation_fixture_passing_v1",
            ))
            price = close
        return candles


@contextmanager
def isolated_paths(root: Path) -> Iterator[None]:
    names = (
        "dashboard_paper_store_path", "dashboard_paper_intent_store_path",
        "simulation_daily_submission_store_path", "historical_data_path",
    )
    previous = {name: getattr(settings, name) for name in names}
    replacements = {
        "dashboard_paper_store_path": root / "paper.sqlite3",
        "dashboard_paper_intent_store_path": root / "intents.sqlite3",
        "simulation_daily_submission_store_path": root / "simulation_slots.sqlite3",
        "historical_data_path": root / "candles.sqlite3",
    }
    try:
        for name, value in replacements.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(settings, name, value)


def _table_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


async def verify(root: Path) -> dict[str, object]:
    if settings.broker_execution_enabled:
        raise RuntimeError("paper verification requires broker execution disabled")
    root.mkdir(parents=True, exist_ok=True)
    with isolated_paths(root):
        gateway = PassingFixtureSimulationGateway(starting_balance=settings.account_balance)
        service = ApplicationService(gateway=gateway, market_data_source=gateway)
        analysis = await service.get_active_market_analysis(
            settings.default_symbol, settings.default_timeframe, settings.default_candle_count
        )
        setup = analysis.setup
        if setup.setup_state != "READY":
            raise RuntimeError(f"documented fixture did not pass naturally: {setup.reason_codes}")

        opened = await service.execute_market_setup(setup.setup_id)
        if opened.status != "OPENED" or opened.order_id is None:
            raise RuntimeError(f"paper fill failed: {opened.reason_codes}")
        duplicate_submit = await service.execute_market_setup(setup.setup_id)

        # Reconstruct only the isolated simulation contract from its durable plan.
        # This does not call a gateway and cannot submit an order.
        store = DashboardPaperStore(settings.dashboard_paper_store_path)
        specification = PaperContractSpecification(
            minimum_stake=Decimal("0.000000000001"),
            stake_increment=Decimal("0.000000000001"),
        )
        engine = PaperContractEngine(specification)
        tf = Timeframe(setup.timeframe)
        opened_at = setup.candle_close_time - timedelta(seconds=TIMEFRAME_SECONDS[tf])
        entry_observation = ClosedMarketObservation(
            canonical_symbol=setup.symbol, source="simulation_fixture_passing_v1",
            provider_symbol=setup.symbol, timeframe=tf, candle_opened_at=opened_at,
            closed_at=setup.candle_close_time, open=float(setup.entry_price),
            high=float(setup.entry_price), low=float(setup.entry_price),
            close=float(setup.entry_price), volume=50.0,
        )
        proposal = engine.propose(
            idempotency_key=setup.setup_id, side=OrderSide(setup.direction),
            stake=Decimal(str(opened.quantity)), stop_loss=Decimal(str(setup.stop_loss)),
            take_profit=Decimal(str(setup.targets[0])), observation=entry_observation,
            entry_price=Decimal(str(setup.entry_price)),
        )
        position = engine.open(proposal)
        exit_open = setup.candle_close_time
        exit_observation = ClosedMarketObservation(
            canonical_symbol=setup.symbol, source="simulation_fixture_passing_v1",
            provider_symbol=setup.symbol, timeframe=tf, candle_opened_at=exit_open,
            closed_at=exit_open + timedelta(seconds=TIMEFRAME_SECONDS[tf]),
            open=float(setup.entry_price), high=float(setup.targets[0]) + 0.01,
            low=float(setup.entry_price), close=float(setup.targets[0]), volume=50.0,
        )
        closed = engine.observe(position.contract_id, exit_observation)
        if closed is None:
            raise RuntimeError("fixture close did not reach its target")
        durable_close = store.record_close(
            setup.setup_id, realized_pnl=closed.realized_profit,
            close_reason=closed.reason.value, recorded_at=closed.closed_at,
            message="Simulation-only paper position closed and reconciled",
        )

        # Restart: reopen stores and repeat both operations.  Unique durable IDs
        # and compare-and-set close persistence must leave one outcome.
        restarted_service = ApplicationService(gateway=gateway, market_data_source=gateway)
        duplicate_after_restart = await restarted_service.execute_market_setup(setup.setup_id)
        restarted_store = DashboardPaperStore(settings.dashboard_paper_store_path)
        duplicate_close = restarted_store.record_close(
            setup.setup_id, realized_pnl=closed.realized_profit,
            close_reason=closed.reason.value, recorded_at=closed.closed_at,
            message="duplicate close must not replace the original",
        )
        monitoring = restarted_service.get_offline_monitoring()

        report: dict[str, object] = {
            "mode": "ISOLATED_SIMULATION_ONLY",
            "data_source": "SIMULATION / simulation_fixture_passing_v1",
            "broker_execution_enabled": settings.broker_execution_enabled,
            "fixture": {
                "version": "simulation_fixture_passing_v1",
                "description": "rising M5 closes with ordinary pullbacks and a larger final closed-candle range",
                "signal_overridden": False,
            },
            "decisions": {
                "signal": analysis.signal.model_dump(mode="json"),
                "setup_id": setup.setup_id,
                "setup_state": setup.setup_state,
                "risk": setup.risk_authorization.model_dump(mode="json"),
                "policy": setup.execution_authorization.model_dump(mode="json"),
            },
            "open": opened.model_dump(mode="json"),
            "contract_id": position.contract_id,
            "close_id": closed.close_id,
            "close": durable_close.model_dump(mode="json"),
            "duplicates": {
                "before_restart": duplicate_submit.model_dump(mode="json"),
                "after_restart": duplicate_after_restart.model_dump(mode="json"),
                "close_id_unchanged": duplicate_close.recorded_at == durable_close.recorded_at,
                "outcome_rows": _table_count(root / "paper.sqlite3", "paper_outcomes"),
                "intent_rows": _table_count(root / "intents.sqlite3", "intent_records"),
                "open_positions_after_close": len(restarted_store.open_positions()),
            },
            "simulation_slots": {
                "isolated_count": _table_count(root / "simulation_slots.sqlite3", "simulation_daily_submission_counter"),
                "broker_account_slots_consumed": 0,
            },
            "monitoring_api": monitoring.model_dump(mode="json"),
        }
        (root / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-root", type=Path, default=Path("state/paper_platform_verification"))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(verify(args.state_root)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
