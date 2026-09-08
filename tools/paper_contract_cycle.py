"""Run exactly one deterministic offline paper-contract lifecycle."""

import asyncio
import gc
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from broker.types import ClosedMarketObservation, ExecutionQuantity, ExecutionQuantityUnit, OrderSide, Timeframe
from execution.executor import AsyncTradeExecutor, ReconciliationState
from execution.paper_contract import PaperContractEngine, PaperContractExecutionGateway
from execution.persistence import SQLiteIntentRecordStore
from execution.policy import ExecutionContext, ExecutionIntent
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService


def observation(*, opened_at: datetime, open_: float, high: float, low: float, close: float) -> ClosedMarketObservation:
    return ClosedMarketObservation(
        canonical_symbol="XAUUSD", source="paper_fixture", provider_symbol="XAUUSD",
        timeframe=Timeframe.M5, candle_opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=5), open=open_, high=high, low=low, close=close,
    )


async def run_cycle() -> int:
    engine = PaperContractEngine()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entry = observation(opened_at=start, open_=100, high=101, low=99, close=100)
    intent = ExecutionIntent(
        symbol="XAUUSD", side=OrderSide.BUY,
        quantity=ExecutionQuantity(value=1, unit=ExecutionQuantityUnit.SIMULATION_UNITS),
        authorized_risk_amount=1.0, expected_loss_at_stop=1.0,
        quantity_risk_verified=True, entry=100, stop_loss=99, take_profit=102,
        idempotency_key="bounded-cycle", risk_approved=True,
    )
    context = ExecutionContext(
        emergency_stop=False, daily_loss_percent=0, max_daily_loss_percent=3,
        daily_trade_count=0, max_daily_trades=1, open_positions=(), max_open_positions=1,
        used_idempotency_keys=frozenset(), execution_enabled=True, dry_run=False,
        broker="simulation", environment="paper", account_id="PAPER",
        approved_brokers=frozenset({"simulation"}), approved_environments=frozenset({"paper"}),
        approved_accounts=frozenset({"PAPER"}), approved_symbols=frozenset({"XAUUSD"}),
        daily_state_authoritative=True,
    )
    venue = PaperContractExecutionGateway(
        engine, entry, observed_at=entry.closed_at,
        authorized_risk_amount=Decimal("1"),
    )
    events = JQENotificationEvents(NotificationService())
    with TemporaryDirectory(prefix="jqe-paper-") as directory:
        records = SQLiteIntentRecordStore(Path(directory) / "intents.sqlite3")
        result = await AsyncTradeExecutor(venue, records).submit(intent, context)
        if result.state is not ReconciliationState.ALREADY_EXECUTED or result.order_id is None:
            await events.paper_event(
                kind="BLOCKED", facts={"Decision": result.decision.code.value, "Execution": "OFFLINE"}
            )
            print(f"PAPER_LIFECYCLE=BLOCKED")
            print(f"DECISION={result.decision.code.value}")
            print("BROKER_NETWORK=DISABLED")
            del records
            gc.collect()
            return 1
        position = engine._positions[result.order_id]
        await events.paper_event(
            kind="OPENED", facts={"Contract": position.contract_id, "Execution": "OFFLINE"}
        )
        exit_observation = observation(
            opened_at=start + timedelta(minutes=5), open_=100, high=102, low=100, close=102
        )
        engine.request_close(position.contract_id)
        closed = engine.observe(position.contract_id, exit_observation, force_close=True)
        reconciled = engine.reconcile(position.contract_id)
        if closed is None:
            del records
            gc.collect()
            return 1
        await events.paper_event(
            kind="CLOSED",
            facts={
                "Contract": position.contract_id,
                "Reason": closed.reason.value,
                "Realized P/L": str(closed.realized_profit),
                "Execution": "OFFLINE",
            },
        )
        print("PAPER_LIFECYCLE=CLOSED")
        print(f"CONTRACT_ID={position.contract_id}")
        print(f"ENTRY={position.entry}")
        print(f"STAKE={position.stake}")
        print(f"STOP_LOSS={position.stop_loss}")
        print(f"TAKE_PROFIT={position.take_profit}")
        print(f"EXIT_REASON={closed.reason.value}")
        print(f"EXIT_PRICE={closed.exit_price}")
        print(f"REALIZED_PL={closed.realized_profit}")
        print(f"RECONCILIATION={reconciled.state.value}")
        print("BROKER_NETWORK=DISABLED")
        del records
        gc.collect()
        return 0


def main() -> int:
    return asyncio.run(run_cycle())


if __name__ == "__main__":
    raise SystemExit(main())
