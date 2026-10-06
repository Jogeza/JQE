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
    expect(host.querySelectorAll('button')).toHaveLength(3);
    expect(host.querySelector('button.chart-fullscreen-toggle')).not.toBeNull();
    expect(host.querySelector('button.chart-indicator-toggle')).not.toBeNull();
  } finally { await act(async () => root.unmount()); host.remove(); }
});

it('lets the user choose synthetic-index chart indicators from a picker', async () => {
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<MarketChart symbol="FX Vol 20" timeframe="M5" candles={[candle]} dataStatus="CURRENT" />));
    expect(captured.latest?.indicators).toEqual({ ema50: true, ema200: true, rsi: false, volume: false });
    await act(async () => (host.querySelector('button.chart-indicator-toggle') as HTMLButtonElement).click());
    const boxes = () => Array.from(host.querySelectorAll('.chart-indicator-popover input')) as HTMLInputElement[];
    expect(boxes().map(box => box.checked)).toEqual([true, true, false, false]);
    await act(async () => boxes()[2].click());
    expect(captured.latest?.indicators).toEqual({ ema50: true, ema200: true, rsi: true, volume: false });
    await act(async () => boxes()[3].click());
    expect(captured.latest?.indicators).toEqual({ ema50: true, ema200: true, rsi: true, volume: true });
    await act(async () => boxes()[0].click());
    expect(captured.latest?.indicators).toEqual({ ema50: false, ema200: true, rsi: true, volume: true });
  } finally { await act(async () => root.unmount()); host.remove(); }
});

it('hides the picker and honours caller-controlled indicators', async () => {
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<MarketChart symbol="FX Vol 20" timeframe="M5" candles={[candle]} dataStatus="CURRENT"
      indicators={{ ema50: true, ema200: true, rsi: true, volume: false }} />));
    expect(host.querySelector('button.chart-indicator-toggle')).toBeNull();
    expect(captured.latest?.indicators).toEqual({ ema50: true, ema200: true, rsi: true, volume: false });
  } finally { await act(async () => root.unmount()); host.remove(); }
});

it('toggles a fullscreen overlay with an accessible exit and body scroll lock', async () => {
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<MarketChart symbol="FX Vol 20" timeframe="M5" candles={[candle]} dataStatus="CURRENT" />));
    const panel = () => host.querySelector('.chart-panel') as HTMLElement;
    const toggle = () => host.querySelector('button.chart-fullscreen-toggle') as HTMLButtonElement;
    expect(panel().className).not.toContain('is-fullscreen');
    expect(toggle().getAttribute('aria-label')).toBe('Fullscreen chart');
    expect(captured.latest?.fill).toBe(false);

    await act(async () => toggle().click());
    expect(panel().className).toContain('is-fullscreen');
    expect(captured.latest?.fill).toBe(true);
    expect(toggle().getAttribute('aria-label')).toBe('Exit fullscreen chart');
    expect(toggle().getAttribute('aria-pressed')).toBe('true');
    expect(document.body.classList.contains('chart-fullscreen-lock')).toBe(true);

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(panel().className).not.toContain('is-fullscreen');
    expect(captured.latest?.fill).toBe(false);
    expect(document.body.classList.contains('chart-fullscreen-lock')).toBe(false);
  } finally { await act(async () => root.unmount()); host.remove(); }
});

it('renders header controls, source label, empty message, and a fullscreen-only overlay', async () => {
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => root.render(<MarketChart symbol="FX Vol 20" timeframe="M5" candles={[]}
      symbolControls={<button type="button" className="probe-control">CTRL</button>}
      sourceLabel="Weltrade · live" emptyMessage="No market snapshot. See Notifications."
      overlay={<aside className="probe-overlay">DECISION</aside>} />));
    const panel = () => host.querySelector('.chart-panel') as HTMLElement;
    expect(panel().querySelector('.quant-panel-title .probe-control')).not.toBeNull();
    expect(panel().textContent).not.toContain('FX Vol 20 / M5');
    expect(panel().querySelector('.chart-source-label')?.textContent).toBe('Weltrade · live');
    expect(panel().querySelector('.chart-empty-state')?.textContent).toContain('No market snapshot. See Notifications.');
    expect(panel().querySelector('.chart-overlay')).toBeNull();

    await act(async () => (host.querySelector('button.chart-fullscreen-toggle') as HTMLButtonElement).click());
    expect(panel().querySelector('.chart-overlay')?.textContent).toContain('DECISION');

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(panel().querySelector('.chart-overlay')).toBeNull();
  } finally { await act(async () => root.unmount()); host.remove(); }
});
