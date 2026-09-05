import type { Time } from 'lightweight-charts';

export interface JQEChartCandle {
  time: Time;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  ema50: number | null;
  ema200: number | null;
  rsi: number | null;
  atr: number | null;
}

export interface JQEChartAnnotation {
  signal: 'BUY' | 'SELL' | 'NO_TRADE';
  entry: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
}
