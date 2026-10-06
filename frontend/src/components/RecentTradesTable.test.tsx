// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { RecentTradesTable } from './RecentTradesTable';
import type { TradeHistoryDTO } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const trade = (id: string, close_time: string, profit: number): TradeHistoryDTO => ({
  id, symbol: 'FX Vol 20', side: 'BUY', volume: 0.1,
  open_price: 1000, close_price: 1001, profit,
  open_time: close_time, close_time, price_decimals: 2,
});

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

it('filters execution history to a selected UTC day with a clear control', async () => {
  const onClear = vi.fn();
  const trades = [trade('501', '2026-10-05T09:00:00Z', 12.5), trade('777', '2026-10-01T15:00:00Z', -7)];
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(
      <RecentTradesTable trades={trades} currency="USD" broker="weltrade" dayFilter="2026-10-05" onClearDayFilter={onClear} />));
    expect(host.textContent).toContain('#501');
    expect(host.textContent).not.toContain('#777');
    expect(host.textContent).toContain('Execution History (1 of 2)');
    expect(host.textContent).toContain('2026-10-05 UTC');
    await act(async () => { (host.querySelector('[aria-label="Clear day filter"]') as HTMLButtonElement).click(); });
    expect(onClear).toHaveBeenCalled();

    await act(async () => root.render(
      <RecentTradesTable trades={trades} currency="USD" broker="weltrade" dayFilter={null} onClearDayFilter={onClear} />));
    expect(host.textContent).toContain('#501');
    expect(host.textContent).toContain('#777');
    expect(host.textContent).toContain('Execution History (2)');

    await act(async () => root.render(
      <RecentTradesTable trades={trades} currency="USD" broker="weltrade" dayFilter="2026-10-07" onClearDayFilter={onClear} />));
    expect(host.textContent).toContain('NO CLOSED TRADES ON 2026-10-07 (UTC)');
  } finally { await act(async () => root.unmount()); }
});

it('reveals full UTC trade details when a row is clicked', async () => {
  const trades: TradeHistoryDTO[] = [{ id: '501', symbol: 'FX Vol 20', side: 'BUY', volume: 0.1,
    open_price: 1000, close_price: 1001, profit: 12.5,
    open_time: '2026-10-05T08:45:00Z', close_time: '2026-10-05T09:00:00Z', price_decimals: 2 }];
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<RecentTradesTable trades={trades} currency="USD" broker="weltrade" />));
    expect(host.textContent).not.toContain('2026-10-05 08:45:00 UTC');
    const row = host.querySelector('.trade-row') as HTMLElement;
    await act(async () => { row.click(); });
    expect(row.getAttribute('aria-expanded')).toBe('true');
    expect(host.textContent).toContain('2026-10-05 08:45:00 UTC');
    expect(host.textContent).toContain('2026-10-05 09:00:00 UTC');
    expect(host.textContent).toContain('+$12.50');
    await act(async () => { row.click(); });
    expect(row.getAttribute('aria-expanded')).toBe('false');
    expect(host.textContent).not.toContain('2026-10-05 08:45:00 UTC');
  } finally { await act(async () => root.unmount()); }
});
