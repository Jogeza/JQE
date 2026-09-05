import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from research.acquisitions import (
    AcquisitionErrorCode, AcquisitionFailure, AcquisitionJobRegistry,
    AcquisitionOutcome, AcquisitionSpec, AcquisitionState,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

def spec(symbol="XAUUSD", timeframe="M15"):
    return AcquisitionSpec("deriv", symbol, "frx" + symbol, timeframe, NOW,
                           NOW + timedelta(minutes=15 * 200), 201)

def outcome(*, complete=True, stored=201):
    return AcquisitionOutcome(0, stored, stored, 0, 0, complete, NOW,
                              NOW + timedelta(minutes=15 * 200), "sha256:test",
                              "UNAVAILABLE", "fixture", stored, 1)

async def settle(registry, job_id):
    for _ in range(100):
        job = registry.get(job_id)
        if job and job.state in (AcquisitionState.COMPLETED, AcquisitionState.FAILED):
            return job
        await asyncio.sleep(0)
    raise AssertionError("job did not settle")

@pytest.mark.asyncio
async def test_job_lifecycle_and_active_request_deduplication():
    gate = asyncio.Event()
    calls = 0
    async def worker(_):
        nonlocal calls
        calls += 1
        await gate.wait()
        return outcome()
    registry = AcquisitionJobRegistry()
    first = registry.submit(spec(), worker)
    second = registry.submit(spec(), worker)
    assert first.job_id == second.job_id
    await asyncio.sleep(0)
    assert registry.get(first.job_id).state == AcquisitionState.RUNNING
    gate.set()
    final = await settle(registry, first.job_id)
    assert final.state == AcquisitionState.COMPLETED
    assert final.outcome.coverage_complete
    assert calls == 1

@pytest.mark.asyncio
async def test_cached_request_completes_without_worker_or_task():
    async def worker(_):
        raise AssertionError("fully cached request must not run provider")
    registry = AcquisitionJobRegistry()
    job = registry.submit(spec(), worker, cached_outcome=replace(outcome(), provider_request_count=0,
                                                                 provider_received=0, inserted=0))
    assert job.state == AcquisitionState.COMPLETED
    assert job.started_at is None
    assert job.outcome.provider_request_count == 0

@pytest.mark.asyncio
async def test_failure_preserves_partial_truth_and_allows_retry():
    partial = replace(outcome(complete=False, stored=80), gap_count=2, provider_received=None,
                      duplicates=None)
    async def worker(_):
        raise AcquisitionFailure(AcquisitionErrorCode.DATASET_INCOMPLETE,
                                 "Provider returned incomplete coverage; retry safely", partial)
    registry = AcquisitionJobRegistry()
    failed = await settle(registry, registry.submit(spec(), worker).job_id)
    assert failed.state == AcquisitionState.FAILED
    assert failed.error_code == AcquisitionErrorCode.DATASET_INCOMPLETE
    assert failed.outcome.stored_after == 80
    retry = registry.submit(spec(), worker)
    assert retry.job_id != failed.job_id
    await settle(registry, retry.job_id)

@pytest.mark.asyncio
async def test_concurrency_is_bounded_and_identities_are_isolated():
    gate = asyncio.Event()
    running = peak = 0
    async def worker(_):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await gate.wait()
        running -= 1
        return outcome()
    registry = AcquisitionJobRegistry(max_concurrent=2)
    jobs = [registry.submit(spec(f"S{i}"), worker) for i in range(3)]
    await asyncio.sleep(0); await asyncio.sleep(0)
    assert peak == 2
    assert len({job.request_identity for job in jobs}) == 3
    gate.set()
    await asyncio.gather(*(settle(registry, job.job_id) for job in jobs))

def test_terminal_ttl_and_bounded_registry_eviction():
    current = NOW
    def clock(): return current
    registry = AcquisitionJobRegistry(max_jobs=1, terminal_ttl=timedelta(seconds=10), clock=clock)
    async def worker(_): return outcome()
    cached = replace(outcome(), provider_request_count=0, provider_received=0, inserted=0)
    first = registry.submit(spec(), worker, cached_outcome=cached)
    second = registry.submit(spec("EURUSD"), worker, cached_outcome=cached)
    assert registry.get(first.job_id) is None
    current += timedelta(seconds=11)
    assert registry.get(second.job_id) is None
