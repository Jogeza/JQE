// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { TradeCalendar } from './TradeCalendar';
import type { TradeHistoryDTO } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const trade = (id: string, close_time: string, profit: number): TradeHistoryDTO => ({
  id, symbol: 'FX Vol 20', side: 'BUY', volume: 0.1,
  open_price: 1000, close_price: 1001, profit,
  open_time: close_time, close_time, price_decimals: 2,
});

it('aggregates daily realized P&L in UTC and ignores invalid dates', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-06T12:00:00Z'));
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<TradeCalendar currency="USD" trades={[
      trade('1', '2026-10-05T09:00:00Z', 12.5),
      trade('2', '2026-10-05T11:30:00Z', -2.5),
      trade('3', '2026-10-01T15:00:00Z', -7),
      trade('4', '2026-09-30T23:00:00Z', 3),
      trade('5', 'not-a-date', 99),
    ]} />));
    expect(host.textContent).toContain('October 2026');
    const cells = host.querySelectorAll('.trade-calendar-cell');
    expect(cells[3].className).toContain('has-loss');
    expect(cells[3].textContent).toContain('-$7.00');
    expect(cells[7].className).toContain('has-profit');
    expect(cells[7].textContent).toContain('+$10.00');
    expect(cells[8].className).toContain('is-today');
    expect(host.textContent).toContain('+$3.00');
    expect(host.textContent).toContain('3 closed trades · broker close date (UTC)');
    expect(host.textContent).not.toContain('99');

    await act(async () => {
      (host.querySelector('[aria-label="Previous month"]') as HTMLButtonElement).click();
    });
    expect(host.textContent).toContain('September 2026');
    const sepCells = host.querySelectorAll('.trade-calendar-cell');
    expect(sepCells[30].className).toContain('has-profit');
    expect(sepCells[30].textContent).toContain('+$3.00');
    expect(sepCells[7].className).not.toContain('has-trades');
    expect(host.textContent).toContain('1 closed trade · broker close date (UTC)');
  } finally { await act(async () => root.unmount()); vi.useRealTimers(); }
});

it('renders a flat fallback without currency and an honest empty month', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-06T12:00:00Z'));
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    await act(async () => root.render(<TradeCalendar trades={[
      trade('1', '2026-10-06T10:00:00Z', 5),
    ]} />));
    expect(host.textContent).toContain('October 2026');
    expect(host.textContent).toContain('+5.00');
    expect(host.textContent).not.toContain('$');

    await act(async () => root.render(<TradeCalendar trades={[]} />));
    expect(host.textContent).toContain('October 2026');
    expect(host.textContent).toContain('—');
    expect(host.textContent).toContain('No closed trades recorded for this month');
    expect(host.textContent).not.toContain('+5.00');
  } finally { await act(async () => root.unmount()); vi.useRealTimers(); }
});

it('exposes keyboard-accessible day selection only for days with trades', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-06T12:00:00Z'));
  const onSelectDay = vi.fn();
  const trades = [trade('1', '2026-10-05T09:00:00Z', 12.5)];
  const host = document.createElement('div'); const root = createRoot(host);
  try {
    const render = (selectedDay: string | null) => root.render(
      <TradeCalendar currency="USD" trades={trades} selectedDay={selectedDay} onSelectDay={onSelectDay} />);

    await act(async () => render(null));
    const buttons = host.querySelectorAll('[role="button"]');
    expect(buttons).toHaveLength(1);
    expect(buttons[0].getAttribute('aria-label')).toBe('5 October 2026: 1 closed trade, +$12.50');
    expect(host.textContent).toContain('Select a day to filter execution history');

    await act(async () => { (buttons[0] as HTMLElement).click(); });
    expect(onSelectDay).toHaveBeenCalledWith('2026-10-05');

    await act(async () => render('2026-10-05'));
    const selected = host.querySelector('[role="button"]') as HTMLElement;
    expect(selected.className).toContain('is-selected');
    expect(selected.getAttribute('aria-pressed')).toBe('true');
    await act(async () => { selected.click(); });
    expect(onSelectDay).toHaveBeenLastCalledWith(null);

    await act(async () => render(null));
    const cell = host.querySelector('[role="button"]') as HTMLElement;
    await act(async () => {
      cell.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    expect(onSelectDay).toHaveBeenLastCalledWith('2026-10-05');
  } finally { await act(async () => root.unmount()); vi.useRealTimers(); }
});
