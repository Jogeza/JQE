// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { RecentTradesTable } from './RecentTradesTable';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('attributes trade history to the broker response and fails closed without it', async () => {
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<RecentTradesTable trades={[]} broker="weltrade" />));
  expect(host.textContent).toContain('WELTRADE MT5 HISTORY');
  await act(async () => root.render(<RecentTradesTable trades={[]} />));
  expect(host.textContent).toContain('BROKER SOURCE UNAVAILABLE');
  await act(async () => root.unmount());
  host.remove();
});
