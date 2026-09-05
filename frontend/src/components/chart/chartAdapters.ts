import type { CandlestickData, HistogramData, LineData, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts';
import type { CandleItemDTO, SignalResponse } from '../../types/api';
import type { JQEChartAnnotation, JQEChartCandle } from './chartTypes';

const finiteOrNull = (value: number | null): number | null =>
  value !== null && Number.isFinite(value) ? value : null;

const toUtcTimestamp = (value: string): UTCTimestamp | null => {
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) ? Math.floor(milliseconds / 1000) as UTCTimestamp : null;
};

export function adaptCandles(candles: CandleItemDTO[]): JQEChartCandle[] {
  const byTimestamp = new Map<number, JQEChartCandle>();
  candles.forEach((candle) => {
    const time = toUtcTimestamp(candle.time);
    if (time === null || ![candle.open, candle.high, candle.low, candle.close].every(Number.isFinite)) return;
    byTimestamp.set(time, {
      time, open: candle.open, high: candle.high, low: candle.low, close: candle.close,
      volume: finiteOrNull(candle.volume), ema50: finiteOrNull(candle.EMA50),
      ema200: finiteOrNull(candle.EMA200), rsi: finiteOrNull(candle.RSI), atr: finiteOrNull(candle.ATR),
    });
  });
  return [...byTimestamp.values()].sort((left, right) => Number(left.time) - Number(right.time));
}

export const toCandlestickData = (candles: JQEChartCandle[]): CandlestickData<Time>[] =>
  candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close }));

export const toLineData = (candles: JQEChartCandle[], key: 'ema50' | 'ema200' | 'rsi'): LineData<Time>[] =>
  candles.flatMap((candle) => candle[key] === null ? [] : [{ time: candle.time, value: candle[key] }]);

export const toVolumeData = (candles: JQEChartCandle[]): HistogramData<Time>[] =>
  candles.flatMap((candle) => candle.volume === null ? [] : [{
    time: candle.time, value: candle.volume,
    color: candle.close >= candle.open ? 'rgba(0, 230, 118, 0.22)' : 'rgba(255, 82, 82, 0.22)',
  }]);

export function adaptSignal(signal: SignalResponse | null, symbol: string): JQEChartAnnotation | null {
  if (!signal || signal.symbol !== symbol) return null;
  const plan = signal.trade_plan;
  return {
    signal: signal.signal, entry: finiteOrNull(plan?.entry ?? null),
    stopLoss: finiteOrNull(plan?.stop_loss ?? null), takeProfit: finiteOrNull(plan?.take_profit ?? null),
  };
}

export function toSignalMarkers(annotation: JQEChartAnnotation | null, time: Time | null): SeriesMarker<Time>[] {
  if (!annotation || time === null) return [];
  if (annotation.signal === 'BUY') return [{ time, position: 'belowBar', color: '#00e676', shape: 'arrowUp', text: 'JQE BUY' }];
  if (annotation.signal === 'SELL') return [{ time, position: 'aboveBar', color: '#ff5252', shape: 'arrowDown', text: 'JQE SELL' }];
  return [{ time, position: 'aboveBar', color: '#9aa4b2', shape: 'circle', text: 'JQE NO TRADE' }];
}
