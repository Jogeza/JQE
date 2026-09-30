import type { CandleItemDTO } from '../../types/api';

export type FibonacciMode = 'off' | 'retracement' | 'extension' | 'both';
export interface FibonacciAnchors { a: number; b: number; c: number; }
export interface FibonacciLevel { kind: 'retracement' | 'extension'; ratio: number; price: number; label: string; }

const retracementRatios = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const extensionRatios = [0.618, 1, 1.618, 2, 2.618];

/** Suggest a chronological swing from displayed candles. The operator can replace every anchor. */
export function suggestFibonacciAnchors(candles: CandleItemDTO[], lookback = 100): FibonacciAnchors | null {
  const window = candles.slice(-lookback);
  if (window.length < 2) return null;
  let low = 0;
  let high = 0;
  for (let i = 1; i < window.length; i += 1) {
    if (window[i].low < window[low].low) low = i;
    if (window[i].high > window[high].high) high = i;
  }
  if (low === high || window[low].low >= window[high].high) return null;
  return low < high
    ? { a: window[low].low, b: window[high].high, c: window[window.length - 1].close }
    : { a: window[high].high, b: window[low].low, c: window[window.length - 1].close };
}

export function fibonacciLevels(mode: FibonacciMode, anchors: FibonacciAnchors | null): FibonacciLevel[] {
  if (mode === 'off' || !anchors || !Object.values(anchors).every(Number.isFinite) || anchors.a === anchors.b) return [];
  const span = anchors.b - anchors.a;
  const result: FibonacciLevel[] = [];
  if (mode === 'retracement' || mode === 'both') {
    for (const ratio of retracementRatios) result.push({
      kind: 'retracement', ratio, price: anchors.b - span * ratio,
      label: `RET ${(ratio * 100).toFixed(1)}%`,
    });
  }
  if (mode === 'extension' || mode === 'both') {
    for (const ratio of extensionRatios) result.push({
      kind: 'extension', ratio, price: anchors.c + span * ratio,
      label: `EXT ${(ratio * 100).toFixed(1)}%`,
    });
  }
  return result;
}
