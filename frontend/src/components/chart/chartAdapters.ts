import type { CandlestickData, HistogramData, LineData, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts';
import type { CandleItemDTO, MarketSetup, SignalResponse } from '../../types/api';
import type { JQEChartAnnotation, JQEChartCandle, JQEChartLevel } from './chartTypes';
import { chartPaletteFallback, type JQEChartPalette } from './chartPalette';

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

export const toCandlestickData = (candles: JQEChartCandle[], palette: JQEChartPalette = chartPaletteFallback): CandlestickData<Time>[] =>
  candles.map(({ time, open, high, low, close }) => open === close
    ? { time, open, high, low, close, color: palette.neutral, borderColor: palette.neutral, wickColor: palette.neutral }
    : { time, open, high, low, close });

export const toLineData = (candles: JQEChartCandle[], key: 'ema50' | 'ema200' | 'rsi'): LineData<Time>[] =>
  candles.flatMap((candle) => candle[key] === null ? [] : [{ time: candle.time, value: candle[key] }]);

export const toVolumeData = (candles: JQEChartCandle[], palette: JQEChartPalette = chartPaletteFallback): HistogramData<Time>[] =>
  candles.flatMap((candle) => candle.volume === null ? [] : [{
    time: candle.time, value: candle.volume,
    color: candle.close === candle.open ? palette.profile : candle.close > candle.open ? palette.bullSoft : palette.bearSoft,
  }]);

export function adaptSignal(signal: SignalResponse | null, symbol: string): JQEChartAnnotation | null {
  if (!signal || signal.symbol !== symbol) return null;
  const plan = signal.trade_plan;
  return {
    signal: signal.signal, entry: finiteOrNull(plan?.entry ?? null),
    stopLoss: finiteOrNull(plan?.stop_loss ?? null), takeProfit: finiteOrNull(plan?.take_profit ?? null),
  };
}

export function adaptMarketSetup(setup: MarketSetup | null, symbol: string): JQEChartAnnotation | null {
  if (!setup || setup.symbol !== symbol) return null;

  const isTrade = setup.direction === 'BUY' || setup.direction === 'SELL';
  const entry = isTrade && setup.entry_price ? finiteOrNull(parseFloat(setup.entry_price)) : null;
  const stopLoss = isTrade && setup.stop_loss ? finiteOrNull(parseFloat(setup.stop_loss)) : null;
  const takeProfit = isTrade && setup.targets?.[0] ? finiteOrNull(parseFloat(setup.targets[0])) : null;

  const levels: JQEChartLevel[] = (setup.levels || []).flatMap((lvl) => {
    const p = parseFloat(lvl.price);
    if (!Number.isFinite(p)) return [];
    return [{
      price: p,
      levelType: lvl.kind,
      name: `${lvl.kind} · ${lvl.method}`,
    }];
  });

  const analyzedCandleTime = setup.analyzed_candle_time ? toUtcTimestamp(setup.analyzed_candle_time) : null;

  return {
    signal: setup.direction,
    entry,
    stopLoss,
    takeProfit,
    levels,
    analyzedCandleTime,
  };
}

export function toSignalMarkers(
  annotation: JQEChartAnnotation | null,
  fallbackTime: Time | null,
  palette: JQEChartPalette = chartPaletteFallback,
): SeriesMarker<Time>[] {
  if (!annotation) return [];
  const time = annotation.analyzedCandleTime ?? fallbackTime;
  if (time === null) return [];

  if (annotation.signal === 'BUY') {
    return [{ time, position: 'belowBar', color: palette.bull, shape: 'arrowUp', text: 'JQE BUY' }];
  }
  if (annotation.signal === 'SELL') {
    return [{ time, position: 'aboveBar', color: palette.bear, shape: 'arrowDown', text: 'JQE SELL' }];
  }
  return [{ time, position: 'aboveBar', color: palette.neutral, shape: 'circle', text: 'JQE NO TRADE' }];
}
