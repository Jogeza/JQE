// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { WatchlistPage } from './WatchlistPage';
import type { WatchlistItemDTO, WatchlistCapUsageDTO } from '../types/api';
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it.each(['STALE', 'UNAVAILABLE'] as const)('never displays remaining cap slots for %s evidence', async state => {
  const host = document.createElement('div'); const root = createRoot(host);
  const item = { symbol: 'FX Vol 20', timeframe: 'M5', scope: 'FX Vol 20:M5' } as WatchlistItemDTO;
  const cap = { symbol: 'FX Vol 20', daily_count: 0, daily_limit: 20 } as WatchlistCapUsageDTO;
  try {
    await act(async () => root.render(<WatchlistPage watchlist={[item]} capUsage={[cap]} capEvidenceState={state} loading={false} onRefresh={() => {}} />));
    expect(host.textContent).toContain('remaining capacity unknown');
    expect(host.textContent).not.toContain('cap slots remaining');
    expect(host.textContent).not.toContain('0 / 20');
    expect(host.textContent).toContain('does not authorize orders');
  } finally { await act(async () => root.unmount()); }
});
