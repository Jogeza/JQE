"""JQE FastAPI Route Definitions.

Exposes clean, typed REST endpoints for quantitative monitoring and observability.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dto import (
    CandlesResponse,
    ExecutionStateResponse,
    MarketSummaryResponse,
    PerformanceSummaryResponse,
    RiskStatusResponse,
    SignalResponse,
    SystemStatusResponse,
)
from api.service import ApplicationService
from core.exceptions import JQEError

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def get_service() -> ApplicationService:
    """Dependency provider for ApplicationService."""
    return ApplicationService()


@router.get("/market", response_model=MarketSummaryResponse)
@router.get("/market/summary", response_model=MarketSummaryResponse)
async def get_market_summary(
    symbol: str | None = None,
    timeframe: str | None = None,
    count: int | None = None,
    service: ApplicationService = Depends(get_service),
) -> MarketSummaryResponse:
    """Returns the latest market data and key indicators snapshot."""
    try:
        return await service.get_market_summary(symbol=symbol, timeframe_str=timeframe, count=count)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/market/candles", response_model=CandlesResponse)
async def get_market_candles(
    symbol: str | None = None,
    timeframe: str | None = None,
    count: int = 50,
    service: ApplicationService = Depends(get_service),
) -> CandlesResponse:
    """Returns recent historical candles with computed indicators for visual charts."""
    try:
        return await service.get_market_candles(symbol=symbol, timeframe_str=timeframe, count=count)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/signal", response_model=SignalResponse)
async def get_strategy_signal(
    symbol: str | None = None,
    timeframe: str | None = None,
    count: int | None = None,
    service: ApplicationService = Depends(get_service),
) -> SignalResponse:
    """Evaluates market state and returns strategy signal, 6-factor confidence, and trade plan."""
    try:
        return await service.get_strategy_signal(symbol=symbol, timeframe_str=timeframe, count=count)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/risk", response_model=RiskStatusResponse)
async def get_risk_status(
    symbol: str | None = None,
    timeframe: str | None = None,
    service: ApplicationService = Depends(get_service),
) -> RiskStatusResponse:
    """Returns account balance, equity, risk limits, and trade sizing evaluation."""
    try:
        return await service.get_risk_status(symbol=symbol, timeframe_str=timeframe)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/execution", response_model=ExecutionStateResponse)
async def get_execution_state(
    service: ApplicationService = Depends(get_service),
) -> ExecutionStateResponse:
    """Returns open positions and recent trade history from the broker."""
    try:
        return await service.get_execution_state()
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/performance", response_model=PerformanceSummaryResponse)
async def get_performance_summary(
    service: ApplicationService = Depends(get_service),
) -> PerformanceSummaryResponse:
    """Returns quantitative performance analytics derived from closed trades."""
    try:
        return await service.get_performance_summary()
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/system", response_model=SystemStatusResponse)
async def get_system_status(
    service: ApplicationService = Depends(get_service),
) -> SystemStatusResponse:
    """Returns system configuration, broker status, and server health."""
    try:
        return await service.get_system_status()
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
