"""Typed factual notification messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class NotificationType(str, Enum):
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    TRADE_AUTHORIZED = "TRADE_AUTHORIZED"
    TRADE_BLOCKED = "TRADE_BLOCKED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_REJECTED = "ORDER_REJECTED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    RUNTIME_HEALTH = "RUNTIME_HEALTH"
    DERIV_IDENTITY_VERIFIED = "DERIV_IDENTITY_VERIFIED"
    DERIV_IDENTITY_REJECTED = "DERIV_IDENTITY_REJECTED"
    PAPER_POSITION_OPENED = "PAPER_POSITION_OPENED"
    PAPER_POSITION_CLOSED = "PAPER_POSITION_CLOSED"
    PAPER_TRADE_BLOCKED = "PAPER_TRADE_BLOCKED"
    PAPER_STOP_LOSS = "PAPER_STOP_LOSS"
    PAPER_TAKE_PROFIT = "PAPER_TAKE_PROFIT"
    PAPER_PERFORMANCE = "PAPER_PERFORMANCE"


@dataclass(frozen=True, slots=True)
class Notification:
    kind: NotificationType
    title: str
    facts: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("notification title must be nonblank")
        clean: dict[str, str] = {}
        for key, value in self.facts.items():
            if not str(key).strip() or not isinstance(value, str):
                raise ValueError("notification facts must be nonblank string pairs")
            clean[str(key).strip()] = value.strip()
        object.__setattr__(self, "facts", MappingProxyType(clean))
