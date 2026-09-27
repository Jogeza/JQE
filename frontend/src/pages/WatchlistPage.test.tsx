// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it } from 'vitest';
import { WatchlistPage } from './WatchlistPage';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const host = document.createElement('div');
document.body.append(host);
const root = createRoot(host);

afterEach(async () => {
  await act(async () => root.render(<></>));
});

it('offers only native Weltrade examples without claiming Telegram synchronization', async () => {
  await act(async () => root.render(<WatchlistPage watchlist={[]} capUsage={[]} loading={false} onRefresh={() => {}} />));
  const input = host.querySelector('input') as HTMLInputElement;
  expect(input.placeholder).toContain('FX Vol 20');
  expect(input.placeholder).not.toContain('R_75');
  expect(host.textContent).toContain('WELTRADE SYNTHETICS');
  expect(host.textContent).not.toContain('TELEGRAM SYNCED');
  expect(host.textContent).toContain('Add a Weltrade synthetic index above.');
});
