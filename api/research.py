"""Ephemeral research sessions. No gateways, network access, or execution APIs."""
from __future__ import annotations

from collections import OrderedDict
import json
import re
from pathlib import Path
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from backtesting.backtest import run_backtest
from backtesting.drawdown import balance_drawdown
from backtesting.models import BacktestResult, CandleDatasetSnapshot
from broker.types import Candle, Timeframe
from data.dataset import candle_content_hash
from data.storage import CandleStore
from data.watchlist import WatchlistStore
from data.provenance import DatasetProvenance, VolumeType
from data.historical import HistoricalDataService
from broker.deriv_public_data import DerivPublicMarketData
from research.markets import MarketCatalogueService, catalogue_from_watchlist
from config.settings import settings
from core.exceptions import MarketDataError
from broker.types import TIMEFRAME_SECONDS
from research.volume_profile import (
    VolumeAllocationMethod, VolumeProfileRequest as DomainVolumeProfileRequest,
    calculate_volume_profile,
)
from research.frvp_experiments import (
    ExperimentRequest as DomainExperimentRequest, HypothesisId, run_frvp_experiment,
)
from research.acquisitions import (
    AcquisitionErrorCode, AcquisitionFailure, AcquisitionJobRegistry,
    AcquisitionOutcome, AcquisitionSpec,
)
from research.experiments import (
    ExperimentCatalog, ExperimentNotFoundError, ExperimentStatus,
    compare_experiment_records, experiment_record_dict,
)
from research.paper_diagnostics import PaperDiagnosticsStore, summarize
from data.storage import find_gaps


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    symbol: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_. -]+$")
    timeframe: Timeframe
    count: int = Field(default=300, ge=201, le=2000)
    initial_capital: float = Field(default=1000, gt=0, le=1e9, allow_inf_nan=False)


class DatasetDTO(BaseModel):
    provider: str
    symbol: str
    timeframe: Timeframe
    start: datetime
    end: datetime
    candle_count: int
    content_hash: str


class VolumeDTO(BaseModel):
    available: bool
    type: str
    source: str


class IndicatorDTO(BaseModel):
    candle_index: int
    timestamp: datetime
    ema50: float | None
    ema200: float | None
    rsi: float | None
    atr: float | None
    regime: str | None


class SessionDTO(BaseModel):
    id: str
    dataset: DatasetDTO
    run_fingerprint: str
    result_hash: str
    engine_version: str
    identity_schema_version: int
    strategy: dict[str, JsonValue]
    volume_metadata: VolumeDTO


class ExperimentSummaryDTO(BaseModel):
    experiment_id: str
    status: ExperimentStatus
    created_at: datetime
    symbol: str
    timeframe: str
    effective_start: datetime
    effective_end: datetime
    candle_count: int
    dataset_hash: str | None
    run_fingerprint: str | None
    result_hash: str | None
    engine_version: str | None
    identity_schema_version: int | None
    initial_capital: float | None
    ending_capital: float | None
    total_return: float | None
    total_trades: int | None
    fully_reproducible: bool


class DiscoveryIssueDTO(BaseModel):
    file_name: str
    code: str
    message: str


class ExperimentListDTO(BaseModel):
    experiments: list[ExperimentSummaryDTO]
    issues: list[DiscoveryIssueDTO]
    total: int
    limit: int
    offset: int


class ExperimentDetailDTO(BaseModel):
    schema_version: int
    experiment_id: str
    status: ExperimentStatus
    created_at: datetime
    dataset_hash: str | None
    run_fingerprint: str | None
    result_hash: str | None
    engine_version: str | None
    identity_schema_version: int | None
    symbol: str
    timeframe: str
    partition: str
    partition_first_candle: datetime
    partition_last_candle: datetime
    partition_candle_count: int
    strategy_name: str
    configuration: dict[str, JsonValue]
    metrics: dict[str, JsonValue]
    provenance: dict[str, JsonValue]


class ExperimentComparisonDTO(BaseModel):
    left_experiment_id: str
    right_experiment_id: str
    classification: str
    controlled_comparison: bool
    both_fully_reproducible: bool
    same_dataset: bool
    same_run_configuration: bool
    same_result: bool
    same_strategy_configuration: bool
    same_risk_configuration: bool
    same_execution_assumptions: bool
    metric_deltas: dict[str, float | int | None]


class IndexedCandleDTO(BaseModel):
    candle_index: int
    candle: Candle
    indicators: IndicatorDTO


class DecisionDTO(BaseModel):
    candle_index: int
    timestamp: datetime
    signal: str
    confidence: int
    state: str
    reasons: tuple[str, ...]
    entry_price: float | None
    stop_price: float | None
    target_price: float | None


class TradeDTO(BaseModel):
    trade_id: int
    entry_index: int
    entry_timestamp: datetime
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    quantity_value: float
    quantity_unit: str
    balance_before: float
    exit_index: int | None = None
    exit_timestamp: datetime | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    net_pnl: float | None = None
    balance_after: float | None = None


class BalancePointDTO(BaseModel):
    candle_index: int
    timestamp: datetime
    balance: float
    drawdown: float
    drawdown_percent: float


class ReplayDTO(BaseModel):
    id: str
    cursor: int
    complete: bool
    candles: list[IndexedCandleDTO]
    signals: list[DecisionDTO]
    trades: list[TradeDTO]
    balance_curve: list[BalancePointDTO]
    balance_basis: str = "REALIZED_BALANCE"
    metrics: dict[str, JsonValue] | None = None


class VolumeProfileApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range_start_index: int = Field(ge=0)
    range_end_index: int = Field(ge=0)
    bin_size: Decimal = Field(gt=0, allow_inf_nan=False)
    value_area_fraction: Decimal = Field(default=Decimal("0.70"), gt=0, le=1, allow_inf_nan=False)
    cursor: int | None = Field(default=None, ge=0)


class VolumeProfileBinDTO(BaseModel):
    low: Decimal
    high: Decimal
    volume: Decimal


class VolumeProfileSnapshotDTO(BaseModel):
    dataset_identity: str
    range_start_index: int
    range_end_index: int
    start_time: datetime
    end_time: datetime
    candle_count: int
    volume_type: str
    volume_source: str
    profile_low: Decimal
    profile_high: Decimal
    total_volume: Decimal
    bin_size: Decimal
    bin_count: int
    value_area_fraction: Decimal
    allocation_method: str
    algorithm_version: str
    point_of_control: Decimal
    value_area_high: Decimal
    value_area_low: Decimal
    range_has_gaps: bool
    gap_count: int
    bins: list[VolumeProfileBinDTO]


class VolumeProfileResultDTO(BaseModel):
    eligible: bool
    eligibility: str
    reason: str
    snapshot: VolumeProfileSnapshotDTO | None = None


class ExperimentApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis_id: HypothesisId
    profile_lookback: int = Field(ge=2, le=200)
    bin_size: Decimal = Field(gt=0, allow_inf_nan=False)
    threshold_candidates: tuple[Decimal, ...] = Field(default=(Decimal("0.25"), Decimal("0.50"), Decimal("1.00")), min_length=1, max_length=8)
    train_fraction: Decimal = Field(default=Decimal("0.60"), gt=0, lt=1)
    validation_fraction: Decimal = Field(default=Decimal("0.20"), gt=0, lt=1)
    minimum_trade_count: int = Field(default=30, ge=1, le=1000)


class AcquireHistoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_symbol: str = Field(min_length=2, max_length=30, pattern=r"^\w{2,30}$")
    timeframe: Timeframe
    requested_start: datetime
    requested_end: datetime

    @model_validator(mode="after")
    def validate_range(self):
        if self.requested_start.tzinfo is None or self.requested_end.tzinfo is None:
            raise ValueError("Historical range must be timezone-aware")
        if self.requested_end < self.requested_start:
            raise ValueError("Historical range must be ordered")
        step = TIMEFRAME_SECONDS[self.timeframe]
        count = int((self.requested_end - self.requested_start).total_seconds() // step) + 1
        if count < 201 or count > 5000:
            raise ValueError("Historical range must contain between 201 and 5000 candles")
        if (self.requested_end - self.requested_start).total_seconds() % step:
            raise ValueError("Historical range must align to the selected timeframe")
        return self


@dataclass(frozen=True)
class ResearchSession:
    metadata: SessionDTO
    candles: tuple[Candle, ...]
    result: BacktestResult


def create_session(candles: list[Candle], result: BacktestResult, provenance: DatasetProvenance | None = None) -> ResearchSession:
    snapshot = CandleDatasetSnapshot(result.provider, result.symbol, result.timeframe, tuple(candles))
    available = all(c.volume is not None for c in candles)
    # Cache does not preserve explicit volume type. Never infer exchange volume.
    volume_type = provenance.volume_type if provenance else (VolumeType.UNKNOWN if available else VolumeType.UNAVAILABLE)
    volume = VolumeDTO(available=available, type=volume_type.value,
                       source=provenance.source if provenance else result.provider)
    return ResearchSession(SessionDTO(
        id=uuid4().hex,
        dataset=DatasetDTO(provider=result.provider, symbol=result.symbol, timeframe=result.timeframe,
                           start=snapshot.start, end=snapshot.end, candle_count=len(candles),
                           content_hash=result.dataset_hash),
        run_fingerprint=result.run_fingerprint,
        result_hash=result.result_hash,
        engine_version=result.engine_version,
        identity_schema_version=result.identity_schema_version,
        strategy=result.strategy, volume_metadata=volume,
    ), snapshot.candles, result)


def replay(session: ResearchSession, cursor: int) -> ReplayDTO:
    if not 0 <= cursor < len(session.candles):
        raise HTTPException(422, "Cursor outside dataset")
    index = {c.time: i for i, c in enumerate(session.candles)}
    trades = []
    balance_at_exit: dict[int, float] = {}
    for trade in session.result.trades:
        entry, exit_ = index[trade.entry_timestamp], index[trade.exit_timestamp]
        if entry > cursor:
            continue
        item = TradeDTO(trade_id=trade.trade_id, entry_index=entry, entry_timestamp=trade.entry_timestamp,
                        direction=trade.direction, entry_price=trade.entry_price, stop_price=trade.stop_price,
                        target_price=trade.target_price, quantity_value=trade.quantity.value,
                        quantity_unit=trade.quantity.unit.value, balance_before=trade.balance_before)
        if exit_ <= cursor:
            item.exit_index, item.exit_timestamp, item.exit_price = exit_, trade.exit_timestamp, trade.exit_price
            item.exit_reason, item.net_pnl, item.balance_after = trade.exit_reason.value, trade.net_pnl, trade.balance_after
            balance_at_exit[exit_] = trade.balance_after
        trades.append(item)
    balance = peak = session.result.initial_capital
    curve = []
    for i, candle in enumerate(session.candles[:cursor + 1]):
        balance = balance_at_exit.get(i, balance)
        peak, drawdown, percent = balance_drawdown(balance, peak)
        curve.append(BalancePointDTO(candle_index=i, timestamp=candle.time, balance=balance,
                                    drawdown=drawdown, drawdown_percent=percent))
    complete = cursor == len(session.candles)-1
    metrics = session.result.to_dict() if complete else None
    if metrics is not None:
        metrics = {k: v for k, v in metrics.items() if k not in ("trades", "decisions")}
    return ReplayDTO(id=session.metadata.id, cursor=cursor, complete=complete,
                     candles=[IndexedCandleDTO(candle_index=i, candle=c,
                              indicators=IndicatorDTO(**asdict(session.result.indicators[i])))
                              for i, c in enumerate(session.candles[:cursor+1])],
                     signals=[DecisionDTO(**asdict(d)) for d in session.result.decisions if d.candle_index <= cursor],
                     trades=trades, balance_curve=curve, metrics=metrics)


router = APIRouter(prefix="/api/v1/research", tags=["research"])
_sessions: OrderedDict[str, ResearchSession] = OrderedDict()
_lock = Lock()


async def _load_deriv_catalogue():
    source = DerivPublicMarketData(settings.deriv_app_id, endpoint=settings.deriv_public_endpoint)
    async with source:
        return await source.get_active_symbols()


_market_catalogue = MarketCatalogueService(_load_deriv_catalogue)
_acquisition_jobs = AcquisitionJobRegistry()
_experiment_catalog = ExperimentCatalog(settings.research_experiment_path)


@router.get("/paper-diagnostics", response_model=None)
def get_paper_diagnostics(session_id: str | None = None):
    """Return a read-only aggregate of the latest paper observation session or an explicit session."""
    path = Path(settings.paper_diagnostics_path).expanduser().resolve()
    if not path.is_file():
        return {"status": "NOT_OBSERVED", "sample_size_insufficient": True}
    try:
        store = PaperDiagnosticsStore(path, initialize=False)
        session = store.session(session_id) if session_id else store.latest_session()
        if session is None:
            return {"status": "NOT_OBSERVED", "sample_size_insufficient": True}
        return {
            "status": session.status,
            "session": asdict(session),
            "metrics": summarize(
                store.records(session.session_id),
                minimum_sample=settings.paper_diagnostics_minimum_sample,
            ),
        }
    except Exception:
        return {"status": "UNAVAILABLE", "sample_size_insufficient": True}


@router.get("/campaign-provenance/{artifact_name}", response_model=None)
def get_campaign_provenance(artifact_name: str):
    """Expose only safe provenance metadata from a completed campaign artifact."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.json", artifact_name):
        raise HTTPException(422, "Invalid campaign artifact name")
    path = Path("state/paper_campaigns") / artifact_name
    if not path.is_file():
        raise HTTPException(404, "Campaign artifact unavailable")
    payload = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = payload.get("research_fingerprint")
    if not isinstance(fingerprint, dict):
        return {
            "artifact": artifact_name, "provenance_status": "PROVENANCE_INCOMPLETE",
            "dataset_identity": payload.get("session", {}).get("dataset_identity"),
            "git_commit": payload.get("session", {}).get("git_commit"),
        }
    return {
        "artifact": artifact_name, "provenance_status": payload.get("provenance_status"),
        "fingerprint_schema_version": fingerprint.get("schema_version"),
        "research_fingerprint_sha256": fingerprint.get("research_fingerprint_sha256"),
        "dataset_identity": fingerprint.get("dataset_identity"),
        "git_commit": fingerprint.get("git_commit"),
    }


@router.get("/experiments", response_model=ExperimentListDTO)
def list_persisted_experiments(
    symbol: str | None = None, timeframe: str | None = None,
    status: ExperimentStatus | None = None, fully_reproducible: bool | None = None,
    dataset_hash: str | None = None, run_fingerprint: str | None = None,
    limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
):
    """List bounded factual summaries without running research or broker code."""
    try:
        result = _experiment_catalog.discover(
            symbol=symbol, timeframe=timeframe, status=status,
            fully_reproducible=fully_reproducible, dataset_hash=dataset_hash,
            run_fingerprint=run_fingerprint, limit=limit, offset=offset,
        )
    except (ValueError, MarketDataError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "experiments": [asdict(item) for item in result.experiments],
        "issues": [asdict(item) for item in result.issues],
        "total": result.total, "limit": limit, "offset": offset,
    }


@router.get("/experiments/compare", response_model=ExperimentComparisonDTO)
def compare_persisted_experiments(left: str, right: str):
    try:
        comparison = compare_experiment_records(
            _experiment_catalog.load(left), _experiment_catalog.load(right)
        )
    except ExperimentNotFoundError as exc:
        raise HTTPException(404, "Experiment not found") from exc
    except MarketDataError as exc:
        raise HTTPException(422, "Experiment record is malformed") from exc
    return {
        "left_experiment_id": comparison.left_experiment_id,
        "right_experiment_id": comparison.right_experiment_id,
        "classification": comparison.classification.value,
        "controlled_comparison": comparison.controlled_comparison,
        "both_fully_reproducible": comparison.both_fully_reproducible,
        "same_dataset": comparison.same_dataset,
        "same_run_configuration": comparison.same_run_configuration,
        "same_result": comparison.same_result,
        "same_strategy_configuration": comparison.same_strategy_configuration,
        "same_risk_configuration": comparison.same_risk_configuration,
        "same_execution_assumptions": comparison.same_execution_assumptions,
        "metric_deltas": dict(comparison.metric_deltas),
    }


@router.get("/experiments/{experiment_id}", response_model=ExperimentDetailDTO)
def get_persisted_experiment(experiment_id: str):
    try:
        return experiment_record_dict(_experiment_catalog.load(experiment_id))
    except ExperimentNotFoundError as exc:
        raise HTTPException(404, "Experiment not found") from exc
    except MarketDataError as exc:
        raise HTTPException(422, "Experiment record is malformed") from exc


def _acquisition_outcome(store: CandleStore, spec: AcquisitionSpec, cached_before: int,
                         *, provider_request_count: int,
                         provider_received: int | None = None) -> AcquisitionOutcome:
    timeframe = Timeframe(spec.timeframe)
    candles = store.load_candles(spec.canonical_symbol, timeframe, spec.requested_start,
                                 spec.requested_end, provider=spec.provider)
    from data.coverage import validate_historical_coverage
    coverage = validate_historical_coverage(
        candles, provider=spec.provider, canonical_symbol=spec.canonical_symbol,
        provider_symbol=spec.provider_symbol, timeframe=timeframe,
        start=spec.requested_start, end=spec.requested_end,
    )
    complete = coverage.is_complete
    return AcquisitionOutcome(
        cached_before=cached_before, stored_after=len(candles),
        inserted=max(0, len(candles) - cached_before),
        duplicates=(max(0, provider_received - max(0, len(candles) - cached_before))
                    if provider_received is not None else None),
        gap_count=coverage.missing_count, coverage_complete=complete,
        first_timestamp=candles[0].time if candles else None,
        last_timestamp=candles[-1].time if candles else None,
        dataset_hash=candle_content_hash(candles) if candles else None,
        volume_type=VolumeType.UNAVAILABLE.value,
        volume_source="Deriv public historical WebSocket",
        provider_received=provider_received, provider_request_count=provider_request_count,
    )


async def _run_acquisition(spec: AcquisitionSpec) -> AcquisitionOutcome:
    store = CandleStore(settings.historical_data_path)
    timeframe = Timeframe(spec.timeframe)
    before = len(store.load_candles(spec.canonical_symbol, timeframe, spec.requested_start,
                                    spec.requested_end, provider=spec.provider))
    source = DerivPublicMarketData(settings.deriv_app_id, endpoint=settings.deriv_public_endpoint)
    try:
        async with source:
            service = HistoricalDataService(source, store=store)
            await service.get_candles_range(
                spec.canonical_symbol, timeframe, spec.requested_start, spec.requested_end,
                count=spec.requested_max_candles, provider=spec.provider,
                source_symbol=spec.provider_symbol,
            )
    except Exception as exc:
        outcome = _acquisition_outcome(store, spec, before, provider_request_count=1)
        message = str(exc).lower()
        code = (AcquisitionErrorCode.PROVIDER_TIMEOUT if "timed out" in message
                else AcquisitionErrorCode.DATASET_INCOMPLETE if "complete" in message
                else AcquisitionErrorCode.PROVIDER_RESPONSE_INVALID if "malformed" in message
                else AcquisitionErrorCode.ACQUISITION_FAILED)
        raise AcquisitionFailure(code, "Historical provider could not complete this range; retry safely",
                                 outcome) from exc
    store.save_provenance(DatasetProvenance(
        spec.provider, spec.canonical_symbol, spec.timeframe,
        "Deriv public historical WebSocket", spec.provider_symbol,
        VolumeType.UNAVAILABLE, datetime.now(timezone.utc)))
    return _acquisition_outcome(store, spec, before, provider_request_count=1,
                                provider_received=spec.requested_max_candles)


@router.get("/markets", response_model=None)
async def get_research_markets(refresh: bool = False):
    watchlist_store = WatchlistStore(settings.watchlist_store_path)
    watchlist_items = watchlist_store.get_items()
    catalogue = catalogue_from_watchlist(
        watchlist_items,
        provider=settings.effective_broker,
    )
    watched_symbols = {item.symbol.casefold() for item in watchlist_items}
    try:
        cached = tuple(
            item for item in CandleStore(settings.historical_data_path, read_only=True).list_cached_datasets()
            if item.symbol.casefold() in watched_symbols
        )
    except Exception:
        cached = ()
    return {
        "catalogue": asdict(catalogue),
        "cached_datasets": [asdict(item) for item in cached],
        "watchlist": [asdict(item) | {"scope": item.scope} for item in watchlist_items],
        "watchlist_count": len(watchlist_items),
    }


@router.post("/history/acquisitions", response_model=None, status_code=202)
async def acquire_research_history(request: AcquireHistoryRequest):
    instrument = await _market_catalogue.require_instrument(request.provider_symbol)
    if instrument.is_trading_suspended:
        raise HTTPException(422, "Selected Deriv instrument is trading suspended")
    start = request.requested_start.astimezone(timezone.utc)
    end = request.requested_end.astimezone(timezone.utc)
    count = int((end - start).total_seconds() // TIMEFRAME_SECONDS[request.timeframe]) + 1
    spec = AcquisitionSpec("deriv", instrument.canonical_symbol, instrument.provider_symbol,
                           request.timeframe.value, start, end, count)
    store = CandleStore(settings.historical_data_path)
    before = len(store.load_candles(spec.canonical_symbol, request.timeframe, start, end, provider="deriv"))
    cached = _acquisition_outcome(store, spec, before, provider_request_count=0,
                                  provider_received=0)
    try:
        job = _acquisition_jobs.submit(spec, _run_acquisition,
                                       cached_outcome=cached if cached.coverage_complete else None)
    except RuntimeError as exc:
        if str(exc) == AcquisitionErrorCode.JOB_LIMIT_REACHED.value:
            raise HTTPException(429, "Historical acquisition queue is full; retry later") from exc
        raise
    return asdict(job)


@router.get("/history/acquisitions/{job_id}", response_model=None)
def get_acquisition(job_id: str):
    job = _acquisition_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Historical acquisition job expired or unavailable")
    return asdict(job)


@router.post("/backtests", response_model=SessionDTO)
async def start_backtest(request: ResearchRequest) -> SessionDTO:
    store = CandleStore(settings.historical_data_path, read_only=True)
    candles = store.load_latest(request.symbol, request.timeframe, request.count, provider=request.provider)
    engine = await run_backtest(symbol=request.symbol, timeframe=request.timeframe, dataset=candles,
                                provider=request.provider, starting_balance=request.initial_capital)
    assert engine.result is not None
    session = create_session(candles, engine.result, store.load_provenance(request.provider, request.symbol, request.timeframe))
    with _lock:
        _sessions[session.metadata.id] = session
        while len(_sessions) > 8:
            _sessions.popitem(last=False)
    return session.metadata


@router.get("/backtests/{session_id}/replay", response_model=ReplayDTO, response_model_exclude_none=True)
def get_replay(session_id: str, cursor: int = 0) -> ReplayDTO:
    with _lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Research session expired or unavailable; rerun the backtest")
    return replay(session, cursor)


@router.post("/backtests/{session_id}/volume-profile", response_model=VolumeProfileResultDTO,
             response_model_exclude_none=True)
def get_volume_profile(session_id: str, request: VolumeProfileApiRequest) -> VolumeProfileResultDTO:
    """Calculate FRVP from the immutable canonical session dataset only."""
    with _lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Research session expired or unavailable; rerun the backtest")
    if request.cursor is not None and request.range_end_index > request.cursor:
        raise HTTPException(422, "Volume-profile range cannot include candles after replay cursor")
    domain_request = DomainVolumeProfileRequest(
        start_index=request.range_start_index, end_index=request.range_end_index,
        bin_size=request.bin_size, value_area_fraction=request.value_area_fraction,
        allocation_method=VolumeAllocationMethod.UNIFORM_RANGE_OVERLAP_V1,
    )
    result = calculate_volume_profile(
        session.candles, dataset_identity=session.metadata.dataset.content_hash,
        volume_type=VolumeType(session.metadata.volume_metadata.type),
        volume_source=session.metadata.volume_metadata.source, request=domain_request,
        step_seconds=TIMEFRAME_SECONDS[session.metadata.dataset.timeframe],
    )
    snapshot = None
    if result.snapshot is not None:
        item = result.snapshot
        snapshot = VolumeProfileSnapshotDTO(
            dataset_identity=item.dataset_identity,
            range_start_index=item.request.start_index, range_end_index=item.request.end_index,
            start_time=item.start_time, end_time=item.end_time, candle_count=item.candle_count,
            volume_type=item.volume_type.value, volume_source=item.volume_source,
            profile_low=item.profile_low, profile_high=item.profile_high, total_volume=item.total_volume,
            bin_size=item.request.bin_size, bin_count=len(item.bins),
            value_area_fraction=item.request.value_area_fraction,
            allocation_method=item.request.allocation_method.value,
            algorithm_version=item.request.algorithm_version,
            point_of_control=item.point_of_control, value_area_high=item.value_area_high,
            value_area_low=item.value_area_low, range_has_gaps=item.range_has_gaps,
            gap_count=item.gap_count, bins=[VolumeProfileBinDTO(**asdict(bin_)) for bin_ in item.bins],
        )
    return VolumeProfileResultDTO(eligible=result.eligible, eligibility=result.eligibility.value,
                                  reason=result.reason, snapshot=snapshot)


@router.post("/backtests/{session_id}/experiments", response_model=None)
def run_experiment(session_id: str, request: ExperimentApiRequest):
    """Run a bounded counterfactual against the immutable session baseline."""
    with _lock:
        session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Research session expired or unavailable; rerun the backtest")
    if request.train_fraction + request.validation_fraction >= 1:
        raise HTTPException(422, "Train and validation fractions must leave an out-of-sample partition")
    result = run_frvp_experiment(session.candles, session.result,
        dataset_identity=session.metadata.dataset.content_hash,
        volume_type=VolumeType(session.metadata.volume_metadata.type),
        volume_source=session.metadata.volume_metadata.source,
        request=DomainExperimentRequest(request.hypothesis_id, request.profile_lookback,
            request.bin_size, request.threshold_candidates, request.train_fraction,
            request.validation_fraction, request.minimum_trade_count))
    return asdict(result)
