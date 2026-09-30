import { describe, expect, it } from 'vitest';
import { fibonacciLevels, suggestFibonacciAnchors } from './fibonacci';
import type { CandleItemDTO } from '../../types/api';

const candle = (low: number, high: number, close: number): CandleItemDTO => ({
  time: '2026-09-29T00:00:00Z', open: close, high, low, close, volume: 1,
  EMA50: null, EMA200: null, RSI: null, ATR: null,
});

describe('Fibonacci research overlay', () => {
  it('uses chronological swing direction and only displayed candles', () => {
    expect(suggestFibonacciAnchors([candle(10, 12, 11), candle(14, 20, 17)]))
      .toEqual({ a: 10, b: 20, c: 17 });
    expect(suggestFibonacciAnchors([candle(18, 20, 19), candle(10, 15, 12)]))
      .toEqual({ a: 20, b: 10, c: 12 });
    expect(suggestFibonacciAnchors([candle(10, 12, 11)])).toBeNull();
  });

  it('computes retracements from A to B and extensions from C in both directions', () => {
    const up = fibonacciLevels('both', { a: 100, b: 200, c: 150 });
    expect(up.find(level => level.kind === 'retracement' && level.ratio === 0.5)?.price).toBe(150);
    expect(up.find(level => level.kind === 'extension' && level.ratio === 1)?.price).toBe(250);
    const down = fibonacciLevels('both', { a: 200, b: 100, c: 150 });
    expect(down.find(level => level.kind === 'retracement' && level.ratio === 0.5)?.price).toBe(150);
    expect(down.find(level => level.kind === 'extension' && level.ratio === 1)?.price).toBe(50);
    expect(fibonacciLevels('off', { a: 100, b: 200, c: 150 })).toEqual([]);
    expect(fibonacciLevels('both', { a: 100, b: 100, c: 150 })).toEqual([]);
  });
});
