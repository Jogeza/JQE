// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CandleItemDTO } from '../../types/api';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const chartMock = vi.hoisted(() => {
  const live = new Set<number>(); let nextId = 0;
  const remove = vi.fn(function (this: { id: number }) { live.delete(this.id); });
  const createChart = vi.fn(() => {
    const id = ++nextId; live.add(id);
    const series = () => ({ setData: vi.fn(), applyOptions: vi.fn(), priceScale: () => ({ applyOptions: vi.fn() }),
      createPriceLine: vi.fn(() => ({})), removePriceLine: vi.fn(), attachPrimitive: vi.fn(), detachPrimitive: vi.fn() });
    return { id, addSeries: vi.fn(series), remove: remove.bind({ id }), timeScale: () => ({ fitContent: vi.fn() }) };
  });
  return { live, createChart, remove, reset: () => { live.clear(); nextId = 0; createChart.mockClear(); remove.mockClear(); } };
});

vi.mock('lightweight-charts', () => ({ CandlestickSeries: 'candles', HistogramSeries: 'histogram', LineSeries: 'line',
  ColorType: { Solid: 'solid' }, CrosshairMode: { Normal: 0 }, LineStyle: { Dashed: 2 },
  createChart: chartMock.createChart, createSeriesMarkers: () => ({ setMarkers: vi.fn() }) }));

import { JQEChart } from './JQEChart';

const candle: CandleItemDTO = { time: '2026-01-01T00:00:00Z', open: 1, high: 2, low: .5, close: 1.5,
  volume: 10, EMA50: 1.2, EMA200: 1.1, RSI: 55, ATR: .2 };

describe('JQEChart public lifecycle', () => {
  let host: HTMLDivElement; let root: Root;
  beforeEach(() => { chartMock.reset(); host = document.createElement('div'); document.body.append(host); root = createRoot(host); });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); });

  it('creates one chart, updates replay and visibility without recreation, and removes it on unmount', async () => {
    await act(async () => root.render(<JQEChart symbol="XAUUSD" candles={[candle]} signal={null} />));
    expect(chartMock.createChart).toHaveBeenCalledTimes(1); expect(chartMock.live.size).toBe(1);
    await act(async () => root.render(<JQEChart symbol="XAUUSD" candles={[candle, { ...candle, time: '2026-01-01T00:15:00Z' }]} signal={null}
      indicators={{ ema50: false, ema200: true, rsi: false, volume: true }} />));
    expect(chartMock.createChart).toHaveBeenCalledTimes(1); expect(chartMock.live.size).toBe(1);
    await act(async () => root.unmount()); expect(chartMock.live.size).toBe(0);
    root = createRoot(host);
  });

  it('keeps exactly one or two live instances across repeated comparison cycles', async () => {
    const render = (comparison: boolean) => <><JQEChart key="primary" symbol="XAUUSD" candles={[candle]} signal={null} />
      {comparison && <JQEChart key="comparison" symbol="EURUSD" candles={[candle]} signal={null} />}</>;
    await act(async () => root.render(render(false))); expect(chartMock.live.size).toBe(1);
    await act(async () => root.render(render(true))); expect(chartMock.live.size).toBe(2);
    await act(async () => root.render(render(false))); expect(chartMock.live.size).toBe(1);
    await act(async () => root.render(render(true))); expect(chartMock.live.size).toBe(2);
    expect(chartMock.createChart).toHaveBeenCalledTimes(3);
  });

  it('changing only secondary identity preserves the primary chart', async () => {
    const render = (secondary: string) => <><JQEChart key="primary" symbol="XAUUSD" candles={[candle]} signal={null} />
      <JQEChart key={secondary} symbol={secondary} candles={[candle]} signal={null} /></>;
    await act(async () => root.render(render('EURUSD'))); expect(chartMock.createChart).toHaveBeenCalledTimes(2);
    await act(async () => root.render(render('GBPUSD'))); expect(chartMock.createChart).toHaveBeenCalledTimes(3); expect(chartMock.live.size).toBe(2);
  });
});
