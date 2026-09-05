import React, { useEffect, useRef } from 'react';
import {
  CandlestickSeries, ColorType, CrosshairMode, createChart, createSeriesMarkers,
  HistogramSeries, LineSeries, LineStyle, type IChartApi, type IPriceLine,
  type ISeriesApi, type ISeriesMarkersPluginApi, type SeriesMarker, type Time,
} from 'lightweight-charts';
import type { CandleItemDTO, SignalResponse } from '../../types/api';
import { adaptCandles, adaptSignal, toCandlestickData, toLineData, toSignalMarkers, toVolumeData } from './chartAdapters';
import { adaptVolumeProfile, VolumeProfilePrimitive } from './volumeProfilePrimitive';
import type { VolumeProfileSnapshotDTO } from '../../types/research';

export interface IndicatorVisibility { ema50: boolean; ema200: boolean; rsi: boolean; volume: boolean; }
interface JQEChartProps { symbol: string; candles: CandleItemDTO[]; signal: SignalResponse | null; markers?: SeriesMarker<Time>[]; priceDecimals?: number; volumeProfile?: VolumeProfileSnapshotDTO | null; indicators?: IndicatorVisibility; height?: number; }
interface ChartHandles {
  chart: IChartApi; candles: ISeriesApi<'Candlestick'>; ema50: ISeriesApi<'Line'>;
  ema200: ISeriesApi<'Line'>; rsi: ISeriesApi<'Line'>; volume: ISeriesApi<'Histogram'>;
  markers: ISeriesMarkersPluginApi<Time>; priceLines: IPriceLine[];
  volumeProfile: VolumeProfilePrimitive | null;
}

export const JQEChart: React.FC<JQEChartProps> = ({ symbol, candles, signal, markers = [], priceDecimals = 5, volumeProfile = null,
  indicators = { ema50: true, ema200: true, rsi: true, volume: true }, height = 460 }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const handlesRef = useRef<ChartHandles | null>(null);
  const hasFitContentRef = useRef(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      autoSize: true, height,
      layout: { background: { type: ColorType.Solid, color: '#07080a' }, textColor: '#7f8996', fontFamily: 'monospace', attributionLogo: true, panes: { separatorColor: '#232830', separatorHoverColor: '#343b46', enableResize: true } },
      grid: { vertLines: { color: 'rgba(255,255,255,0.035)' }, horzLines: { color: 'rgba(255,255,255,0.05)' } },
      crosshair: { mode: CrosshairMode.Normal }, rightPriceScale: { borderColor: '#232830' },
      timeScale: { borderColor: '#232830', timeVisible: true, secondsVisible: false },
      localization: { priceFormatter: (price: number) => price.toFixed(priceDecimals) },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#00e676', downColor: '#ff5252', borderVisible: false, wickUpColor: '#00e676', wickDownColor: '#ff5252',
      priceFormat: { type: 'price', precision: priceDecimals, minMove: 10 ** -priceDecimals },
    });
    const volumeSeries = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '', lastValueVisible: false, priceLineVisible: false });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    const ema50Series = chart.addSeries(LineSeries, { color: '#00bcd4', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const ema200Series = chart.addSeries(LineSeries, { color: '#a775ff', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const rsiSeries = chart.addSeries(LineSeries, { color: '#ffab00', lineWidth: 1, priceLineVisible: false, priceFormat: { type: 'price', precision: 1, minMove: 0.1 } }, 1);
    rsiSeries.createPriceLine({ price: 70, color: 'rgba(255,171,0,0.35)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '70' });
    rsiSeries.createPriceLine({ price: 30, color: 'rgba(255,171,0,0.35)', lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '30' });
    const markers = createSeriesMarkers(candleSeries, []);
    handlesRef.current = { chart, candles: candleSeries, ema50: ema50Series, ema200: ema200Series, rsi: rsiSeries, volume: volumeSeries, markers, priceLines: [], volumeProfile: null };
    return () => { handlesRef.current = null; hasFitContentRef.current = false; chart.remove(); };
  }, [priceDecimals, height]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    handles.ema50.applyOptions({ visible: indicators.ema50 });
    handles.ema200.applyOptions({ visible: indicators.ema200 });
    handles.rsi.applyOptions({ visible: indicators.rsi });
    handles.volume.applyOptions({ visible: indicators.volume });
  }, [indicators.ema50, indicators.ema200, indicators.rsi, indicators.volume]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    const adapted = adaptCandles(candles);
    handles.candles.setData(toCandlestickData(adapted)); handles.volume.setData(toVolumeData(adapted));
    handles.ema50.setData(toLineData(adapted, 'ema50')); handles.ema200.setData(toLineData(adapted, 'ema200'));
    handles.rsi.setData(toLineData(adapted, 'rsi'));
    const annotation = adaptSignal(signal, symbol);
    handles.markers.setMarkers([...markers, ...toSignalMarkers(annotation, adapted.length > 0 ? adapted[adapted.length - 1].time : null)]);
    handles.priceLines.forEach((line) => handles.candles.removePriceLine(line));
    handles.priceLines = [];
    if (annotation) {
      [{ price: annotation.entry, color: '#00bcd4', title: 'ENTRY' }, { price: annotation.stopLoss, color: '#ff5252', title: 'SL' }, { price: annotation.takeProfit, color: '#00e676', title: 'TP' }]
        .forEach(({ price, color, title }) => { if (price !== null) handles.priceLines.push(handles.candles.createPriceLine({ price, color, title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true })); });
    }
    if (!hasFitContentRef.current && adapted.length > 0) { handles.chart.timeScale().fitContent(); hasFitContentRef.current = true; }
  }, [candles, signal, markers, symbol]);

  useEffect(() => {
    const handles = handlesRef.current;
    if (!handles) return;
    if (handles.volumeProfile) handles.candles.detachPrimitive(handles.volumeProfile);
    handles.volumeProfile = volumeProfile ? new VolumeProfilePrimitive(adaptVolumeProfile(volumeProfile)) : null;
    if (handles.volumeProfile) handles.candles.attachPrimitive(handles.volumeProfile);
  }, [volumeProfile]);

  return <div ref={containerRef} style={{ width: '100%', height: `${height}px`, backgroundColor: '#07080a' }} aria-label={`${symbol} candlestick chart`} />;
};
