"""Typed factual notification messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from datetime import datetime
from typing import Mapping

from notifications.chart import ChartSnapshot


class NotificationType(str, Enum):
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    TRADE_AUTHORIZED = "TRADE_AUTHORIZED"
    TRADE_BLOCKED = "TRADE_BLOCKED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    PENDING_ORDER_PLACED = "PENDING_ORDER_PLACED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_MODIFIED = "POSITION_MODIFIED"
    POSITION_CLOSED = "POSITION_CLOSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    RUNTIME_HEALTH = "RUNTIME_HEALTH"
    BROKER_CONNECTION = "BROKER_CONNECTION"
    DAILY_DIGEST = "DAILY_DIGEST"
    DERIV_IDENTITY_VERIFIED = "DERIV_IDENTITY_VERIFIED"
    DERIV_IDENTITY_REJECTED = "DERIV_IDENTITY_REJECTED"
    PAPER_POSITION_OPENED = "PAPER_POSITION_OPENED"
    PAPER_POSITION_CLOSED = "PAPER_POSITION_CLOSED"
    PAPER_TRADE_BLOCKED = "PAPER_TRADE_BLOCKED"
    PAPER_STOP_LOSS = "PAPER_STOP_LOSS"
    PAPER_TAKE_PROFIT = "PAPER_TAKE_PROFIT"
    PAPER_PERFORMANCE = "PAPER_PERFORMANCE"
    PAPER_RUNTIME_STARTED = "PAPER_RUNTIME_STARTED"
    PAPER_SIGNAL = "PAPER_SIGNAL"
    PAPER_RUNTIME_ERROR = "PAPER_RUNTIME_ERROR"
    PAPER_RUNTIME_STOPPED = "PAPER_RUNTIME_STOPPED"


@dataclass(frozen=True, slots=True)
class DigestSnapshot:
    symbol: str
    timeframe: str
    conclusion: str
    quality_score: int | float | None
    is_steady: bool
    cap_count: int
    cap_limit: int


@dataclass(frozen=True, slots=True)
class Notification:
    kind: NotificationType
    title: str
    facts: Mapping[str, str] = field(default_factory=dict)
    digest_snapshots: tuple[DigestSnapshot, ...] = ()
    occurred_at: datetime | None = None
    chart_snapshot: ChartSnapshot | None = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("notification title must be nonblank")
        clean: dict[str, str] = {}
        for key, value in self.facts.items():
            if not str(key).strip() or not isinstance(value, str):
                raise ValueError("notification facts must be nonblank string pairs")
            clean[str(key).strip()] = value.strip()
        object.__setattr__(self, "facts", MappingProxyType(clean))
