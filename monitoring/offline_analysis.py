"""Deterministic analysis-only cycle over closed synthetic candles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256

import pandas as pd

from broker.simulation_gateway import SimulationGateway
from broker.types import Candle, TIMEFRAME_SECONDS, Timeframe
from core.data_validator import validate_market_data
from core.exceptions import MarketDataError
from core.indicators import calculate_indicators
from core.regime import detect_regime
from data.dataset import canonical_dataset_hash
from execution.market_setup import (
    DataFreshnessDTO, HistoricalWinRateDTO, MarketLevelDTO, MarketSetup,
    SetupAuthorizationDTO, SetupEvidenceDTO, resolve_historical_win_rate,
)
from intelligence.analyst import explain_setup
from intelligence.trade_plan import TradePlan
from strategy.pipeline import generate_trading_signal


def _utc_floor(instant: datetime, seconds: int) -> datetime:
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise MarketDataError("Offline analysis observation time must be timezone-aware")
    utc = instant.astimezone(timezone.utc)
    return datetime.fromtimestamp(int(utc.timestamp()) // seconds * seconds, tz=timezone.utc)


def validate_closed_dataset(
    candles: list[Candle], *, timeframe: Timeframe, observed_at: datetime
) -> datetime:
    if not candles:
        raise MarketDataError("Offline analysis dataset is empty")
    seconds = TIMEFRAME_SECONDS[timeframe]
    observed = observed_at.astimezone(timezone.utc)
    previous: datetime | None = None
    for candle in candles:
        if candle.source.lower() != "simulation":
            raise MarketDataError("Offline analysis requires simulation-sourced candles")
        if candle.time.tzinfo is None or candle.time.utcoffset() is None:
            raise MarketDataError("Offline candle timestamps must be timezone-aware")
        opened = candle.time.astimezone(timezone.utc)
        if int(opened.timestamp()) % seconds:
            raise MarketDataError("Offline candle is not aligned to its timeframe")
        if previous is not None and opened - previous != timedelta(seconds=seconds):
            raise MarketDataError("Offline candle timestamps must be monotonic and contiguous")
        if opened + timedelta(seconds=seconds) > observed:
            raise MarketDataError("Incomplete/open candle cannot be analyzed")
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            raise MarketDataError("Offline candle has invalid OHLC relationships")
        previous = opened
    frame = pd.DataFrame([c.model_dump() for c in candles])
    if not validate_market_data(frame):
        raise MarketDataError("Offline dataset failed canonical integrity validation")
    latest_close = candles[-1].time.astimezone(timezone.utc) + timedelta(seconds=seconds)
    if observed - latest_close >= timedelta(seconds=seconds):
        raise MarketDataError("Stale offline data cannot be published as fresh")
    return latest_close


async def run_offline_analysis(
    *, symbol: str, timeframe: Timeframe, seed: int, count: int,
    observed_at: datetime | None = None,
) -> MarketSetup:
    """Generate, validate, evaluate, and return one analysis-only setup."""
    observed = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seconds = TIMEFRAME_SECONDS[timeframe]
    boundary = _utc_floor(observed, seconds)
    source = SimulationGateway(seed=seed)
    await source.connect()
    try:
        candles = await source.get_candles(symbol, timeframe, count, end=boundary)
    finally:
        await source.disconnect()
    latest_close = validate_closed_dataset(candles, timeframe=timeframe, observed_at=observed)
    dataset_hash = canonical_dataset_hash(candles, symbol=symbol, timeframe=timeframe)
    frame = calculate_indicators(pd.DataFrame([c.model_dump() for c in candles]))
    regime = detect_regime(frame)
    decision = generate_trading_signal(
        frame, symbol=symbol, regime=regime, include_details=True,
    )
    breakdown = decision.get("confidence_breakdown")
    if breakdown is None:
        raise MarketDataError("Canonical strategy did not complete its confidence assessment")
    plan: TradePlan | None = decision.get("trade_plan")
    direction = decision["signal"]
    reason_codes = ["NO_TRADE"] if direction == "NO_TRADE" else ["ANALYSIS_ONLY"]
    risk_status = "BLOCKED" if direction == "NO_TRADE" else "NOT_EVALUATED"
    risk_reason = "Strategy produced an authoritative no-trade result" if direction == "NO_TRADE" else "Analysis-only cycle does not authorize risk"
    maximums = {"trend": 25, "structure": 20, "liquidity": 20, "momentum": 15, "volatility": 10, "risk": 10}
    recent = frame.tail(20)
    levels = [
        MarketLevelDTO(kind="SUPPORT", price=Decimal(str(float(recent["low"].min())))),
        MarketLevelDTO(kind="RESISTANCE", price=Decimal(str(float(recent["high"].max())))),
    ]
    material = f"offline|{symbol.upper()}|{timeframe.value}|{seed}|{dataset_hash}"
    setup = MarketSetup(
        setup_id=sha256(material.encode()).hexdigest()[:24], symbol=symbol.upper(),
        timeframe=timeframe.value, observed_at=observed, candle_close_time=latest_close,
        expires_at=latest_close + timedelta(seconds=seconds * 2), direction=direction,
        setup_state="BLOCKED", entry_price=Decimal(str(plan.entry)) if plan and plan.entry is not None else None,
        stop_loss=Decimal(str(plan.stop_loss)) if plan and plan.stop_loss is not None else None,
        targets=[Decimal(str(plan.take_profit))] if plan and plan.take_profit is not None else [],
        levels=levels, analyzed_candle_time=candles[-1].time,
        risk_reward_ratio=Decimal(str(plan.risk_reward)) if plan and plan.risk_reward is not None else None,
        confidence_score=breakdown.total, confidence_method="JQE_DETERMINISTIC_6_FACTOR_V1",
        evidence=[SetupEvidenceDTO(factor=name, assessment=breakdown.factors.get(name, "UNKNOWN"), score=getattr(breakdown, f"{name}_score"), maximum_score=maximum) for name, maximum in maximums.items()],
        conflicts=list(dict.fromkeys([*decision.get("reasons", []), *(plan.warnings if plan else [])])),
        market_regime=str(decision.get("intelligence", {}).get("regime", regime)),
        invalidation_condition=plan.invalidation if plan else None,
        data_freshness=DataFreshnessDTO(
            status="CURRENT", source="SIMULATION", age_seconds=Decimal(str((observed-latest_close).total_seconds())),
            maximum_age_seconds=seconds, reason="Newest deterministic simulation candle is closed and current",
            latest_closed_candle_at=latest_close, expected_closed_candle_at=boundary,
            freshness_tolerance_seconds=seconds, freshness_age_seconds=Decimal(str((observed-latest_close).total_seconds())),
            freshness_state="FRESH", freshness_reason_codes=["LATEST_CLOSED_CANDLE_WITHIN_TOLERANCE"],
            reason_codes=["LATEST_CLOSED_CANDLE_WITHIN_TOLERANCE"],
        ),
        risk_authorization=SetupAuthorizationDTO(status=risk_status, reason=risk_reason, reason_codes=reason_codes),
        execution_authorization=SetupAuthorizationDTO(status="BLOCKED", reason="Analysis-only cycle cannot authorize submission", reason_codes=["ANALYSIS_ONLY"]),
        reason_codes=list(dict.fromkeys([*reason_codes, "ANALYSIS_ONLY"])),
        historical_win_rate=resolve_historical_win_rate(symbol, timeframe.value),
        dataset_source="SIMULATION", dataset_seed=seed, dataset_hash=dataset_hash,
        dataset_first_candle=candles[0].time, dataset_last_candle=candles[-1].time,
    )
    setup.explanation = explain_setup(setup)
    return setup
