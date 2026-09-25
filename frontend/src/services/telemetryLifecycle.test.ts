import { describe, expect, it } from 'vitest';
import { canonicalSignalFromAssessment, deriveTelemetryLifecycle, isOlderAssessment, validateOfflineTelemetry } from './telemetryLifecycle';

const snapshot = (overrides: Record<string, unknown> = {}) => ({
  schema_version: 1,
  mode: 'OFFLINE_SIMULATION',
  observed_at: '2026-09-14T15:09:00Z',
  environment: 'development',
  backend: { state: 'LIVE', value: 'ONLINE', observed_at: '2026-09-14T15:09:00Z', source: 'FASTAPI', reason_codes: [] },
  strategy: { state: 'FRESH', value: 'BUY', observed_at: '2026-09-14T15:08:00Z', source: 'CANONICAL_STRATEGY_PIPELINE', reason_codes: ['ANALYSIS_ONLY'] },
  candle_freshness: { state: 'FRESH', value: 'CURRENT', observed_at: '2026-09-14T15:08:00Z', source: 'SIMULATION', reason_codes: [] },
  risk: { state: 'FRESH', value: 'NOT_EVALUATED', observed_at: '2026-09-14T15:08:00Z', source: 'OFFLINE_SETUP', reason_codes: ['ANALYSIS_ONLY'] },
  execution_authorization: { state: 'BLOCKED', value: 'BLOCKED', observed_at: '2026-09-14T15:08:00Z', source: 'OFFLINE_SIMULATION_POLICY', reason_codes: ['ANALYSIS_ONLY'] },
  simulation_submissions: { state: 'FRESH', account_scope: 'simulation:JQE-DASHBOARD-PAPER', utc_count: 0, limit: 5, utc_date: '2026-09-14', reset_at: '2026-09-15T00:00:00Z', reason_codes: [] },
  broker_execution_enabled: false,
  assessment: {
    schema_version: 1, setup_id: 'setup', symbol: 'R_75', timeframe: 'H1',
    observed_at: '2026-09-14T15:08:00Z', candle_close_time: '2026-09-14T15:00:00Z',
    expires_at: '2026-09-14T17:00:00Z', direction: 'BUY', setup_state: 'BLOCKED',
    entry_price: null, stop_loss: null, targets: [], levels: [], analyzed_candle_time: null,
    risk_reward_ratio: null, confidence_score: 86, confidence_method: 'TEST', evidence: [], conflicts: [],
    market_regime: 'TRENDING', invalidation_condition: null,
    data_freshness: { status: 'CURRENT', source: 'SIMULATION', age_seconds: 0, maximum_age_seconds: 3600, reason: 'fresh', latest_closed_candle_at: null, expected_closed_candle_at: null, freshness_tolerance_seconds: 3600, freshness_age_seconds: 0, freshness_state: 'FRESH', freshness_reason_codes: [], reason_codes: [] },
    risk_authorization: { status: 'NOT_EVALUATED', reason: 'analysis only', reason_codes: ['ANALYSIS_ONLY'], authorized_risk_amount: null, authorized_risk_percent: null, quantity: null, quantity_unit: null, expected_loss_at_stop: null },
    execution_authorization: { status: 'BLOCKED', reason: 'analysis only', reason_codes: ['ANALYSIS_ONLY'], authorized_risk_amount: null, authorized_risk_percent: null, quantity: null, quantity_unit: null, expected_loss_at_stop: null },
    reason_codes: ['ANALYSIS_ONLY'], historical_win_rate: { status: 'UNAVAILABLE', win_rate_percent: null, sample_size: null, evaluation_start: null, evaluation_end: null, strategy_version: null, dataset_hash: null, compatibility_state: 'UNVERIFIED', reason: 'none' },
  },
  ...overrides,
});

describe('offline telemetry lifecycle', () => {
  it('projects the lower-panel conclusion from the canonical assessment', () => {
    const conflicting = validateOfflineTelemetry(snapshot({
      strategy: { ...snapshot().strategy as object, value: 'NO_TRADE' },
    }));

    const lowerPanel = canonicalSignalFromAssessment(conflicting.assessment);

    expect(lowerPanel?.signal).toBe('BUY');
    expect(lowerPanel?.signal).toBe(conflicting.assessment?.direction);
    expect(lowerPanel?.signal).not.toBe(conflicting.strategy.value);
  });

  it('transitions fresh to stale from expiry without another response', () => {
    const valid = validateOfflineTelemetry(snapshot());
    expect(deriveTelemetryLifecycle({ snapshot: valid, connected: true, loading: false, lastSuccessfulContact: new Date(), now: new Date('2026-09-14T16:00:00Z') }).state).toBe('LIVE');
    expect(deriveTelemetryLifecycle({ snapshot: valid, connected: true, loading: false, lastSuccessfulContact: new Date(), now: new Date('2026-09-14T17:00:00Z') }).state).toBe('STALE');
  });

  it('retains historical context as offline and recovers only with valid telemetry', () => {
    const valid = validateOfflineTelemetry(snapshot());
    const offline = deriveTelemetryLifecycle({ snapshot: valid, connected: false, loading: false, lastSuccessfulContact: new Date('2026-09-14T15:09:00Z'), now: new Date('2026-09-14T16:00:00Z') });
    expect(offline.state).toBe('OFFLINE');
    expect(offline.assessment?.direction).toBe('BUY');
    expect(deriveTelemetryLifecycle({ snapshot: valid, connected: true, loading: false, lastSuccessfulContact: new Date(), now: new Date('2026-09-14T16:00:00Z') }).state).toBe('LIVE');
  });

  it('rejects out-of-order assessments', () => {
    const current = validateOfflineTelemetry(snapshot());
    const older = validateOfflineTelemetry(snapshot({ assessment: { ...snapshot().assessment as object, observed_at: '2026-09-14T14:00:00Z' } }));
    expect(isOlderAssessment(current, older)).toBe(true);
  });

  it('fails closed for malformed and unsupported schemas', () => {
    expect(() => validateOfflineTelemetry({ schema_version: 1 })).toThrow('MALFORMED_TELEMETRY');
    expect(() => validateOfflineTelemetry(snapshot({ schema_version: 2 }))).toThrow('UNSUPPORTED_TELEMETRY_SCHEMA');
    expect(() => validateOfflineTelemetry(snapshot({ assessment: { ...snapshot().assessment as object, schema_version: 2 } }))).toThrow('UNSUPPORTED_ASSESSMENT_SCHEMA');
  });

  it('accepts absent optional dataset fields but keeps analysis blocked and count unchanged', () => {
    const valid = validateOfflineTelemetry(snapshot());
    expect(valid.assessment?.dataset_hash).toBeUndefined();
    expect(valid.assessment?.execution_authorization.status).toBe('BLOCKED');
    expect(valid.assessment?.execution_authorization.reason_codes).toContain('ANALYSIS_ONLY');
    expect(valid.simulation_submissions.utc_count).toBe(0);
  });

  it('accepts an ordinary no-trade reason inside the explicit offline-simulation envelope', () => {
    const base = snapshot().assessment as Record<string, unknown>;
    const valid = validateOfflineTelemetry(snapshot({
      assessment: {
        ...base,
        direction: 'NO_TRADE',
        reason_codes: ['NO_TRADE'],
        execution_authorization: {
          status: 'BLOCKED', reason: 'normal no-trade', reason_codes: ['NO_TRADE'],
          authorized_risk_amount: null, authorized_risk_percent: null,
          quantity: null, quantity_unit: null, expected_loss_at_stop: null,
        },
      },
    }));
    expect(valid.assessment?.direction).toBe('NO_TRADE');
  });
});
