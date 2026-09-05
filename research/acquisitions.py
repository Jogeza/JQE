"""Bounded in-process coordination for public historical research acquisition."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Awaitable, Callable
from uuid import uuid4


class AcquisitionState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AcquisitionErrorCode(str, Enum):
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    DATASET_INCOMPLETE = "DATASET_INCOMPLETE"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    JOB_LIMIT_REACHED = "JOB_LIMIT_REACHED"


@dataclass(frozen=True, slots=True)
class AcquisitionSpec:
    provider: str
    canonical_symbol: str
    provider_symbol: str
    timeframe: str
    requested_start: datetime
    requested_end: datetime
    requested_max_candles: int

    @property
    def identity(self) -> str:
        start = self.requested_start.astimezone(timezone.utc)
        end = self.requested_end.astimezone(timezone.utc)
        payload = {"provider": self.provider, "canonical_symbol": self.canonical_symbol,
            "provider_symbol": self.provider_symbol, "timeframe": self.timeframe,
            "start": start.isoformat(), "end": end.isoformat(),
            "max_candles": self.requested_max_candles}
        return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    cached_before: int
    stored_after: int
    inserted: int
    duplicates: int | None
    gap_count: int
    coverage_complete: bool
    first_timestamp: datetime | None
    last_timestamp: datetime | None
    dataset_hash: str | None
    volume_type: str | None
    volume_source: str | None
    provider_received: int | None = None
    provider_request_count: int = 0


@dataclass(frozen=True, slots=True)
class HistoricalAcquisitionJob:
    job_id: str
    request_identity: str
    spec: AcquisitionSpec
    state: AcquisitionState
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    outcome: AcquisitionOutcome | None = None
    error_code: AcquisitionErrorCode | None = None
    error_message: str | None = None


class AcquisitionFailure(Exception):
    """Safe job failure carrying truthful post-attempt cache state."""

    def __init__(self, code: AcquisitionErrorCode, message: str,
                 outcome: AcquisitionOutcome | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.outcome = outcome


class AcquisitionJobRegistry:
    """Ephemeral registry; CandleStore remains the durable authority."""
    def __init__(self, *, max_jobs: int = 32, max_concurrent: int = 2,
                 terminal_ttl: timedelta = timedelta(hours=1),
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.max_jobs, self.terminal_ttl, self.clock = max_jobs, terminal_ttl, clock
        self._jobs: OrderedDict[str, HistoricalAcquisitionJob] = OrderedDict()
        self._active_by_identity: dict[str, str] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def get(self, job_id: str) -> HistoricalAcquisitionJob | None:
        self._evict(); return self._jobs.get(job_id)

    def submit(self, spec: AcquisitionSpec, worker: Callable[[AcquisitionSpec], Awaitable[AcquisitionOutcome]],
               *, cached_outcome: AcquisitionOutcome | None = None) -> HistoricalAcquisitionJob:
        self._evict()
        active = self._active_by_identity.get(spec.identity)
        if active: return self._jobs[active]
        if len(self._jobs) >= self.max_jobs:
            terminal = next((key for key, value in self._jobs.items() if value.state in (AcquisitionState.COMPLETED, AcquisitionState.FAILED)), None)
            if terminal: self._jobs.pop(terminal)
            else: raise RuntimeError(AcquisitionErrorCode.JOB_LIMIT_REACHED.value)
        now = self.clock()
        job = HistoricalAcquisitionJob(uuid4().hex, spec.identity, spec,
            AcquisitionState.COMPLETED if cached_outcome else AcquisitionState.QUEUED, now,
            completed_at=now if cached_outcome else None, outcome=cached_outcome)
        self._jobs[job.job_id] = job
        if not cached_outcome:
            self._active_by_identity[spec.identity] = job.job_id
            asyncio.create_task(self._run(job.job_id, worker))
        return job

    async def _run(self, job_id: str, worker: Callable[[AcquisitionSpec], Awaitable[AcquisitionOutcome]]) -> None:
        async with self._semaphore:
            job = self._jobs[job_id]
            self._jobs[job_id] = replace(job, state=AcquisitionState.RUNNING, started_at=self.clock())
            try:
                outcome = await worker(job.spec)
                if not outcome.coverage_complete:
                    raise AcquisitionFailure(
                        AcquisitionErrorCode.DATASET_INCOMPLETE,
                        "Requested historical coverage remains incomplete; retry safely",
                        outcome,
                    )
                self._jobs[job_id] = replace(self._jobs[job_id], state=AcquisitionState.COMPLETED,
                    completed_at=self.clock(), outcome=outcome)
            except Exception as exc:
                text = str(exc)
                code = (exc.code if isinstance(exc, AcquisitionFailure)
                    else AcquisitionErrorCode.PROVIDER_TIMEOUT if "timed out" in text.lower()
                    else AcquisitionErrorCode.DATASET_INCOMPLETE if "incomplete" in text.lower()
                    else AcquisitionErrorCode.PROVIDER_RESPONSE_INVALID if "malformed" in text.lower()
                    else AcquisitionErrorCode.ACQUISITION_FAILED)
                partial = getattr(exc, "outcome", None)
                self._jobs[job_id] = replace(self._jobs[job_id], state=AcquisitionState.FAILED,
                    completed_at=self.clock(), outcome=partial, error_code=code,
                    error_message=(text[:240] if isinstance(exc, AcquisitionFailure)
                                   else "Public historical acquisition failed; retry the request"))
            finally:
                self._active_by_identity.pop(job.request_identity, None)

    def _evict(self) -> None:
        now = self.clock()
        expired = [key for key, job in self._jobs.items() if job.completed_at and now-job.completed_at > self.terminal_ttl]
        for key in expired: self._jobs.pop(key, None)
