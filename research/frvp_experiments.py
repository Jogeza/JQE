"""Deterministic, research-only FRVP counterfactual experiments."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import Enum
from statistics import median
from typing import Sequence

from backtesting.models import BacktestResult, BacktestTrade
from broker.types import Candle
from data.provenance import VolumeType
from research.volume_profile import FRVP_ALGORITHM_VERSION, VolumeProfileRequest, calculate_volume_profile

EXPERIMENT_VERSION = "frvp-experiment-v1"
MAX_PARAMETER_CANDIDATES = 8
MAX_PROFILE_CALCULATIONS = 1_000
MIN_SPLIT_CANDLES = 30


class HypothesisId(str, Enum):
    POC_PROXIMITY_FILTER_V1 = "POC_PROXIMITY_FILTER_V1"
    VALUE_AREA_LOCATION_V1 = "VALUE_AREA_LOCATION_V1"


class ExperimentStatus(str, Enum):
    COMPLETED = "COMPLETED"
    FRVP_EXPERIMENT_UNAVAILABLE = "FRVP_EXPERIMENT_UNAVAILABLE"
    INSUFFICIENT_DATA_FOR_SPLIT = "INSUFFICIENT_DATA_FOR_SPLIT"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


class ResearchConclusion(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    NO_OUT_OF_SAMPLE_IMPROVEMENT = "NO_OUT_OF_SAMPLE_IMPROVEMENT"
    OUT_OF_SAMPLE_IMPROVEMENT_OBSERVED = "OUT_OF_SAMPLE_IMPROVEMENT_OBSERVED"
    MIXED_RESULT = "MIXED_RESULT"


class ValueAreaLocation(str, Enum):
    ABOVE_VAH = "ABOVE_VAH"
    INSIDE_VALUE_AREA = "INSIDE_VALUE_AREA"
    BELOW_VAL = "BELOW_VAL"


@dataclass(frozen=True, slots=True)
class ExperimentRequest:
    hypothesis_id: HypothesisId
    profile_lookback: int
    bin_size: Decimal
    threshold_candidates: tuple[Decimal, ...] = (Decimal("0.25"), Decimal("0.50"), Decimal("1.00"))
    train_fraction: Decimal = Decimal("0.60")
    validation_fraction: Decimal = Decimal("0.20")
    minimum_trade_count: int = 30


@dataclass(frozen=True, slots=True)
class FeatureObservation:
    candle_index: int
    profile_start_index: int
    profile_end_index: int
    price: Decimal
    poc: Decimal
    vah: Decimal
    val: Decimal
    atr: Decimal
    distance_to_poc_atr: Decimal
    location: ValueAreaLocation


@dataclass(frozen=True, slots=True)
class ExperimentMetrics:
    trade_count: int
    win_rate: float
    net_pnl: float
    expectancy: float
    profit_factor: float | None
    max_drawdown: float
    average_result: float
    median_result: float
    sample_sufficient: bool


@dataclass(frozen=True, slots=True)
class MetricDeltas:
    trade_count_delta: int
    net_pnl_delta: float
    win_rate_delta: float
    expectancy_delta: float
    profit_factor_delta: float | None
    max_drawdown_delta: float


@dataclass(frozen=True, slots=True)
class PartitionComparison:
    baseline: ExperimentMetrics
    variant: ExperimentMetrics
    deltas: MetricDeltas


@dataclass(frozen=True, slots=True)
class LocationGroup:
    location: ValueAreaLocation
    metrics: ExperimentMetrics


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    status: ExperimentStatus
    reason: str
    experiment_id: str
    dataset_identity: str
    strategy_identity: str
    experiment_version: str
    frvp_algorithm_version: str
    volume_type: VolumeType
    volume_source: str
    request: ExperimentRequest
    split_boundaries: tuple[int, int]
    selected_threshold: Decimal | None
    selection_metric: str
    conclusion: ResearchConclusion
    train: PartitionComparison | None
    validation: PartitionComparison | None
    out_of_sample: PartitionComparison | None
    validation_candidates: tuple[tuple[Decimal, ExperimentMetrics], ...] = ()
    training_candidates: tuple[tuple[Decimal, ExperimentMetrics], ...] = ()
    location_groups: tuple[LocationGroup, ...] = ()
    features: tuple[FeatureObservation, ...] = ()


def _metrics(trades: Sequence[BacktestTrade], minimum: int) -> ExperimentMetrics:
    pnls = [float(t.net_pnl) for t in trades]
    wins, losses = [p for p in pnls if p > 0], [p for p in pnls if p < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    balance = peak = drawdown = 0.0
    for pnl in pnls:
        balance += pnl
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    count = len(pnls)
    return ExperimentMetrics(count, len(wins) / count * 100 if count else 0.0,
        sum(pnls), sum(pnls) / count if count else 0.0,
        gross_profit / gross_loss if gross_loss else None, drawdown,
        sum(pnls) / count if count else 0.0, float(median(pnls)) if pnls else 0.0,
        count >= minimum)


def _comparison(baseline: Sequence[BacktestTrade], variant: Sequence[BacktestTrade], minimum: int) -> PartitionComparison:
    b, v = _metrics(baseline, minimum), _metrics(variant, minimum)
    return PartitionComparison(b, v, MetricDeltas(v.trade_count-b.trade_count, v.net_pnl-b.net_pnl,
        v.win_rate-b.win_rate, v.expectancy-b.expectancy,
        None if b.profit_factor is None or v.profit_factor is None else v.profit_factor-b.profit_factor,
        v.max_drawdown-b.max_drawdown))


def _identity(dataset: str, strategy: str, request: ExperimentRequest) -> str:
    def norm(value):
        if isinstance(value, Decimal): return str(value)
        if isinstance(value, Enum): return value.value
        if isinstance(value, dict): return {k: norm(v) for k, v in sorted(value.items())}
        if isinstance(value, (list, tuple)): return [norm(v) for v in value]
        return value
    payload = {"dataset": dataset, "strategy": strategy, "version": EXPERIMENT_VERSION, "request": norm(asdict(request))}
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _strategy_identity(result: BacktestResult) -> str:
    payload = json.dumps(result.strategy, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def run_frvp_experiment(candles: Sequence[Candle], baseline: BacktestResult, *, dataset_identity: str,
                        volume_type: VolumeType, volume_source: str, request: ExperimentRequest) -> ExperimentResult:
    """Evaluate existing baseline trades only; profiles end at their decision candle."""
    strategy_id = _strategy_identity(baseline)
    identity = _identity(dataset_identity, strategy_id, request)
    empty = dict(experiment_id=identity, dataset_identity=dataset_identity, strategy_identity=strategy_id,
        experiment_version=EXPERIMENT_VERSION, frvp_algorithm_version=FRVP_ALGORITHM_VERSION,
        volume_type=volume_type, volume_source=volume_source, request=request, split_boundaries=(0, 0),
        selected_threshold=None, selection_metric="VALIDATION_EXPECTANCY", conclusion=ResearchConclusion.NOT_EVALUATED, train=None, validation=None,
        out_of_sample=None)
    if volume_type in (VolumeType.UNAVAILABLE, VolumeType.UNKNOWN):
        return ExperimentResult(ExperimentStatus.FRVP_EXPERIMENT_UNAVAILABLE, f"Volume semantics {volume_type.value} are ineligible", **empty)
    if request.profile_lookback < 2 or request.bin_size <= 0 or request.minimum_trade_count < 1:
        return ExperimentResult(ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT, "Experiment configuration is invalid", **empty)
    if len(request.threshold_candidates) > MAX_PARAMETER_CANDIDATES:
        return ExperimentResult(ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT, "Too many parameter candidates", **empty)
    train_end = int(len(candles) * request.train_fraction)
    validation_end = train_end + int(len(candles) * request.validation_fraction)
    if train_end < MIN_SPLIT_CANDLES or validation_end-train_end < MIN_SPLIT_CANDLES or len(candles)-validation_end < MIN_SPLIT_CANDLES:
        return ExperimentResult(ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT, "Each chronological partition requires at least 30 candles", **empty)
    baseline_bytes = baseline.to_json_bytes()
    if len(baseline_bytes) == 0:
        raise ValueError("Canonical baseline serialization failed")
    index_by_time = {c.time: i for i, c in enumerate(candles)}
    trades = [t for t in baseline.trades if t.signal_timestamp in index_by_time]
    calculations = len(trades)
    if calculations > MAX_PROFILE_CALCULATIONS:
        return ExperimentResult(ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT, "Experiment exceeds profile calculation limit", **empty)
    indicators = {i.candle_index: i for i in baseline.indicators}
    features: list[FeatureObservation] = []
    trade_features: dict[int, FeatureObservation] = {}
    for trade in trades:
        n = index_by_time[trade.signal_timestamp]
        start = n - request.profile_lookback + 1
        observation = indicators.get(n)
        if start < 0 or observation is None or observation.atr is None or observation.atr <= 0:
            continue
        profile = calculate_volume_profile(candles, dataset_identity=dataset_identity, volume_type=volume_type,
            volume_source=volume_source, request=VolumeProfileRequest(start, n, request.bin_size))
        if not profile.eligible or profile.snapshot is None:
            continue
        snap, price, atr = profile.snapshot, Decimal(str(trade.entry_price)), Decimal(str(observation.atr))
        location = ValueAreaLocation.ABOVE_VAH if price > snap.value_area_high else ValueAreaLocation.BELOW_VAL if price < snap.value_area_low else ValueAreaLocation.INSIDE_VALUE_AREA
        feature = FeatureObservation(n, start, n, price, snap.point_of_control, snap.value_area_high,
            snap.value_area_low, atr, abs(price-snap.point_of_control)/atr, location)
        features.append(feature); trade_features[trade.trade_id] = feature

    def partition(lo: int, hi: int) -> list[BacktestTrade]:
        return [t for t in trades if lo <= index_by_time[t.signal_timestamp] < hi and t.trade_id in trade_features]
    parts = (partition(0, train_end), partition(train_end, validation_end), partition(validation_end, len(candles)))
    selected: Decimal | None = None
    candidates: list[tuple[Decimal, ExperimentMetrics]] = []
    training_candidates: list[tuple[Decimal, ExperimentMetrics]] = []
    groups: list[LocationGroup] = []
    if request.hypothesis_id is HypothesisId.POC_PROXIMITY_FILTER_V1:
        thresholds = tuple(sorted(set(request.threshold_candidates)))
        if not thresholds or any(t < 0 for t in thresholds):
            return ExperimentResult(ExperimentStatus.INSUFFICIENT_DATA_FOR_SPLIT, "Threshold candidates are invalid", **empty)
        for threshold in thresholds:
            training_candidates.append((threshold, _metrics([t for t in parts[0] if trade_features[t.trade_id].distance_to_poc_atr >= threshold], request.minimum_trade_count)))
            accepted = [t for t in parts[1] if trade_features[t.trade_id].distance_to_poc_atr >= threshold]
            candidates.append((threshold, _metrics(accepted, request.minimum_trade_count)))
        selected = max(candidates, key=lambda item: (item[1].expectancy, item[1].net_pnl, -float(item[0])))[0]
        variants = tuple([t for t in part if trade_features[t.trade_id].distance_to_poc_atr >= selected] for part in parts)
    else:
        variants = parts
        for location in ValueAreaLocation:
            groups.append(LocationGroup(location, _metrics([t for t in trades if t.trade_id in trade_features and trade_features[t.trade_id].location is location], request.minimum_trade_count)))
    comparisons = tuple(_comparison(base, variant, request.minimum_trade_count) for base, variant in zip(parts, variants))
    sufficient = comparisons[2].variant.sample_sufficient
    status = ExperimentStatus.COMPLETED if sufficient else ExperimentStatus.INSUFFICIENT_SAMPLE
    conclusion = ResearchConclusion.NOT_EVALUATED
    if sufficient and request.hypothesis_id is HypothesisId.POC_PROXIMITY_FILTER_V1:
        pnl_up = comparisons[2].deltas.net_pnl_delta > 0
        expectancy_up = comparisons[2].deltas.expectancy_delta > 0
        conclusion = (ResearchConclusion.OUT_OF_SAMPLE_IMPROVEMENT_OBSERVED if pnl_up and expectancy_up
            else ResearchConclusion.MIXED_RESULT if pnl_up or expectancy_up
            else ResearchConclusion.NO_OUT_OF_SAMPLE_IMPROVEMENT)
    if baseline.to_json_bytes() != baseline_bytes:
        raise RuntimeError("Canonical baseline changed during FRVP experiment")
    return ExperimentResult(status, "Deterministic offline comparison completed" if sufficient else "Out-of-sample trade count is below the configured minimum",
        identity, dataset_identity, strategy_id, EXPERIMENT_VERSION, FRVP_ALGORITHM_VERSION, volume_type,
        volume_source, request, (train_end, validation_end), selected, "VALIDATION_EXPECTANCY", conclusion,
        comparisons[0], comparisons[1], comparisons[2], tuple(candidates), tuple(training_candidates), tuple(groups), tuple(features))
