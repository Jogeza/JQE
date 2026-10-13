// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { PositionsTable } from './PositionsTable';
import type { PositionDTO } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('reveals exact broker quantity and stop/target evidence by keyboard without order controls', async () => {
  const host = document.createElement('div'); const root = createRoot(host);
  const position = { id: '42', symbol: 'FX Vol 20', side: 'BUY', volume: 0.02,
    open_price: 100, current_price: 101, stop_loss: 95, take_profit: null,
    profit: 2, price_decimals: 2 } as PositionDTO;
  try {
    await act(async () => root.render(<PositionsTable positions={[position]} currency="USD" />));
    const row = host.querySelector('.position-row') as HTMLElement;
    expect(row.getAttribute('aria-expanded')).toBe('false');
    await act(async () => row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
    expect(row.getAttribute('aria-expanded')).toBe('true');
    const details = host.querySelector('.position-detail-row')!;
    expect(details.textContent).toContain('Volume0.02');
    expect(details.textContent).toContain('Stop loss95.00');
    expect(details.textContent).toContain('Take profit—');
    expect(host.querySelector('button')).toBeNull();
  } finally { await act(async () => root.unmount()); }
});
