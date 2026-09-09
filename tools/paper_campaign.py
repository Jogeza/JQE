"""Run a resumable, local-only bounded paper observation campaign."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import os
import subprocess
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from broker.types import ClosedMarketObservation, TIMEFRAME_SECONDS, Timeframe
from config import settings
from core.logger import logger as jqe_logger
from data.storage import CandleStore, find_gaps
from execution.paper_runtime import ContinuousPaperRuntime, PaperRuntimeStateStore
from execution.paper_contract import PaperContractEngine, PaperContractSpecification
from execution.persistence import SQLiteIntentRecordStore
from notifications.events import JQENotificationEvents
from notifications.service import NotificationService
from research.paper_diagnostics import (
    STRATEGY_ID, PaperDiagnosticsStore, PaperObservationRecord,
    PaperObservationSession, configuration_hash, summarize,
)
from research.historical_safety import (
    ExecutionContextKind, HistoricalResearchSafetyContext,
    require_historical_research_context,
)
from research.historical_confirmation import HistoricalConfirmationState
from research.campaign_provenance import (
    CampaignEvidence, CampaignEvidenceStore, build_fingerprint, sha256_file,
)
from tools.paper_runtime import evaluate_production_decision, evaluate_strategy_candidate


DEFAULT_OUTPUT = Path("state/paper_campaigns/latest.json")


def _candidate_id(symbol: str, timeframe: str, signal_candle: datetime, direction: str) -> str:
    value = f"{symbol.upper()}|{timeframe}|{signal_candle.astimezone(timezone.utc).isoformat()}|{direction}"
    return "CANDIDATE-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _effective_config(*, symbol: str, timeframe: Timeframe, max_observations: int, safety: HistoricalResearchSafetyContext) -> dict[str, object]:
    """Secret-free effective inputs used by the campaign."""
    specification = PaperContractSpecification(
        minimum_stake=Decimal("0.000000000001"), stake_increment=Decimal("0.000000000001")
    )
    return {
        "symbol": symbol.upper(), "timeframe": timeframe.value,
        "max_observations": max_observations, "warmup_candles": 500,
        "history_window_candles": 500, "account_balance": settings.account_balance,
        "risk_percent": settings.risk_percent, "max_daily_loss": settings.max_daily_loss,
        "max_daily_trades": settings.max_trades_daily,
        "min_confidence_threshold": settings.min_confidence_threshold,
        "max_open_positions": safety.max_open_positions,
        "paper_minimum_stake": str(specification.minimum_stake),
        "paper_maximum_stake": str(specification.maximum_stake),
        "paper_stake_increment": str(specification.stake_increment),
        "paper_fee_rate": str(specification.fee_rate),
        "paper_slippage": str(specification.slippage),
        "trade_plan_atr_sl_multiplier": "2.0", "trade_plan_target_rr": "2.0",
        "paper_diagnostics_minimum_sample": settings.paper_diagnostics_minimum_sample,
        "runtime_mode": "paper_continuous", "broker": "simulation",
        "broker_execution_enabled": False,
    }


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _campaign_observations(symbol: str, timeframe: Timeframe, count: int) -> tuple[list[ClosedMarketObservation], str, list[tuple[datetime, datetime]]]:
    store = CandleStore(read_only=True)
    candles = store.load_candles(symbol, timeframe, provider="deriv")
    warmup = 500
    if len(candles) < warmup + count:
        raise ValueError(f"local CandleStore has {len(candles)} candles; {warmup + count} required")
    provenance = store.load_provenance("deriv", symbol, timeframe)
    if provenance is None:
        raise ValueError("local dataset provenance is unavailable")
    selected = candles[:warmup + count]
    gaps = find_gaps(selected, TIMEFRAME_SECONDS[timeframe])
    observations = [ClosedMarketObservation(
        canonical_symbol=symbol, source="deriv_candlestore", provider_symbol=provenance.provider_symbol,
        timeframe=timeframe, candle_opened_at=item.time,
        closed_at=item.time + timedelta(seconds=TIMEFRAME_SECONDS[timeframe]),
        open=item.open, high=item.high, low=item.low, close=item.close, volume=item.volume,
    ) for item in selected]
    identity = f"sha256:{__import__('hashlib').sha256(''.join(item.model_dump_json() for item in selected).encode()).hexdigest()}"
    return observations, identity, gaps


def _record(session_id: str, cycle: int, observation: ClosedMarketObservation, heartbeat: Any, facts: dict[str, object], began: datetime, runtime: Any) -> PaperObservationRecord:
    closed = runtime.engine.closes[-1] if (
        runtime.engine.closes and runtime.engine.closes[-1].closed_at == observation.closed_at
    ) else None
    raw_direction = str(facts.get("strategy_signal_direction", facts.get("signal_direction", "NO_TRADE")))
    direction = raw_direction if raw_direction in {"BUY", "SELL"} else "NO_SIGNAL"
    block = heartbeat.last_action.split(":", 1)[1] if heartbeat.last_action.startswith("BLOCKED:") else None
    realized_r = None
    if closed is not None:
        maximum_loss = runtime.engine.maximum_loss_for(closed.contract_id)
        realized_r = closed.realized_profit / maximum_loss if maximum_loss else None
    return PaperObservationRecord(
        session_id=session_id, observed_at=began, symbol=observation.canonical_symbol,
        timeframe=observation.timeframe.value, candle_close_time=observation.closed_at,
        source_mode="DERIV_CANDLESTORE_READ_ONLY", dataset_identity=None, cycle_number=cycle,
        regime=str(facts.get("regime")) if facts.get("regime") is not None else None,
        signal_direction=direction,
        signal_confidence=Decimal(str(facts["signal_confidence"])) if facts.get("signal_confidence") is not None else None,
        confirmation_state=str(facts.get("confirmation_state", "NOT_EVALUATED")),
        confirmation_reason=str(facts["confirmation_reason"]) if facts.get("confirmation_reason") else None,
        momentum=str(facts["momentum"]) if facts.get("momentum") else None,
        volatility=str(facts["volatility"]) if facts.get("volatility") else None,
        safety_context="HISTORICAL_RESEARCH",
        execution_decision="ALLOWED" if heartbeat.last_action == "POSITION_OPENED" else "BLOCKED" if block else "NOT_EVALUATED",
        block_reason=block or (str(facts.get("block_reason")) if facts.get("block_reason") else "NO_SIGNAL" if direction == "NO_SIGNAL" else None),
        risk_authorization_state=str(facts.get("risk_authorization_state", "NOT_EVALUATED")),
        authorized_quantity=Decimal(str(facts["authorized_quantity"])) if facts.get("authorized_quantity") is not None else None,
        paper_position_state="OPEN" if heartbeat.open_paper_positions else "CLOSED" if closed else None,
        entry_event="OPENED" if heartbeat.last_action == "POSITION_OPENED" else None,
        exit_event="CLOSED" if closed else None, exit_reason=closed.reason.value if closed else None,
        realized_pnl=closed.realized_profit if closed else None,
        realized_r=realized_r,
        cumulative_pnl=None, equity=None, drawdown=None,
        processing_duration_ms=Decimal(str((datetime.now(timezone.utc) - began).total_seconds() * 1000)),
        strategy_duration_ms=Decimal(str(facts["strategy_duration_ms"])) if facts.get("strategy_duration_ms") is not None else None,
        risk_duration_ms=Decimal(str(facts["risk_duration_ms"])) if facts.get("risk_duration_ms") is not None else None,
        market_data_freshness_seconds=Decimal(str(max(0.0, (began - observation.closed_at).total_seconds()))),
        reconciliation_state="CLOSED" if closed else "NOT_EVALUATED",
    )


async def run_campaign(*, symbol: str, timeframe: Timeframe, max_observations: int, output: Path, safety_context: HistoricalResearchSafetyContext | None, diagnostics_path: Path | None = None, evidence_path: Path | None = None, session_id: str | None = None, resume: bool = False, quiet: bool = False) -> dict[str, Any]:
    if max_observations <= 0:
        raise ValueError("max-observations must be positive")
    research_safety = require_historical_research_context(safety_context)
    if research_safety.symbol.strip().upper() != symbol.strip().upper():
        raise ValueError("historical research safety symbol does not match campaign")
    observations, dataset_identity, gaps = _campaign_observations(symbol, timeframe, max_observations)
    warmup = 500
    output = output.expanduser().resolve()
    diagnostics_path = (diagnostics_path or output.with_suffix(".sqlite3")).expanduser().resolve()
    evidence_path = (evidence_path or output.with_suffix(".evidence.sqlite3")).expanduser().resolve()
    pending_output = output.with_suffix(".pending.json")
    pending_confirmation_path = output.with_name(f"{output.stem}.{session_id or 'new'}.confirmation.json")
    diagnostics = PaperDiagnosticsStore(diagnostics_path)
    existing = diagnostics.session(session_id) if session_id else None
    if resume and existing is None:
        raise ValueError("--resume requires an existing --session-id")
    if existing and existing.status == "COMPLETED":
        raise ValueError("campaign session is already complete")
    session_id = session_id or uuid4().hex
    fingerprint = build_fingerprint(
        root=Path(__file__).resolve().parents[1], git_commit=_git_commit(), strategy_id=STRATEGY_ID,
        effective_config=_effective_config(symbol=symbol, timeframe=timeframe, max_observations=max_observations, safety=research_safety),
        dataset_identity=dataset_identity, symbol=symbol, timeframe=timeframe.value,
        first_candle=observations[warmup].closed_at.isoformat(), last_candle=observations[-1].closed_at.isoformat(),
        requested_observations=max_observations, safety_context={"kind": research_safety.kind.value, **research_safety.assumptions},
    )
    evidence = CampaignEvidenceStore(evidence_path)
    evidence.start(session_id, fingerprint)
    pending_confirmation_path = output.with_name(f"{output.stem}.{session_id}.confirmation.json")
    records = diagnostics.records(session_id) if existing else ()
    processed_times = {item.candle_close_time for item in records}
    session = existing or PaperObservationSession(
        session_id=session_id, started_at=datetime.now(timezone.utc), ended_at=None,
        git_commit=_git_commit(), strategy_id=STRATEGY_ID,
        configuration_hash=configuration_hash({"symbol": symbol, "timeframe": timeframe.value, "max_observations": max_observations}),
        runtime_mode="paper_continuous", source_mode="DERIV_CANDLESTORE_READ_ONLY",
        symbols=(symbol,), timeframes=(timeframe.value,), dataset_identity=dataset_identity,
    )
    diagnostics.start(session)
    if not quiet:
        print(f"JQE PAPER CAMPAIGN\nDataset: {symbol} {timeframe.value}")
    old_enabled, old_mode = settings.paper_runtime_enabled, settings.runtime_mode
    settings.paper_runtime_enabled, settings.runtime_mode = True, "paper_continuous"
    try:
        cursor = warmup + len(records)
        async def source() -> list[ClosedMarketObservation]:
            return observations[max(0, cursor - warmup):cursor]
        confirmation = HistoricalConfirmationState.load(pending_confirmation_path) if resume else HistoricalConfirmationState()
        if not resume:
            confirmation.save(pending_confirmation_path)
        facts: dict[str, object] = {}
        position_origins: dict[str, dict[str, object]] = {}
        event_sequence = len(evidence.events(session_id))
        def emit(event_type: str, occurred_at: datetime, event_facts: dict[str, object], candidate_id: str | None = None) -> None:
            nonlocal event_sequence
            event_sequence += 1
            evidence.append(session_id, CampaignEvidence(
                event_id=f"{event_sequence:08d}:{event_type}", event_type=event_type,
                candidate_id=candidate_id, occurred_at=occurred_at.isoformat(), facts=event_facts,
            ))
        async def decide(window: list[ClosedMarketObservation]):
            nonlocal facts
            signal, facts = await evaluate_strategy_candidate(window)
            facts["strategy_signal_direction"] = facts["signal_direction"]
            latest = window[-1]
            pending_before = confirmation.pending
            transition = confirmation.observe(latest.candle_opened_at, str(facts["regime"]))
            current_direction = str(signal.get("signal", "NO_TRADE"))
            current_candidate_id = _candidate_id(symbol, timeframe.value, latest.candle_opened_at, current_direction) if current_direction in {"BUY", "SELL"} else None
            if current_candidate_id is not None:
                status = "CONFIRMATION_PENDING" if pending_before is None else "OVERLAP_PENDING_CANDIDATE"
                emit("CANDIDATE", latest.candle_opened_at, {
                    "symbol": symbol, "timeframe": timeframe.value, "signal_candle": latest.candle_opened_at.isoformat(),
                    "direction": current_direction, "regime": facts.get("regime"), "confidence": facts.get("signal_confidence"),
                    "momentum": facts.get("momentum"), "volatility": facts.get("volatility"), "rsi": facts.get("rsi"),
                    "candidate_status": status,
                }, current_candidate_id)
            if transition.candidate is not None and transition.state not in {"NO_PENDING_CANDIDATE", "PENDING_CONFIRMATION"}:
                prior = transition.candidate
                prior_id = _candidate_id(symbol, timeframe.value, prior.signal_candle, prior.direction)
                emit("CONFIRMATION" if transition.state in {"CONFIRMED", "CONFIRMATION_FAILED"} else "CANDIDATE_DISPOSITION", latest.candle_opened_at, {
                    "signal_timestamp": prior.signal_candle.isoformat(), "confirmation_timestamp": latest.candle_opened_at.isoformat(),
                    "direction": prior.direction, "signal_regime": prior.strategy_context.get("regime"),
                    "confirmation_regime": facts.get("regime"), "result": transition.state, "reason_code": transition.reason,
                    "confirmation_features": {"regime": facts.get("regime")},
                }, prior_id)
            if transition.state == "ENTRY_DUE" and transition.candidate is not None:
                candidate = transition.candidate
                candidate_id = _candidate_id(symbol, timeframe.value, candidate.signal_candle, candidate.direction)
                original_signal = dict(candidate.strategy_context["signal"])
                decision, authorized_facts = await evaluate_production_decision(
                    window, execution_context=research_safety.execution_context(),
                    signal_override=original_signal, entry_price=float(latest.open),
                )
                facts = {
                    **authorized_facts,
                    "strategy_signal_direction": facts["strategy_signal_direction"],
                    "confirmation_state": "CONFIRMED_ENTRY_DUE",
                    "confirmation_reason": candidate.confirmation_reason,
                    "signal_candle": candidate.signal_candle.isoformat(),
                    "entry_candle": latest.candle_opened_at.isoformat(),
                    "candidate_id": candidate_id,
                    "original_regime": candidate.strategy_context.get("regime"),
                    "original_momentum": dict(original_signal.get("intelligence", {})).get("momentum"),
                    "original_volatility": dict(original_signal.get("intelligence", {})).get("volatility"),
                }
                if decision is not None:
                    facts.update(
                        authorized_risk_amount=str(decision.intent.authorized_risk_amount),
                        stop_loss=str(decision.intent.stop_loss), take_profit=str(decision.intent.take_profit),
                        stop_distance=str(abs(Decimal(str(decision.intent.entry)) - Decimal(str(decision.intent.stop_loss)))),
                    )
                emit("ENTRY", latest.candle_opened_at, {
                    "expected_entry_timestamp": candidate.expected_entry_candle.isoformat(),
                    "actual_entry_timestamp": latest.candle_opened_at.isoformat(), "entry_available": True,
                    "entry_price": str(latest.open),
                }, candidate_id)
                emit("RISK", latest.candle_opened_at, {
                    "result": facts.get("risk_authorization_state"), "reason_code": facts.get("block_reason"),
                    "input_confidence": original_signal.get("confidence"), "account_balance": settings.account_balance,
                    "risk_percent": settings.risk_percent, "authorized_quantity": facts.get("authorized_quantity"),
                    "quantity_unit": "SIMULATION_UNITS" if facts.get("authorized_quantity") is not None else None,
                    "authorized_risk_amount": facts.get("authorized_risk_amount"),
                    "stop_distance": facts.get("stop_distance"),
                    "risk_policy_source_hash": fingerprint.source_hashes["risk"],
                }, candidate_id)
                confirmation.save(pending_confirmation_path)
                return decision
            if transition.state in {"CONFIRMED", "CONFIRMATION_FAILED", "INCOMPLETE_CONFIRMATION", "INCOMPLETE_ENTRY", "DUPLICATE_CONFIRMATION_PREVENTED"}:
                facts["confirmation_state"] = transition.state
                facts["confirmation_reason"] = transition.reason
                facts["block_reason"] = transition.reason if "FAILED" in transition.state or "INCOMPLETE" in transition.state else None
                confirmation.save(pending_confirmation_path)
                return None
            direction = str(signal.get("signal", "NO_TRADE"))
            if confirmation.pending is None and direction in {"BUY", "SELL"}:
                queued = confirmation.queue(
                    symbol=symbol, timeframe=timeframe.value,
                    signal_candle=latest.candle_opened_at, direction=direction,
                    confidence=int(signal.get("confidence", 0)),
                    strategy_context={"signal": signal, "regime": facts["regime"]},
                    candle_interval=timedelta(seconds=TIMEFRAME_SECONDS[timeframe]),
                )
                facts["confirmation_state"] = "PENDING_CONFIRMATION"
                facts["confirmation_reason"] = queued.reason
            elif confirmation.pending is not None:
                facts["block_reason"] = "ENTRY_ALREADY_PENDING"
            confirmation.save(pending_confirmation_path)
            return None
        runtime = ContinuousPaperRuntime(
            observation_source=source, decision_builder=decide,
            intent_records=SQLiteIntentRecordStore(output.with_name(f"{output.stem}.{session.session_id}.intents.sqlite3")),
            state_store=PaperRuntimeStateStore(output.with_name(f"{output.stem}.{session.session_id}.runtime.sqlite3")),
            symbols=(symbol,), enabled=True, runtime_mode="paper_continuous", poll_seconds=1, max_backoff_seconds=2,
            notifications=JQENotificationEvents(NotificationService()),
            engine=PaperContractEngine(PaperContractSpecification(
                minimum_stake=Decimal("0.000000000001"),
                stake_increment=Decimal("0.000000000001"),
            )),
        )
        prior_logging_disable = logging.root.manager.disable
        if quiet:
            logging.disable(logging.CRITICAL)
            jqe_logger.disable("core.data_validator")
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                for index in range(cursor, len(observations)):
                    cursor = index + 1
                    observation = observations[index]
                    if observation.closed_at in processed_times:
                        continue
                    began = datetime.now(timezone.utc)
                    heartbeat = await runtime.run_once()
                    item = _record(session.session_id, cursor, observation, heartbeat, facts, began, runtime)
                    item = replace(item, dataset_identity=dataset_identity)
                    diagnostics.append(item)
                    if facts.get("candidate_id") and heartbeat.last_action.startswith("BLOCKED:"):
                        open_positions = [p for p in runtime.engine.positions if p.state.value != "CLOSED"]
                        emit("POLICY", observation.candle_opened_at, {
                            "result": "BLOCKED", "reason_code": heartbeat.last_action.split(":", 1)[1],
                            "open_position_ids": [p.contract_id for p in open_positions],
                            "open_position_count": len(open_positions), "max_open_positions": research_safety.max_open_positions,
                        }, str(facts["candidate_id"]))
                    elif facts.get("candidate_id") and heartbeat.last_action == "POSITION_OPENED":
                        position = next(p for p in reversed(runtime.engine.positions) if p.state.value != "CLOSED")
                        origin = {
                            "candidate_id": str(facts["candidate_id"]), "contract_id": position.contract_id,
                            "entry_timestamp": position.opened_at.isoformat(), "entry_price": str(position.entry),
                            "direction": position.side.value, "original_regime": facts.get("original_regime"),
                            "original_confidence": facts.get("signal_confidence"), "original_momentum": facts.get("original_momentum"),
                            "original_volatility": facts.get("original_volatility"), "authorized_quantity": str(position.stake),
                            "authorized_risk": facts.get("authorized_risk_amount"),
                            "stop": str(position.stop_loss), "target": str(position.take_profit),
                        }
                        position_origins[position.contract_id] = origin
                        emit("POLICY", observation.candle_opened_at, {"result": "ADMITTED", "reason_code": "ALLOWED", "open_position_ids": []}, str(facts["candidate_id"]))
                        emit("POSITION_OPENED", observation.candle_opened_at, origin, str(facts["candidate_id"]))
                    closed_event = runtime.engine.closes[-1] if (
                        runtime.engine.closes and runtime.engine.closes[-1].closed_at == observation.closed_at
                    ) else None
                    if item.exit_event == "CLOSED" and closed_event is not None:
                        closed = closed_event
                        origin = position_origins.get(closed.contract_id, {})
                        opened_at = next(p.opened_at for p in runtime.engine.positions if p.contract_id == closed.contract_id)
                        seconds = int((closed.closed_at - opened_at).total_seconds())
                        emit("POSITION_CLOSED", closed.closed_at, {
                            **origin, "exit_timestamp": closed.closed_at.isoformat(), "exit_price": str(closed.exit_price),
                            "exit_reason": closed.reason.value, "realized_pnl": str(closed.realized_profit),
                            "realized_r": str(item.realized_r), "holding_duration_seconds": seconds,
                            "holding_candles": seconds // TIMEFRAME_SECONDS[timeframe], "reconciliation_state": item.reconciliation_state,
                        }, str(origin.get("candidate_id")) if origin else None)
                    processed = cursor - warmup
                    if not quiet and processed % 1000 == 0:
                        print(f"Progress: {processed}/{max_observations}")
        finally:
            logging.disable(prior_logging_disable)
            if quiet:
                jqe_logger.enable("core.data_validator")
        boundary = confirmation.finish()
        if boundary is not None and boundary.candidate is not None:
            boundary_candidate = boundary.candidate
            emit("CANDIDATE_DISPOSITION", observations[-1].candle_opened_at, {
                "result": boundary.state, "reason_code": boundary.reason,
                "expected_confirmation_timestamp": boundary_candidate.expected_confirmation_candle.isoformat(),
                "expected_entry_timestamp": boundary_candidate.expected_entry_candle.isoformat(),
            }, _candidate_id(symbol, timeframe.value, boundary_candidate.signal_candle, boundary_candidate.direction))
        confirmation.save(pending_confirmation_path)
        records = diagnostics.records(session.session_id)
        metrics = summarize(records, minimum_sample=settings.paper_diagnostics_minimum_sample)
        metrics["sample_sufficiency"].update({
            "buy_sample_sufficient": metrics["directions"].get("BUY", 0) >= 3,
            "sell_sample_sufficient": metrics["directions"].get("SELL", 0) >= 3,
        })
        metrics["confirmation_analysis"] = {
            direction: {
                "observations": group["observations"],
                "signals": group["signals"],
                "confirmations": sum(
                    item.signal_direction == direction and item.confirmation_state == "CONFIRMED"
                    for item in records
                ),
                "block_reasons": group["block_reasons"],
            }
            for direction, group in metrics["by_direction"].items()
            if direction in {"BUY", "SELL"}
        }
        evidence.finalize(session_id)
        summary = {"schema_version": 2, "provenance_status": "PROVENANCE_COMPLETE",
        "research_fingerprint": fingerprint.payload(), "evidence": {
            "path": evidence_path.name, "sha256": sha256_file(evidence_path), "event_count": len(evidence.events(session_id)),
        }, "safety_context": research_safety.kind.value,
        "research_safety_assumptions": research_safety.assumptions, "session": {
            "session_id": session.session_id, "git_commit": session.git_commit,
            "strategy_id": session.strategy_id, "configuration_hash": session.configuration_hash,
            "symbol": symbol, "timeframe": timeframe.value, "dataset_identity": dataset_identity,
            "first_candle": observations[warmup].closed_at.isoformat(), "last_candle": observations[-1].closed_at.isoformat(),
            "requested_observations": max_observations, "processed_observations": len(records),
            "gaps_encountered": len(gaps), "gaps_skipped": 0, "status": "COMPLETED",
            "termination_reason": "TARGET_REACHED", "created_at": session.started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }, "metrics": metrics, "boundary_state": boundary.state if boundary else None,
        "boundary_reason": boundary.reason if boundary else None}
        _atomic_json(pending_output, summary)
        diagnostics.finish(replace(session, ended_at=datetime.now(timezone.utc), status="COMPLETED", termination_reason="TARGET_REACHED"))
        os.replace(pending_output, output)
        return summary
    except BaseException as exc:
        pending_output.unlink(missing_ok=True)
        diagnostics.finish(replace(session, ended_at=datetime.now(timezone.utc), status="FAILED", termination_reason=type(exc).__name__))
        raise
    finally:
        settings.paper_runtime_enabled, settings.runtime_mode = old_enabled, old_mode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", type=Timeframe, default=Timeframe.M15)
    parser.add_argument("--max-observations", type=int, default=5000)
    parser.add_argument("--source", choices=("candle_store",), default="candle_store")
    parser.add_argument("--session-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--diagnostics-path", type=Path)
    parser.add_argument("--evidence-path", type=Path)
    args = parser.parse_args()
    safety_context = HistoricalResearchSafetyContext(
        kind=ExecutionContextKind.HISTORICAL_RESEARCH, symbol=args.symbol,
        max_daily_loss_percent=settings.max_daily_loss,
        max_daily_trades=settings.max_trades_daily, max_open_positions=1,
    )
    summary = asyncio.run(run_campaign(symbol=args.symbol, timeframe=args.timeframe, max_observations=args.max_observations, output=args.output, safety_context=safety_context, diagnostics_path=args.diagnostics_path, evidence_path=args.evidence_path, session_id=args.session_id, resume=args.resume, quiet=args.quiet))
    print(json.dumps({"status": summary["session"]["status"], "session_id": summary["session"]["session_id"], "summary": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
