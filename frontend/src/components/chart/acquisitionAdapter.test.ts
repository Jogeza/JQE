import { describe, expect, it } from 'vitest';
import { acquisitionSelectionKey, isTerminalAcquisition, jobSelectionKey } from './acquisitionAdapter';
import type { HistoricalAcquisitionJobDTO } from '../../types/research';

const job = (state: HistoricalAcquisitionJobDTO['state']): HistoricalAcquisitionJobDTO => ({
  job_id: '1', request_identity: 'sha256:x', state, created_at: '2026-01-01T00:00:00Z',
  spec: { provider: 'deriv', provider_symbol: 'frxXAUUSD', canonical_symbol: 'XAUUSD',
    timeframe: 'M15', requested_start: '2026-01-01T00:00:00Z',
    requested_end: '2026-01-04T03:00:00Z', requested_max_candles: 301 },
});

describe('acquisition adapter', () => {
  it.each(['QUEUED', 'RUNNING'] as const)('keeps %s active', state => expect(isTerminalAcquisition(job(state))).toBe(false));
  it.each(['COMPLETED', 'FAILED'] as const)('recognizes %s as terminal', state => expect(isTerminalAcquisition(job(state))).toBe(true));
  it('isolates jobs from a newly selected identity', () => {
    expect(jobSelectionKey(job('RUNNING'))).toBe(acquisitionSelectionKey('deriv', 'frxXAUUSD', 'XAUUSD', 'M15'));
    expect(jobSelectionKey(job('RUNNING'))).not.toBe(acquisitionSelectionKey('deriv', 'R_100', 'R_100', 'M15'));
  });
});
