"""Typed, broker-neutral contract for an analyzed paper-trading setup."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

import json
from pathlib import Path

from pydantic import BaseModel, Field


MarketDataProvenance = Literal["SIMULATION", "DERIV_PUBLIC", "UNAVAILABLE"]


class SetupEvidenceDTO(BaseModel):
    factor: str
    assessment: str
    score: int = Field(ge=0)
    maximum_score: int = Field(ge=0)


class DataFreshnessDTO(BaseModel):
    status: Literal["CURRENT", "CACHED", "STALE", "UNAVAILABLE"]
    source: MarketDataProvenance
    age_seconds: Decimal | None = None
    maximum_age_seconds: int
    reason: str
    latest_closed_candle_at: datetime | None = None
    expected_closed_candle_at: datetime | None = None
    freshness_tolerance_seconds: int | None = None
    freshness_age_seconds: Decimal | None = None
    freshness_state: Literal["FRESH", "STALE", "FORMING", "UNKNOWN"] = "UNKNOWN"
    freshness_reason_codes: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class SetupAuthorizationDTO(BaseModel):
    status: Literal["AUTHORIZED", "BLOCKED", "NOT_EVALUATED"]
    reason: str
    reason_codes: list[str] = Field(default_factory=list)
    authorized_risk_amount: Decimal | None = None
    authorized_risk_percent: Decimal | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    expected_loss_at_stop: Decimal | None = None


class HistoricalWinRateDTO(BaseModel):
    status: Literal["AVAILABLE", "UNAVAILABLE"] = "UNAVAILABLE"
    win_rate_percent: Decimal | None = None
    sample_size: int | None = None
    evaluation_start: datetime | None = None
    evaluation_end: datetime | None = None
    strategy_version: str | None = None
    dataset_hash: str | None = None
    compatibility_state: Literal["COMPATIBLE", "INCOMPATIBLE", "UNVERIFIED"] = "UNVERIFIED"
    reason: str = "No compatible out-of-sample evidence is linked to this setup"


def resolve_historical_win_rate(
    symbol: str,
    timeframe: str,
    experiment_dir: Path | str | None = None,
) -> HistoricalWinRateDTO:
    """Find a verified out-of-sample experiment strictly matching setup parameters."""
    from config.settings import settings
    path = Path(experiment_dir or settings.research_experiment_path).expanduser().resolve()
    if not path.is_dir():
        return HistoricalWinRateDTO(
            status="UNAVAILABLE",
            compatibility_state="UNVERIFIED",
            reason=f"No compatible out-of-sample evidence for {symbol} {timeframe}",
        )
    sym = symbol.strip().upper()
    tf = timeframe.strip().upper()
    for file_path in sorted(path.glob("*.json")):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("status") != "COMPLETED":
                continue
            if str(data.get("symbol", "")).upper() != sym:
                continue
            if str(data.get("timeframe", "")).upper() != tf:
                continue
            strategy = (
                data.get("strategy_name")
                or data.get("configuration", {}).get("strategy", {}).get("strategy_id")
            )
            if not strategy or not str(strategy).startswith("jqe-canonical"):
                continue
            metrics = data.get("metrics", {})
            win_rate = metrics.get("Win Rate %")
            trades = metrics.get("Actual Opened Trades") or metrics.get("total_trades")
            if win_rate is None or trades is None or trades <= 0:
                continue
            start_str = data.get("partition_first_candle")
            end_str = data.get("partition_last_candle")
            start = datetime.fromisoformat(start_str) if start_str else None
            end = datetime.fromisoformat(end_str) if end_str else None
            return HistoricalWinRateDTO(
                status="AVAILABLE",
                win_rate_percent=Decimal(str(round(float(win_rate), 2))),
                sample_size=int(trades),
                evaluation_start=start,
                evaluation_end=end,
                strategy_version=str(strategy),
                dataset_hash=data.get("dataset_hash"),
                compatibility_state="COMPATIBLE",
                reason=f"Compatible out-of-sample experiment {data.get('experiment_id')}",
            )
        except Exception:
            continue
    return HistoricalWinRateDTO(
        status="UNAVAILABLE",
        compatibility_state="UNVERIFIED",
        reason=f"No compatible out-of-sample evidence for {symbol} {timeframe}",
    )


class MarketLevelDTO(BaseModel):
    kind: Literal["SUPPORT", "RESISTANCE"]
    price: Decimal
    method: str = "RECENT_RANGE_20_V1"


class AnalystExplanation(BaseModel):
    state: str
    decision_summary: str | None = None
    supporting_evidence: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    freshness_warning: str | None = None
    invalidation_condition: str | None = None
    additional_evidence_required: list[str] = Field(default_factory=list)
    method: str = "JQE_BOUNDED_DETERMINISTIC_ANALYST_V1"


class MarketSetup(BaseModel):
    """Unified, auditable market-analysis and paper-execution contract."""

    setup_id: str
    symbol: str
    timeframe: str
    observed_at: datetime
    candle_close_time: datetime
    expires_at: datetime | None = None
    direction: Literal["BUY", "SELL", "NO_TRADE"]
    setup_state: Literal["FORMING", "READY", "BLOCKED", "EXPIRED", "EXECUTED"]
    entry_price: Decimal | None = None
    stop_loss: Decimal | None = None
    targets: list[Decimal] = Field(default_factory=list)
    levels: list[MarketLevelDTO] = Field(default_factory=list)
    analyzed_candle_time: datetime | None = None
    risk_reward_ratio: Decimal | None = None
    confidence_score: int = Field(ge=0, le=100)
    confidence_method: str
    evidence: list[SetupEvidenceDTO] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    market_regime: str
    invalidation_condition: str | None = None
    data_freshness: DataFreshnessDTO
    risk_authorization: SetupAuthorizationDTO
    execution_authorization: SetupAuthorizationDTO
    reason_codes: list[str] = Field(default_factory=list)
    historical_win_rate: HistoricalWinRateDTO = Field(default_factory=HistoricalWinRateDTO)
    dataset_source: str | None = None
    dataset_seed: int | None = None
    dataset_hash: str | None = None
    dataset_first_candle: datetime | None = None
    dataset_last_candle: datetime | None = None
    explanation: AnalystExplanation | None = None
    schema_version: int = 1


class PaperExecutionOutcomeDTO(BaseModel):
    outcome_id: str
    setup_id: str
    recorded_at: datetime
    status: Literal["OPENED", "BLOCKED", "ALREADY_RECORDED", "UNKNOWN"]
    setup_state: Literal["READY", "BLOCKED", "EXPIRED", "EXECUTED"]
    order_id: str | None = None
    execution_price: Decimal | None = None
    quantity: Decimal | None = None
    quantity_unit: str | None = None
    realized_pnl: Decimal | None = None
    close_reason: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    message: str
    paper_only: Literal[True] = True
