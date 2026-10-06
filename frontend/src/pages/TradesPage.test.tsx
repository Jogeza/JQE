// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { TradesPage } from './TradesPage';
import { jqeApi } from '../services/api';
import type { ExecutionStateResponse, TradeHistoryDTO } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const trade = (id: string, close_time: string, profit: number): TradeHistoryDTO => ({
  id, symbol: 'FX Vol 20', side: 'BUY', volume: 0.1,
  open_price: 1000, close_price: 1001, profit,
  open_time: close_time, close_time, price_decimals: 2,
});

it('filters execution history to the calendar day selected and clears it', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-06T12:00:00Z'));
  vi.spyOn(jqeApi, 'getJournal').mockResolvedValue({ state: 'OBSERVED', items: [] });
  const execution: ExecutionStateResponse = {
    broker: 'weltrade', connected: true, open_positions_count: 0, positions: [],
    recent_trades_count: 2,
    recent_trades: [trade('501', '2026-10-05T09:00:00Z', 12.5), trade('777', '2026-10-01T15:00:00Z', -7)],
    currency: 'USD',
  };
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<TradesPage execution={execution} loading={false} currency="USD" />));
    expect(host.textContent).toContain('#501');
    expect(host.textContent).toContain('#777');
    expect(host.textContent).toContain('Execution History (2)');

    await act(async () => {
      (host.querySelector('[aria-label^="5 October 2026"]') as HTMLElement).click();
    });
    expect(host.textContent).toContain('#501');
    expect(host.textContent).not.toContain('#777');
    expect(host.textContent).toContain('2026-10-05 UTC');
    expect(host.textContent).toContain('Execution History (1 of 2)');

    await act(async () => {
      (host.querySelector('[aria-label="Clear day filter"]') as HTMLButtonElement).click();
    });
    expect(host.textContent).toContain('#777');
    expect(host.textContent).toContain('Execution History (2)');
    expect(host.textContent).not.toContain('2026-10-05 UTC');
  } finally {
    await act(async () => root.unmount());
    vi.restoreAllMocks();
    vi.useRealTimers();
  }
});
