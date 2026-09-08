"""Durable i/i+1/i+2 state for confirmation-aware historical campaigns."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from research.regime_diagnostics import confirmation_expected_regime, confirmation_regime_passes


@dataclass(frozen=True, slots=True)
class PendingHistoricalCandidate:
    symbol: str
    timeframe: str
    signal_candle: datetime
    direction: str
    confidence: int
    strategy_context: dict[str, Any]
    expected_confirmation_candle: datetime
    expected_entry_candle: datetime
    confirmation_evaluated: bool = False
    confirmed: bool = False
    confirmation_reason: str | None = None

    def __post_init__(self) -> None:
        if self.direction not in {"BUY", "SELL"}:
            raise ValueError("pending candidate direction must be BUY or SELL")
        if any(value.tzinfo is None for value in (
            self.signal_candle, self.expected_confirmation_candle, self.expected_entry_candle,
        )):
            raise ValueError("pending candidate timestamps must be timezone-aware")
        if not self.signal_candle < self.expected_confirmation_candle < self.expected_entry_candle:
            raise ValueError("pending candidate chronology must be i < i+1 < i+2")


@dataclass(frozen=True, slots=True)
class ConfirmationTransition:
    state: str
    candidate: PendingHistoricalCandidate | None
    reason: str


class HistoricalConfirmationState:
    """Single-candidate state machine; later candles never substitute for gaps."""

    def __init__(self, pending: PendingHistoricalCandidate | None = None) -> None:
        self.pending = pending

    def queue(
        self, *, symbol: str, timeframe: str, signal_candle: datetime,
        direction: str, confidence: int, strategy_context: dict[str, Any],
        candle_interval: timedelta,
    ) -> ConfirmationTransition:
        if self.pending is not None:
            return ConfirmationTransition("REJECTED_CANDIDATE", self.pending, "Entry already pending")
        self.pending = PendingHistoricalCandidate(
            symbol=symbol, timeframe=timeframe, signal_candle=signal_candle,
            direction=direction, confidence=confidence,
            strategy_context=dict(strategy_context),
            expected_confirmation_candle=signal_candle + candle_interval,
            expected_entry_candle=signal_candle + candle_interval * 2,
        )
        return ConfirmationTransition("STRATEGY_CANDIDATE", self.pending, "Pending confirmation")

    def observe(self, candle_opened_at: datetime, regime: str) -> ConfirmationTransition:
        candidate = self.pending
        if candidate is None:
            return ConfirmationTransition("NO_PENDING_CANDIDATE", None, "No pending candidate")
        if candle_opened_at < candidate.expected_confirmation_candle:
            return ConfirmationTransition("PENDING_CONFIRMATION", candidate, "Confirmation candle not reached")
        if candle_opened_at > candidate.expected_confirmation_candle and not candidate.confirmation_evaluated:
            self.pending = None
            return ConfirmationTransition("INCOMPLETE_CONFIRMATION", candidate, "MISSING_CONFIRMATION_CANDLE")
        if candle_opened_at == candidate.expected_confirmation_candle:
            if candidate.confirmation_evaluated:
                return ConfirmationTransition("DUPLICATE_CONFIRMATION_PREVENTED", candidate, "Confirmation already evaluated")
            passed = confirmation_regime_passes(candidate.direction, regime)
            reason = (
                f"Confirmation candle regime {regime}; entry eligible at next candle open"
                if passed else
                f"Confirmation candle regime {regime} failed {confirmation_expected_regime(candidate.direction)} requirement"
            )
            self.pending = PendingHistoricalCandidate(
                **{**asdict(candidate), "confirmation_evaluated": True,
                   "confirmed": passed, "confirmation_reason": reason}
            )
            if not passed:
                failed = self.pending
                self.pending = None
                return ConfirmationTransition("CONFIRMATION_FAILED", failed, reason)
            return ConfirmationTransition("CONFIRMED", self.pending, reason)
        if candle_opened_at < candidate.expected_entry_candle:
            return ConfirmationTransition("CONFIRMED", candidate, candidate.confirmation_reason or "Confirmed")
        if candle_opened_at > candidate.expected_entry_candle:
            self.pending = None
            return ConfirmationTransition("INCOMPLETE_ENTRY", candidate, "MISSING_ENTRY_CANDLE")
        self.pending = None
        return ConfirmationTransition("ENTRY_DUE", candidate, "Authoritative i+2 open available")

    def finish(self) -> ConfirmationTransition | None:
        if self.pending is None:
            return None
        candidate = self.pending
        self.pending = None
        state = "INCOMPLETE_ENTRY" if candidate.confirmed else "INCOMPLETE_CONFIRMATION"
        return ConfirmationTransition(state, candidate, "CAMPAIGN_BOUNDARY")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = None if self.pending is None else asdict(self.pending)
        if payload:
            for name in ("signal_candle", "expected_confirmation_candle", "expected_entry_candle"):
                payload[name] = payload[name].isoformat()
        path.write_text(json.dumps(payload, sort_keys=True, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "HistoricalConfirmationState":
        if not path.is_file():
            raise RuntimeError("pending confirmation reconstruction is unavailable")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload is None:
            return cls()
        for name in ("signal_candle", "expected_confirmation_candle", "expected_entry_candle"):
            payload[name] = datetime.fromisoformat(payload[name])
        return cls(PendingHistoricalCandidate(**payload))
