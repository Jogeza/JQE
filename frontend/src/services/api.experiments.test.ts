import { afterEach, describe, expect, it, vi } from 'vitest';
import { jqeApi } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('experiment API client', () => {
  it('constructs supported filters and preserves false', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ experiments: [], issues: [], total: 0, limit: 25, offset: 0 }) });
    vi.stubGlobal('fetch', fetchMock);
    await jqeApi.listExperiments({ symbol: 'R_100', timeframe: undefined, fully_reproducible: false, dataset_hash: 'sha256:abc', offset: 0 });
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain('symbol=R_100');
    expect(url).toContain('fully_reproducible=false');
    expect(url).toContain('dataset_hash=sha256%3Aabc');
    expect(url).toContain('offset=0');
    expect(url).not.toContain('result_hash');
    expect(url).not.toContain('timeframe');
  });

  it('does not hide HTTP 422 validation details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, statusText: 'Unprocessable Entity', json: async () => ({ detail: 'invalid dataset hash' }) }));
    await expect(jqeApi.listExperiments({ dataset_hash: 'bad' })).rejects.toMatchObject({ status: 422, message: 'invalid dataset hash' });
  });
});
