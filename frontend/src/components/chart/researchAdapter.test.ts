import { describe, expect, it } from 'vitest';
import { adaptCandles, toSignalMarkers } from './chartAdapters';
import { adaptReplay } from './researchAdapter';
import type { ResearchReplayDTO } from '../../types/research';

describe('research visibility', () => {
  it('drops future data and outcome fields defensively', () => {
    const dto: ResearchReplayDTO = { id: 'x', cursor: 1, complete: false, candles: [], signals: [{ candle_index: 1, timestamp: '2026-01-01T00:00:00Z', signal: 'BUY', confidence: 80, state: 'QUEUED', reasons: [] }],
      trades: [{ trade_id: 1, entry_index: 1, entry_timestamp: '', direction: 'BUY', entry_price: 10, stop_price: 9, target_price: 12,
        exit_index: 3, exit_price: 12, net_pnl: 2 }], balance_curve: [], metrics: { profit: 2 } };
    expect(adaptReplay(dto).trades[0].pnl).toBeUndefined();
    expect(adaptReplay(dto).metrics).toBeUndefined();
    expect(adaptReplay(dto).markers.map(marker => marker.text)).toEqual(['BUY 80%', 'ENTRY']);
  });
  it('validates, sorts and deduplicates chart timestamps', () => {
    const candle = { time: '2026-01-01T00:00:00Z', open: 1, high: 2, low: 1, close: 2, volume: null, EMA50: null, EMA200: null, RSI: null, ATR: null };
    const result = adaptCandles([{ ...candle, time: 'invalid' }, { ...candle, time: '2026-01-02T00:00:00Z' }, candle, candle]);
    expect(result).toHaveLength(2);
    expect(Number(result[0].time)).toBeLessThan(Number(result[1].time));
  });
  it('maps backend signals without generating a decision', () => {
    expect(toSignalMarkers(null, null)).toEqual([]);
    expect(toSignalMarkers({ signal: 'BUY', entry: 1, stopLoss: 0, takeProfit: 2 }, '2026-01-01')[0].shape).toBe('arrowUp');
  });
});
