import type { ResearchReplayDTO } from '../../types/research';
import type { CandleItemDTO } from '../../types/api';
import type { SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts';
import { getChartPalette } from './chartPalette';

const time = (value: string): UTCTimestamp => Math.floor(Date.parse(value) / 1000) as UTCTimestamp;

export function adaptReplay(dto: ResearchReplayDTO) {
  const palette = getChartPalette();
  const cursor = dto.cursor;
  const candles: CandleItemDTO[] = dto.candles.filter(c => c.candle_index <= cursor).map(({ candle, indicators }) => ({
    ...candle, volume: candle.volume ?? null, EMA50: indicators.ema50 ?? null,
    EMA200: indicators.ema200 ?? null, RSI: indicators.rsi ?? null, ATR: indicators.atr ?? null,
  }));
  const markers: SeriesMarker<Time>[] = [];
  dto.signals.filter(s => s.candle_index <= cursor && s.state === 'QUEUED').forEach(signal => {
    markers.push({ time: time(signal.timestamp), position: signal.signal === 'BUY' ? 'belowBar' : 'aboveBar',
      color: signal.signal === 'BUY' ? palette.bull : palette.bear, shape: signal.signal === 'BUY' ? 'arrowUp' : 'arrowDown',
      text: `${signal.signal} ${signal.confidence}%` });
  });
  dto.trades.filter(t => t.entry_index <= cursor).forEach(trade => {
    markers.push({ time: time(trade.entry_timestamp), position: trade.direction === 'BUY' ? 'belowBar' : 'aboveBar',
      color: palette.accent, shape: 'circle', text: 'ENTRY' });
    if (trade.exit_index !== undefined && trade.exit_index <= cursor && trade.exit_timestamp) {
      markers.push({ time: time(trade.exit_timestamp), position: trade.direction === 'BUY' ? 'aboveBar' : 'belowBar',
        color: palette.neutral, shape: 'square', text: 'EXIT' });
    }
  });
  markers.sort((a, b) => Number(a.time) - Number(b.time));
  return {
    cursor, candles,
    decisions: dto.signals.filter(s => s.candle_index <= cursor),
    trades: dto.trades.filter(t => t.entry_index <= cursor).map(t => {
      const closed = t.exit_index !== undefined && t.exit_index <= cursor;
      return { id: t.trade_id, direction: t.direction, entry: t.entry_price, stop: t.stop_price, target: t.target_price,
        exit: closed ? t.exit_price : undefined, pnl: closed ? t.net_pnl : undefined };
    }),
    balance: dto.balance_curve.filter(p => p.candle_index <= cursor), markers,
    currentIndicators: dto.candles.find(c => c.candle_index === cursor)?.indicators,
    currentDecision: dto.signals.find(s => s.candle_index === cursor),
    metrics: dto.complete ? dto.metrics : undefined,
  };
}
