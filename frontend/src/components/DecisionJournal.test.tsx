// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { DecisionJournal, DemoSupervisorBadge } from './DecisionJournal';
import { jqeApi } from '../services/api';
import type { ObservationHealthResponse, ResourceState } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('reuses heartbeat evidence across menu copies without journal requests or order authorization', async () => {
  const spy = vi.spyOn(jqeApi, 'getJournal').mockResolvedValue({ state: 'OBSERVED', items: [],
    supervisor: { state: 'STOPPED_OR_STALE', execution_enabled: false },
    analysis: { state: 'RUNNING', current_pairs: 4, total_pairs: 4 } });
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    const health = {data:{execution_supervisor:{state:'STOPPED', updated_at:new Date().toISOString(), stale:false, process_alive:false, cycle_number:4, max_age_seconds:10}}, stale:false, error:null} as ResourceState<ObservationHealthResponse>;
    await act(async () => root.render(<><DemoSupervisorBadge health={health} /><DemoSupervisorBadge health={health} /><DemoSupervisorBadge health={health} /></>));
    expect(host.textContent).toContain('Demo supervisor STOPPED');
    expect(host.textContent).toContain('no order authorization');
    expect(spy).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain('armed');
  } finally { await act(async () => root.unmount()); spy.mockRestore(); }
});

it('expires menu heartbeat evidence without fetching or changing order permissions', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-06T01:00:00Z'));
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    const health = {data:{execution_supervisor:{state:'RUNNING', updated_at:'2026-10-06T01:00:00Z', stale:false, process_alive:true, cycle_number:4, max_age_seconds:10}}, stale:false, error:null} as ResourceState<ObservationHealthResponse>;
    await act(async () => root.render(<DemoSupervisorBadge health={health} />));
    expect(host.textContent).toContain('RUNNING');
    await act(async () => vi.advanceTimersByTime(15000));
    expect(host.textContent).toContain('STALE');
    expect(host.textContent).not.toContain('armed');
  } finally { await act(async () => root.unmount()); vi.useRealTimers(); }
});

it('does not overlap slow journal reads', async () => {
  vi.useFakeTimers();
  let resolve!: (value: {state:string;items:[]}) => void;
  const spy = vi.spyOn(jqeApi, 'getJournal').mockImplementation(() => new Promise(done => {resolve = done;}));
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<DecisionJournal />));
    await act(async () => vi.advanceTimersByTime(45000));
    expect(spy).toHaveBeenCalledTimes(1);
    await act(async () => resolve({state:'OBSERVED',items:[]}));
    await act(async () => vi.advanceTimersByTime(15000));
    expect(spy).toHaveBeenCalledTimes(2);
  } finally { await act(async () => root.unmount()); spy.mockRestore(); vi.useRealTimers(); }
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
