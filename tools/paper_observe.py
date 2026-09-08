"""Run a bounded, synthetic-only paper observation diagnostics session."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from config import settings
from execution.paper_runtime import ContinuousPaperRuntime, PaperRuntimeStateStore
from execution.persistence import SQLiteIntentRecordStore
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from research.paper_diagnostics import (
    STRATEGY_ID,
    PaperDiagnosticsStore,
    PaperObservationRecord,
    PaperObservationSession,
    configuration_hash,
    summarize,
)
from tools.paper_runtime import _offline_observations, evaluate_production_decision


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


async def observe(max_cycles: int) -> dict:
    if max_cycles <= 0:
        raise ValueError("max cycles must be positive")
    if settings.broker != "simulation":
        raise RuntimeError("paper observation forbids broker execution configuration")
    all_observations = _offline_observations(500 + max_cycles)
    warmup = min(500, len(all_observations))
    if warmup + max_cycles > len(all_observations):
        raise ValueError("bounded fixture does not contain enough closed observations")
    cursor = warmup
    last_facts: dict[str, object] = {}

    async def source():
        nonlocal cursor
        window = all_observations[:cursor]
        cursor += 1
        return window

    async def decide(observations):
        nonlocal last_facts
        decision, last_facts = await evaluate_production_decision(observations)
        return decision

    context = {
        "symbol": settings.default_symbol, "timeframe": "M5",
        "runtime_mode": "paper_continuous", "risk_percent": settings.risk_percent,
        "minimum_confidence": settings.min_confidence_threshold,
        "source_mode": "SYNTHETIC_OBSERVATION",
    }
    started = datetime.now(timezone.utc)
    session = PaperObservationSession(
        session_id=uuid4().hex, started_at=started, ended_at=None,
        git_commit=_git_commit(), strategy_id=STRATEGY_ID,
        configuration_hash=configuration_hash(context), runtime_mode="paper_continuous",
        source_mode="SYNTHETIC_OBSERVATION", symbols=(settings.default_symbol,),
        timeframes=("M5",), dataset_identity=configuration_hash({
            "source": "paper_runtime_fixture", "first": all_observations[0].closed_at,
            "last": all_observations[-1].closed_at, "count": len(all_observations),
        }),
    )
    diagnostics = PaperDiagnosticsStore(settings.paper_diagnostics_path)
    diagnostics.start(session)
    runtime = ContinuousPaperRuntime(
        observation_source=source, decision_builder=decide,
        intent_records=SQLiteIntentRecordStore(settings.intent_store_path),
        state_store=PaperRuntimeStateStore(settings.paper_runtime_state_path),
        symbols=(settings.default_symbol,), enabled=settings.paper_runtime_enabled,
        runtime_mode=settings.runtime_mode, poll_seconds=settings.paper_runtime_poll_seconds,
        max_backoff_seconds=settings.paper_runtime_max_backoff_seconds,
        notifications=JQENotificationEvents(NotificationService()),
    )
    cumulative = Decimal("0")
    starting_equity = Decimal(str(settings.account_balance))
    equity_peak = starting_equity
    seen_closes: set[str] = set()
    for cycle in range(1, max_cycles + 1):
        began = datetime.now(timezone.utc)
        heartbeat = await runtime.run_once()
        observation = all_observations[warmup + cycle - 2]
        new_closes = [item for item in runtime.engine.closes if item.close_id not in seen_closes]
        for item in new_closes:
            seen_closes.add(item.close_id)
            cumulative += item.realized_profit
        closed = new_closes[-1] if new_closes else None
        realized_r = None
        if closed is not None:
            maximum_loss = runtime.engine.maximum_loss_for(closed.contract_id)
            realized_r = closed.realized_profit / maximum_loss if maximum_loss else None
        equity = starting_equity + cumulative
        equity_peak = max(equity_peak, equity)
        drawdown = equity_peak - equity
        raw_direction = str(last_facts.get("signal_direction", "NO_TRADE"))
        direction = raw_direction if raw_direction in {"BUY", "SELL"} else "NO_SIGNAL"
        block = heartbeat.last_action.split(":", 1)[1] if heartbeat.last_action.startswith("BLOCKED:") else None
        diagnostics.append(PaperObservationRecord(
            session_id=session.session_id, observed_at=began,
            symbol=observation.canonical_symbol, timeframe=observation.timeframe.value,
            candle_close_time=observation.closed_at, source_mode=session.source_mode,
            dataset_identity=session.dataset_identity, cycle_number=cycle,
            regime=str(last_facts.get("regime")) if last_facts.get("regime") is not None else None,
            signal_direction=direction,
            signal_confidence=(Decimal(str(last_facts["signal_confidence"])) if last_facts.get("signal_confidence") is not None else None),
            confirmation_state=str(last_facts.get("confirmation_state", "NOT_EVALUATED")),
            execution_decision=("ALLOWED" if heartbeat.last_action == "POSITION_OPENED" else "BLOCKED" if block else "NOT_EVALUATED"),
            block_reason=block or (str(last_facts.get("block_reason")) if last_facts.get("block_reason") else "NO_SIGNAL" if direction == "NO_SIGNAL" else None),
            risk_authorization_state=str(last_facts.get("risk_authorization_state", "NOT_EVALUATED")),
            authorized_quantity=(Decimal(str(last_facts["authorized_quantity"])) if last_facts.get("authorized_quantity") is not None else None),
            paper_position_state=("OPEN" if heartbeat.open_paper_positions else "CLOSED" if closed else None),
            entry_event="OPENED" if heartbeat.last_action == "POSITION_OPENED" else None,
            exit_event="CLOSED" if closed else None,
            exit_reason=closed.reason.value if closed else None,
            realized_pnl=closed.realized_profit if closed else None,
            realized_r=realized_r,
            fees=closed.fees if closed else None,
            slippage=runtime.engine.specification.slippage if closed else None,
            cumulative_pnl=cumulative, equity=equity, drawdown=drawdown,
            processing_duration_ms=Decimal(str(
                (datetime.now(timezone.utc) - began).total_seconds() * 1000
            )),
            strategy_duration_ms=(Decimal(str(last_facts["strategy_duration_ms"])) if last_facts.get("strategy_duration_ms") is not None else None),
            risk_duration_ms=(Decimal(str(last_facts["risk_duration_ms"])) if last_facts.get("risk_duration_ms") is not None else None),
            market_data_freshness_seconds=Decimal(str(
                max(0.0, (began - observation.closed_at).total_seconds())
            )),
            reconciliation_state="CLOSED" if closed else "NOT_EVALUATED",
        ))
    finished = replace(
        session, ended_at=datetime.now(timezone.utc), status="COMPLETED",
        termination_reason="MAX_CYCLES_REACHED",
    )
    diagnostics.finish(finished)
    metrics = summarize(diagnostics.records(session.session_id), minimum_sample=settings.paper_diagnostics_minimum_sample)
    await JQENotificationEvents(NotificationService()).paper_summary(facts={
        "Observations": str(metrics["observations"]), "Signals": str(metrics["signals"]),
        "Confirmed": str(metrics["confirmations"]), "Trades": str(metrics["closed_positions"]),
        "Net R": str(metrics["average_r"] or "UNAVAILABLE"), "Drawdown R": str(metrics["max_drawdown"]),
    })
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-cycles", type=int, default=10)
    args = parser.parse_args()
    metrics = asyncio.run(observe(args.max_cycles))
    for key in ("observations", "signals", "confirmations", "authorized_entries", "opened_positions", "closed_positions", "net_pnl", "average_r", "max_drawdown"):
        print(f"{key.upper()}={metrics[key]}")
    print(f"BLOCK_REASONS={json.dumps(metrics['block_reasons'], sort_keys=True)}")
    print(f"EXIT_DISTRIBUTION={json.dumps(metrics['exit_distribution'], sort_keys=True)}")
    print(f"REGIME_DISTRIBUTION={json.dumps(metrics['by_regime'], sort_keys=True)}")
    print("BROKER_EXECUTION=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
