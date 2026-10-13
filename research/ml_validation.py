"""Offline ML research controls, not a signal, trainer or execution path."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import math


FEATURES = frozenset({"rsi", "ema_distance_atr", "ema_slope_atr", "atr_price_ratio",
    "return_1_atr", "return_3_atr", "range_atr", "lagged_spread_atr"})


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamps required")


@dataclass(frozen=True)
class LabelInterval:
    event_id: str
    decision_at: datetime
    features_available_at: datetime
    label_available_at: datetime

    def __post_init__(self):
        for value in (self.decision_at,self.features_available_at,self.label_available_at):
            _aware(value)
        if not self.event_id or self.features_available_at > self.decision_at:
            raise ValueError("Features unavailable at decision time")
        if self.label_available_at <= self.decision_at:
            raise ValueError("Label must resolve after decision")


def validate_features(features: dict[str,float]) -> None:
    """An explicit allowlist prevents outcomes and future fill data becoming inputs."""
    if not features or not set(features).issubset(FEATURES):
        raise ValueError("Unknown, outcome-derived or future feature")
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in features.values()):
        raise ValueError("Only finite numeric features permitted")


def chronological_fold(events: tuple[LabelInterval,...], test_start: datetime,
                       test_end: datetime, embargo: timedelta) -> tuple[tuple[str,...],tuple[str,...]]:
    """Expanding past-only training; purge by actual label availability, not row gap."""
    _aware(test_start); _aware(test_end)
    if test_start >= test_end or embargo < timedelta(0):
        raise ValueError("Invalid fold window/embargo")
    if len({e.event_id for e in events}) != len(events):
        raise ValueError("Duplicate event identity")
    ordered=sorted(events,key=lambda e:(e.decision_at,e.event_id))
    cutoff=test_start-embargo
    train=tuple(e.event_id for e in ordered if e.decision_at<cutoff and e.label_available_at<cutoff)
    # Exclude labels crossing this fold's right boundary, even if a nominal
    # 19-bar horizon was expected: gaps can extend wall-clock holding time.
    test=tuple(e.event_id for e in ordered if test_start<=e.decision_at<test_end and e.label_available_at<test_end)
    return train,test


@dataclass(frozen=True)
class ReadinessEvidence:
    closed_training_events: int
    calendar_days: int
    executed_symbols: int
    exact_costs_verified: bool
    financing_calendar_verified: bool
    all_canonical_opportunities_labelled: bool
    fresh_ml_holdout_registered: bool
    canonical_replay_equivalence_verified: bool

    def __post_init__(self):
        if any(type(v) is not int or v<0 for v in (self.closed_training_events,self.calendar_days,self.executed_symbols)):
            raise ValueError("Nonnegative integer sample counts required")
        for name in ("exact_costs_verified","financing_calendar_verified","all_canonical_opportunities_labelled",
                     "fresh_ml_holdout_registered","canonical_replay_equivalence_verified"):
            if type(getattr(self,name)) is not bool:
                raise ValueError("Evidence status must be an explicit boolean")


def readiness(evidence: ReadinessEvidence) -> dict:
    """Conservative project design gates; sample minima are not statistical guarantees."""
    blocks=[]
    for name in ("exact_costs_verified","financing_calendar_verified","all_canonical_opportunities_labelled",
                 "fresh_ml_holdout_registered","canonical_replay_equivalence_verified"):
        if not getattr(evidence,name):blocks.append(name)
    if evidence.closed_training_events<1000:blocks.append("fewer_than_1000_training_events")
    if evidence.calendar_days<90:blocks.append("fewer_than_90_calendar_days")
    if evidence.executed_symbols<1:blocks.append("no_executable_symbol_sample")
    return {"status":"BLOCKED" if blocks else "ELIGIBLE_FOR_PREREGISTERED_OFFLINE_FIT_ONLY",
        "blocks":blocks,"promotion_authorized":False,
        "claim_scope":"symbol-specific until independently tested across symbols",
        "threshold_scope":"project research design choices, not statistical sufficiency guarantees"}
