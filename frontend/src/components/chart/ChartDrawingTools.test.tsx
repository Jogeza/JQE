// @vitest-environment happy-dom
import { act, StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { ChartDrawingTools } from './ChartDrawingTools';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('anchors drawings to chart prices, reprojects after scaling, locks edits and isolates markets', async () => {
  vi.useFakeTimers();
  sessionStorage.clear();
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  let scale = 1;
  const timeScale = { width: () => 400, coordinateToTime: (x: number) => x + 1000, timeToCoordinate: (time: number) => (time - 1000) * scale,
    subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(), fitContent: vi.fn(), getVisibleLogicalRange: () => ({ from: 0, to: 100 }), setVisibleLogicalRange: vi.fn() };
  const chart = { priceScale: () => ({width: () => 58}), timeScale: () => timeScale, panes: () => [{ getHeight: () => 300 }] } as unknown as IChartApi;
  const series = { coordinateToPrice: (y: number) => 100 - y / 10, priceToCoordinate: (price: number) => (100 - price) * 10 * scale } as unknown as ISeriesApi<'Candlestick'>;
  const button = (label: string) => host.querySelector(`button[aria-label="${label}"]`) as HTMLButtonElement;
  try {
    await act(async () => root.render(<ChartDrawingTools chart={chart} series={series} scope="FX20:M5" decimals={2} />));
    await act(async () => button('Rectangle').click());
    const svg = host.querySelector('svg.chart-drawing-overlay') as SVGSVGElement;
    svg.setPointerCapture = vi.fn();
    await act(async () => svg.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 20, clientY: 30, pointerId: 1 })));
    await act(async () => svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 60, clientY: 80, pointerId: 1 })));
    await act(async () => svg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 1 })));
    expect(svg.querySelector('rect')?.getAttribute('width')).toBe('40');
    scale = 2; await act(async () => vi.advanceTimersByTime(200));
    expect(svg.querySelector('rect')?.getAttribute('width')).toBe('80');
    await act(async () => button('Lock drawings').click());
    expect(button('Clear drawings').disabled).toBe(true);
    await act(async () => root.render(<ChartDrawingTools chart={chart} series={series} scope="FX40:M5" decimals={2} />));
    expect(svg.querySelector('rect')).toBeNull();
    await act(async () => root.render(<ChartDrawingTools chart={chart} series={series} scope="FX20:M5" decimals={2} />));
    expect(svg.querySelector('rect')?.getAttribute('width')).toBe('80');
    expect(button('Clear drawings').disabled).toBe(false);
    await act(async () => root.render(<ChartDrawingTools key="reload" chart={chart} series={series} scope="FX20:M5" decimals={2} />));
    expect(host.querySelector('svg.chart-drawing-overlay rect')).not.toBeNull();
    await act(async () => button('Clear drawings').click());
    expect(host.querySelector('svg.chart-drawing-overlay rect')).toBeNull();
  } finally { await act(async () => root.unmount()); host.remove(); sessionStorage.clear(); vi.useRealTimers(); }
});

it('keeps a stored market when a mount is torn down before its restore render settles', async () => {
  vi.useFakeTimers();
  sessionStorage.clear();
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const timeScale = { width: () => 400, coordinateToTime: (x: number) => x + 1000, timeToCoordinate: (time: number) => time - 1000,
    subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(), fitContent: vi.fn(), getVisibleLogicalRange: () => ({ from: 0, to: 100 }), setVisibleLogicalRange: vi.fn() };
  const chart = { priceScale: () => ({width: () => 58}), timeScale: () => timeScale, panes: () => [{ getHeight: () => 300 }] } as unknown as IChartApi;
  const series = { coordinateToPrice: (y: number) => 100 - y / 10, priceToCoordinate: (price: number) => (100 - price) * 10 } as unknown as ISeriesApi<'Candlestick'>;
  const storageKey = 'jqe:drawings:v1:weltrade:FX20:M5';
  sessionStorage.setItem(storageKey, JSON.stringify([{ id: 4, tool: 'line', a: { time: 1100, price: 90 }, b: { time: 1200, price: 80 }, color: '#38bdf8', text: 'Note' }]));
  try {
    await act(async () => root.render(
      <StrictMode><ChartDrawingTools chart={chart} series={series} scope="FX20:M5" decimals={2} /></StrictMode>
    ));
    expect(host.textContent).toContain('1 drawings');
    expect(host.querySelector('svg.chart-drawing-overlay line')).not.toBeNull();
    expect(sessionStorage.getItem(storageKey)).not.toBeNull();
  } finally { await act(async () => root.unmount()); host.remove(); sessionStorage.clear(); vi.useRealTimers(); }
});

it('selects a stored drawing from cursor mode, drags it by body and endpoints, then deletes it', async () => {
  vi.useFakeTimers();
  sessionStorage.clear();
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  const timeScale = { width: () => 400, coordinateToTime: (x: number) => x + 1000, timeToCoordinate: (time: number) => time - 1000,
    subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(), fitContent: vi.fn(), getVisibleLogicalRange: () => ({ from: 0, to: 100 }), setVisibleLogicalRange: vi.fn() };
  const chart = { priceScale: () => ({width: () => 58}), timeScale: () => timeScale, panes: () => [{ getHeight: () => 300 }] } as unknown as IChartApi;
  const series = { coordinateToPrice: (y: number) => 100 - y / 10, priceToCoordinate: (price: number) => (100 - price) * 10 } as unknown as ISeriesApi<'Candlestick'>;
  const storageKey = 'jqe:drawings:v1:weltrade:FX20:M5';
  sessionStorage.setItem(storageKey, JSON.stringify([{ id: 4, tool: 'line', a: { time: 1100, price: 90 }, b: { time: 1200, price: 80 }, color: '#38bdf8', text: 'Note' }]));
  try {
    await act(async () => root.render(<ChartDrawingTools chart={chart} series={series} scope="FX20:M5" decimals={2} />));
    const svg = host.querySelector('svg.chart-drawing-overlay') as SVGSVGElement;
    svg.setPointerCapture = vi.fn();
    const group = svg.querySelector('[data-drawing-id="4"]') as SVGGElement;
    expect(group).not.toBeNull();
    await act(async () => group.querySelector('line')!.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 100, clientY: 100, pointerId: 2 })));
    expect(host.textContent).toContain('Selected · drag to move');
    expect(group.querySelectorAll('circle').length).toBeGreaterThanOrEqual(4);
    await act(async () => svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 120, clientY: 90, pointerId: 2 })));
    await act(async () => svg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: 120, clientY: 90, pointerId: 2 })));
    const line = group.querySelector('line') as SVGLineElement;
    expect(line.getAttribute('x1')).toBe('120');
    expect(line.getAttribute('y1')).toBe('90');
    await act(async () => group.querySelectorAll('circle')[0].dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, clientX: 120, clientY: 90, pointerId: 3 })));
    await act(async () => svg.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, clientX: 140, clientY: 90, pointerId: 3 })));
    await act(async () => svg.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 3 })));
    expect(line.getAttribute('x1')).toBe('140');
    expect(line.getAttribute('y1')).toBe('90');
    expect(line.getAttribute('x2')).toBe('220');
    await act(async () => (host.querySelector('button[aria-label="Delete selected drawing"]') as HTMLButtonElement).click());
    expect(svg.querySelector('[data-drawing-id="4"]')).toBeNull();
    expect(host.textContent).toContain('0 drawings');
    expect(sessionStorage.getItem(storageKey)).toBeNull();
  } finally { await act(async () => root.unmount()); host.remove(); sessionStorage.clear(); vi.useRealTimers(); }
});
