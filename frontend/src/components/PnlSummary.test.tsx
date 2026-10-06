// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { PnlSummary } from './PnlSummary';
import type { TradeHistoryDTO } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const trade = (id: string, close_time: string, profit: number): TradeHistoryDTO => ({
  id, symbol: 'FX Vol 20', side: 'BUY', volume: 0.1,
  open_price: 1000, close_price: 1001, profit,
  open_time: close_time, close_time, price_decimals: 2,
});

it('summarizes window P&L, win rate and best/worst UTC days', async () => {
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<PnlSummary currency="USD" trades={[
      trade('1', '2026-10-05T09:00:00Z', 12.5),
      trade('2', '2026-10-05T11:30:00Z', -2.5),
      trade('3', '2026-10-01T15:00:00Z', -7),
      trade('4', '2026-09-30T23:00:00Z', 3),
    ]} />));
    const stats = [...host.querySelectorAll('.pnl-stat')];
    expect(stats).toHaveLength(4);
    expect(stats[0].textContent).toContain('+$6.00');
    expect(stats[0].querySelector('.pnl-stat-value')?.className).toContain('is-profit');
    expect(stats[0].textContent).toContain('4 closed executions');
    expect(stats[1].textContent).toContain('50%');
    expect(stats[1].textContent).toContain('2 wins · 2 losses');
    expect(stats[2].textContent).toContain('+$10.00');
    expect(stats[2].textContent).toContain('2026-10-05 (UTC)');
    expect(stats[3].textContent).toContain('-$7.00');
    expect(stats[3].textContent).toContain('2026-10-01 (UTC)');
    expect(host.textContent).toContain('30-DAY BROKER WINDOW (UTC)');
  } finally { await act(async () => root.unmount()); }
});

it('falls back to signed decimals without a currency and shows flat empty stats', async () => {
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<PnlSummary trades={[trade('1', '2026-10-05T09:00:00Z', -4.25)]} />));
    expect(host.textContent).toContain('-4.25');
    expect(host.textContent).not.toContain('$');
    expect(host.textContent).toContain('0%');

    await act(async () => root.render(<PnlSummary trades={[]} />));
    const values = [...host.querySelectorAll('.pnl-stat-value')];
    expect(values).toHaveLength(4);
    expect(values.every(value => value.textContent === '—')).toBe(true);
    expect(values.every(value => value.className.includes('is-flat'))).toBe(true);
    expect(host.textContent).toContain('0 closed executions');
    expect(host.textContent).toContain('no closed days');
  } finally { await act(async () => root.unmount()); }
});
