// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { DecisionJournal, DemoSupervisorBadge } from './DecisionJournal';
import { jqeApi } from '../services/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('keeps fresh analysis distinct from a stopped demo supervisor', async () => {
  const spy = vi.spyOn(jqeApi, 'getJournal').mockResolvedValue({ state: 'OBSERVED', items: [],
    supervisor: { state: 'STOPPED_OR_STALE', execution_enabled: false },
    analysis: { state: 'RUNNING', current_pairs: 4, total_pairs: 4 } });
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<DemoSupervisorBadge />));
    expect(host.textContent).toContain('watching 4/4 fresh pairs');
    expect(host.textContent).toContain('Demo supervisor stopped or stale');
    expect(host.textContent).not.toContain('armed');
  } finally { await act(async () => root.unmount()); spy.mockRestore(); }
});

it('shows decision reasons in UTC and reports a separately armed supervisor', async () => {
  const spy = vi.spyOn(jqeApi, 'getJournal').mockResolvedValue({ state: 'OBSERVED',
    supervisor: { state: 'RUNNING', execution_enabled: true, cycle_number: 2 },
    items: [{ id: 1, observed_at: '2026-10-04T17:15:00Z', symbol: 'FX Vol 20', timeframe: 'M5',
      stage: 'DECISION', facts: { status: 'NO_TRADE', decision_code: 'NO_TRADE_SIGNAL' } }] });
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<DecisionJournal />));
    expect(host.textContent).toContain('NO_TRADE_SIGNAL');
    expect(host.textContent).toContain('2026-10-04 17:15:00 UTC');
    expect(host.textContent).toContain('armed · guarded demo');
  } finally { await act(async () => root.unmount()); spy.mockRestore(); }
});

it('routes transport errors to Notifications and never claims an armed process', async () => {
  const spy = vi.spyOn(jqeApi, 'getJournal').mockRejectedValue(new Error('offline'));
  const receive = vi.fn(); window.addEventListener('jqe:notification', receive);
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<><DecisionJournal /><DemoSupervisorBadge /></>));
    expect(receive).toHaveBeenCalled();
    expect((receive.mock.calls[0][0] as CustomEvent).detail.detail).toContain('evidence unavailable');
    expect(host.textContent).toContain('Demo supervisor unavailable');
    expect(host.textContent).not.toContain('armed · guarded demo');
  } finally {
    await act(async () => root.unmount()); spy.mockRestore();
    window.removeEventListener('jqe:notification', receive);
  }
});
