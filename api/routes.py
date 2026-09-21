"""JQE FastAPI Route Definitions.

Exposes clean, typed REST endpoints for quantitative monitoring and observability.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dto import (
    CandlesResponse,
    ExecutionStateResponse,
    ExecutionSafetyResponse,
    RecoveryDiagnosticsResponse,
    MarketSummaryResponse,
    PerformanceSummaryResponse,
    RiskStatusResponse,
    SignalResponse,
    SystemStatusResponse,
    PaperRuntimeStatusResponse,
    MarketSetup,
    PaperExecutionOutcomeDTO,
    ActiveMarketAnalysisResponse,
    OfflineMonitoringResponse,
    BrokerStatusResponse,
    SelectBrokerRequest,
    SelectBrokerResponse,
    WatchlistCapUsageResponse,
)
from api.service import (
    ApplicationService,
    BrokerSwitchConflictError,
    BrokerUnavailableError,
)
from core.exceptions import JQEError

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


def get_service() -> ApplicationService:
    """Dependency provider for ApplicationService."""
    return ApplicationService()


@router.get("/monitoring/offline", response_model=OfflineMonitoringResponse)
def get_offline_monitoring(
    service: ApplicationService = Depends(get_service),
) -> OfflineMonitoringResponse:
    """Return persisted offline-simulation gates without selecting a broker."""
    return service.get_offline_monitoring()


@router.post("/monitoring/offline/analyze", response_model=MarketSetup)
async def run_offline_analysis(
    symbol: str = "R_75",
    timeframe: str = "H1",
    service: ApplicationService = Depends(get_service),
) -> MarketSetup:
    """Publish one deterministic analysis-only simulation assessment."""
    return await service.run_offline_analysis(symbol, timeframe)


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


@router.get("/market/setup", response_model=MarketSetup)
async def get_market_setup(
    symbol: str | None = None,
    timeframe: str | None = None,
    count: int | None = None,
    service: ApplicationService = Depends(get_service),
) -> MarketSetup:
    """Return one unified strategy/risk/paper-execution setup."""
    try:
        return await service.get_market_setup(symbol, timeframe, count)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/market/active-analysis", response_model=ActiveMarketAnalysisResponse)
async def get_active_market_analysis(
    symbol: str | None = None,
    timeframe: str | None = None,
    count: int | None = None,
    service: ApplicationService = Depends(get_service),
) -> ActiveMarketAnalysisResponse:
    """Return unified active-market context, telemetry, setup, and explanation."""
    try:
        return await service.get_active_market_analysis(symbol, timeframe, count)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/market/setups/{setup_id}/paper-execute",
    response_model=PaperExecutionOutcomeDTO,
)
async def execute_market_setup(
    setup_id: str,
    service: ApplicationService = Depends(get_service),
) -> PaperExecutionOutcomeDTO:
    """Record an offline paper execution; this route never selects a broker."""
    try:
        return await service.execute_market_setup(setup_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/execution/safety", response_model=ExecutionSafetyResponse)
def get_execution_safety(
    service: ApplicationService = Depends(get_service),
) -> ExecutionSafetyResponse:
    """Returns the latest canonical cross-process safety observation."""
    return service.get_execution_safety()


@router.get("/execution/recovery", response_model=RecoveryDiagnosticsResponse)
def get_recovery_diagnostics(
    service: ApplicationService = Depends(get_service),
) -> RecoveryDiagnosticsResponse:
    """Returns read-only durable startup recovery diagnostics."""
    return service.get_recovery_diagnostics()


@router.get("/execution/paper-runtime", response_model=PaperRuntimeStatusResponse)
def get_paper_runtime_status(
    service: ApplicationService = Depends(get_service),
) -> PaperRuntimeStatusResponse:
    """Returns the read-only continuous paper-runtime heartbeat."""
    return service.get_paper_runtime_status()


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


@router.get("/brokers/status", response_model=BrokerStatusResponse)
def get_broker_status(
    service: ApplicationService = Depends(get_service),
) -> BrokerStatusResponse:
    """Returns multi-broker connection state and DemoOnlyGuard verification status."""
    try:
        return service.get_broker_status()
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/brokers/select", response_model=SelectBrokerResponse)
def select_broker(
    request: SelectBrokerRequest,
    service: ApplicationService = Depends(get_service),
) -> SelectBrokerResponse:
    """Validates and persists the operator broker selection; never falls back to simulation."""
    try:
        return service.select_broker(request.broker, reason=request.reason)
    except BrokerSwitchConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BrokerUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/watchlist/cap-usage", response_model=WatchlistCapUsageResponse)
def get_watchlist_cap_usage(
    account_scope: str = Query(default="default", description="Account scope for daily instrument guard"),
    service: ApplicationService = Depends(get_service),
) -> WatchlistCapUsageResponse:
    """Returns daily instrument cap usage for each watchlisted instrument."""
    try:
        return service.get_watchlist_cap_usage(account_scope=account_scope)
    except JQEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
