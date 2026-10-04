// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { ChartDrawingTools } from './ChartDrawingTools';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('anchors drawings to chart prices, reprojects after scaling, locks edits and isolates markets', async () => {
  vi.useFakeTimers();
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  let scale = 1;
  const timeScale = { width: () => 400, coordinateToTime: (x: number) => x + 1000, timeToCoordinate: (time: number) => (time - 1000) * scale,
    subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(), fitContent: vi.fn(), getVisibleLogicalRange: () => ({ from: 0, to: 100 }), setVisibleLogicalRange: vi.fn() };
  const chart = { timeScale: () => timeScale, panes: () => [{ getHeight: () => 300 }] } as unknown as IChartApi;
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
  } finally { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); }
});
