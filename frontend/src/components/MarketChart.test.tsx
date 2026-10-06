// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { CandleItemDTO } from '../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const captured = vi.hoisted(() => ({ latest: null as Record<string, unknown> | null }));
vi.mock('./chart/JQEChart', () => ({
  JQEChart: (props: Record<string, unknown>) => { captured.latest = props; return null; },
}));

import { MarketChart } from './MarketChart';

const candle: CandleItemDTO = { time: '2026-01-01T00:00:00Z', open: 1, high: 2, low: .5, close: 1.5, volume: 10, EMA50: 1.2, EMA200: 1.1, RSI: 55, ATR: .2 };

it('keeps prices on the right (no side toggle) and narrows the axis through the compact toggle', async () => {
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<MarketChart symbol="FX Vol 20" timeframe="M5" candles={[candle]} dataStatus="CURRENT" />));
    const toggle = () => host.querySelector('button.chart-density-toggle') as HTMLButtonElement;
    expect(toggle().textContent).toBe('Compact prices');
    expect(toggle().getAttribute('title')).toMatch(/narrower right price axis/i);
    expect(captured.latest?.compactPriceScale).toBe(false);
    expect(captured.latest).not.toHaveProperty('priceScaleSide');
    await act(async () => toggle().click());
    expect(captured.latest?.compactPriceScale).toBe(true);
    expect(toggle().textContent).toBe('Full prices');
    expect(toggle().getAttribute('aria-pressed')).toBe('true');
    await act(async () => toggle().click());
    expect(captured.latest?.compactPriceScale).toBe(false);
    expect(host.querySelectorAll('button')).toHaveLength(1);
  } finally { await act(async () => root.unmount()); host.remove(); }
});
