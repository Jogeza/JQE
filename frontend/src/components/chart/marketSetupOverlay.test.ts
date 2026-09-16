import { describe, expect, it } from 'vitest';
import { adaptMarketSetup, toSignalMarkers } from './chartAdapters';
import type { MarketSetup } from '../../types/api';

describe('adaptMarketSetup', () => {
  const baseSetup: MarketSetup = {
    setup_id: 'setup-test-1',
    symbol: 'XAUUSD',
    timeframe: 'H1',
    observed_at: '2026-09-13T12:00:00Z',
    candle_close_time: '2026-09-13T12:00:00Z',
    expires_at: '2026-09-13T14:00:00Z',
    direction: 'NO_TRADE',
    setup_state: 'FORMING',
    entry_price: null,
    stop_loss: null,
    targets: [],
    levels: [
      { kind: 'SUPPORT', price: '2500.50', method: 'RECENT_RANGE_20_V1' },
      { kind: 'RESISTANCE', price: '2520.00', method: 'RECENT_RANGE_20_V1' },
    ],
    analyzed_candle_time: '2026-09-13T11:00:00Z',
    risk_reward_ratio: null,
    confidence_score: 45,
    confidence_method: '6-factor confluence',
    evidence: [],
    conflicts: ['MOMENTUM_CONTRADICTION'],
    market_regime: 'RANGE',
    invalidation_condition: null,
    data_freshness: {
      status: 'CURRENT',
      source: 'SIMULATION',
      age_seconds: '0',
      maximum_age_seconds: 3600,
      reason: 'Fresh candle',
      latest_closed_candle_at: '2026-09-13T12:00:00Z',
      expected_closed_candle_at: '2026-09-13T12:00:00Z',
      freshness_tolerance_seconds: 3600,
      freshness_age_seconds: '0',
      freshness_state: 'FRESH',
      freshness_reason_codes: ['FRESH'],
      reason_codes: [],
    },
    risk_authorization: {
      status: 'BLOCKED',
      reason: 'No direction',
      reason_codes: [],
      authorized_risk_amount: null,
      authorized_risk_percent: null,
      quantity: null,
      quantity_unit: null,
      expected_loss_at_stop: null,
    },
    execution_authorization: {
      status: 'BLOCKED',
      reason: 'No direction',
      reason_codes: [],
      authorized_risk_amount: null,
      authorized_risk_percent: null,
      quantity: null,
      quantity_unit: null,
      expected_loss_at_stop: null,
    },
    reason_codes: ['NO_TRADE'],
    historical_win_rate: {
      status: 'UNAVAILABLE',
      win_rate_percent: null,
      sample_size: null,
      evaluation_start: null,
      evaluation_end: null,
      strategy_version: null,
      dataset_hash: null,
      compatibility_state: 'UNVERIFIED',
      reason: 'No evidence',
    },
    schema_version: 1,
  };

  it('never fabricates entry/stop/target prices for NO_TRADE setup', () => {
    const annotation = adaptMarketSetup(baseSetup, 'XAUUSD');
    expect(annotation).not.toBeNull();
    expect(annotation?.signal).toBe('NO_TRADE');
    expect(annotation?.entry).toBeNull();
    expect(annotation?.stopLoss).toBeNull();
    expect(annotation?.takeProfit).toBeNull();
  });

  it('extracts support and resistance levels for NO_TRADE setup', () => {
    const annotation = adaptMarketSetup(baseSetup, 'XAUUSD');
    expect(annotation?.levels).toHaveLength(2);
    expect(annotation?.levels?.[0]).toEqual({
      price: 2500.5,
      levelType: 'SUPPORT',
      name: 'SUPPORT · RECENT_RANGE_20_V1',
    });
    expect(annotation?.levels?.[1]).toEqual({
      price: 2520,
      levelType: 'RESISTANCE',
      name: 'RESISTANCE · RECENT_RANGE_20_V1',
    });
  });

  it('rejects setups for mismatched symbols', () => {
    const annotation = adaptMarketSetup(baseSetup, 'EURUSD');
    expect(annotation).toBeNull();
  });

  it('overlays entry, stopLoss, and takeProfit only for active BUY/SELL setups', () => {
    const buySetup: MarketSetup = {
      ...baseSetup,
      direction: 'BUY',
      setup_state: 'READY',
      entry_price: '2510.00',
      stop_loss: '2500.00',
      targets: ['2530.00'],
    };
    const annotation = adaptMarketSetup(buySetup, 'XAUUSD');
    expect(annotation?.signal).toBe('BUY');
    expect(annotation?.entry).toBe(2510);
    expect(annotation?.stopLoss).toBe(2500);
    expect(annotation?.takeProfit).toBe(2530);
  });

  it('creates circle marker for NO_TRADE and arrow for BUY/SELL at analyzed candle time', () => {
    const noTradeAnnotation = adaptMarketSetup(baseSetup, 'XAUUSD');
    const markers = toSignalMarkers(noTradeAnnotation, null);
    expect(markers).toHaveLength(1);
    expect(markers[0].shape).toBe('circle');
    expect(markers[0].text).toBe('JQE NO TRADE');

    const buySetup: MarketSetup = {
      ...baseSetup,
      direction: 'BUY',
    };
    const buyAnnotation = adaptMarketSetup(buySetup, 'XAUUSD');
    const buyMarkers = toSignalMarkers(buyAnnotation, null);
    expect(buyMarkers).toHaveLength(1);
    expect(buyMarkers[0].shape).toBe('arrowUp');
    expect(buyMarkers[0].text).toBe('JQE BUY');
  });
});
