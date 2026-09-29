// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { NotificationCenter } from './NotificationCenter';
import type { ResourceState } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const unavailable = <T,>(): ResourceState<T> => ({ data: null, error: null, loading: false, stale: false, lastUpdated: null });

it('keeps all four status facts visible when evidence is unavailable and closes with Escape', async () => {
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<NotificationCenter broker={unavailable()} safety={unavailable()} market={unavailable()} notifications={unavailable()} apiError={null} />));
    await act(async () => (host.querySelector('.notification-trigger') as HTMLButtonElement).click());
    const panel = host.querySelector('[role="dialog"]');
    expect(panel).not.toBeNull();
    expect(Array.from(panel!.querySelectorAll('dt')).map(item => item.textContent)).toEqual(['Live broker connection', 'Demo verified', 'Market data freshness', 'Broker execution']);
    expect(panel!.textContent).toContain('Unverified');
    expect(panel!.textContent).toContain('Execution remains blocked');
    expect(panel!.textContent).not.toContain('Yes - live');
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(host.querySelector('.notification-trigger'));
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
