import { MarketSetup, OfflineMonitoringResponse, SignalResponse } from '../types/api';

export type TelemetryLifecycleState = 'LOADING' | 'LIVE' | 'STALE' | 'OFFLINE' | 'UNAVAILABLE';

export interface TelemetryLifecycle {
  state: TelemetryLifecycleState;
  snapshot: OfflineMonitoringResponse | null;
  assessment: MarketSetup | null;
  lastSuccessfulContact: Date | null;
  reason: string;
}

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const validDate = (value: unknown): value is string =>
  typeof value === 'string' && Number.isFinite(Date.parse(value));

export function canonicalSignalFromAssessment(assessment: MarketSetup | null): SignalResponse | null {
  if (!assessment) return null;
  const evidence = Object.fromEntries(assessment.evidence.map(item => [item.factor, item]));
  const score = (name: string) => evidence[name]?.score ?? 0;
  const factor = (name: string) => evidence[name]?.assessment ?? 'UNKNOWN';
  return {
    symbol: assessment.symbol,
    signal: assessment.direction,
    confidence: assessment.confidence_score,
    quality: assessment.confidence_score >= 80 ? 'HIGH' : assessment.confidence_score >= 70 ? 'GOOD' : 'LOW',
    score: assessment.confidence_score,
    reasons: [...assessment.conflicts, ...assessment.reason_codes],
    regime: assessment.market_regime,
    trend: factor('trend'),
    momentum: factor('momentum'),
    volatility: factor('volatility'),
    liquidity: factor('liquidity'),
    confidence_breakdown: {
      trend_score: score('trend'), structure_score: score('structure'),
      liquidity_score: score('liquidity'), momentum_score: score('momentum'),
      volatility_score: score('volatility'), risk_score: score('risk'),
      total: assessment.confidence_score,
      factors: Object.fromEntries(assessment.evidence.map(item => [item.factor, item.assessment])),
    },
    trade_plan: null,
    generated_at: assessment.observed_at,
    price_decimals: 5,
  };
}

export function validateOfflineTelemetry(value: unknown): OfflineMonitoringResponse {
  if (!object(value)) throw new Error('MALFORMED_TELEMETRY');
  if (value.schema_version !== 1) throw new Error('UNSUPPORTED_TELEMETRY_SCHEMA');
  if (value.mode !== 'OFFLINE_SIMULATION' || !validDate(value.observed_at)) throw new Error('MALFORMED_TELEMETRY');
  if (value.broker_execution_enabled !== false) throw new Error('EXECUTION_NOT_BLOCKED');
  if (!object(value.backend) || !object(value.simulation_submissions)) throw new Error('MALFORMED_TELEMETRY');
  const cap = value.simulation_submissions;
  if (!Number.isInteger(cap.utc_count) || !Number.isInteger(cap.limit) || !validDate(cap.reset_at)) {
    throw new Error('MALFORMED_TELEMETRY');
  }
  const assessment = value.assessment;
  if (assessment !== null && assessment !== undefined) {
    if (!object(assessment) || assessment.schema_version !== 1) throw new Error('UNSUPPORTED_ASSESSMENT_SCHEMA');
    if (!validDate(assessment.observed_at) || !validDate(assessment.candle_close_time)) throw new Error('MALFORMED_ASSESSMENT');
    if (assessment.expires_at !== null && assessment.expires_at !== undefined && !validDate(assessment.expires_at)) throw new Error('MALFORMED_ASSESSMENT');
    if (!object(assessment.execution_authorization)) throw new Error('MALFORMED_ASSESSMENT');
    const authorization = assessment.execution_authorization.status;
    if (authorization !== 'BLOCKED' && authorization !== 'AUTHORIZED') {
      throw new Error('INVALID_SIMULATION_AUTHORIZATION');
    }
    if (authorization === 'AUTHORIZED' && value.broker_execution_enabled !== false) {
      throw new Error('EXECUTION_NOT_BLOCKED');
    }
  }
  return value as unknown as OfflineMonitoringResponse;
}

export function isOlderAssessment(
  current: OfflineMonitoringResponse | null,
  incoming: OfflineMonitoringResponse,
): boolean {
  const currentAt = current?.assessment?.observed_at;
  const incomingAt = incoming.assessment?.observed_at;
  return Boolean(currentAt && (!incomingAt || Date.parse(incomingAt) < Date.parse(currentAt)));
}

export function deriveTelemetryLifecycle(args: {
  snapshot: OfflineMonitoringResponse | null;
  connected: boolean;
  loading: boolean;
  lastSuccessfulContact: Date | null;
  now: Date;
  validationError?: string | null;
}): TelemetryLifecycle {
  const { snapshot, connected, loading, lastSuccessfulContact, now, validationError } = args;
  if (loading && !snapshot) return { state: 'LOADING', snapshot: null, assessment: null, lastSuccessfulContact, reason: 'Waiting for telemetry' };
  if (validationError) return { state: 'UNAVAILABLE', snapshot: null, assessment: null, lastSuccessfulContact, reason: validationError };
  if (!snapshot) return { state: connected ? 'UNAVAILABLE' : 'OFFLINE', snapshot: null, assessment: null, lastSuccessfulContact, reason: connected ? 'No valid assessment' : 'Backend unreachable' };
  if (!connected) return { state: 'OFFLINE', snapshot, assessment: snapshot.assessment, lastSuccessfulContact, reason: 'Historical context only; backend unreachable' };
  const expiry = snapshot.assessment?.expires_at;
  const embeddedStale = snapshot.strategy.state === 'STALE' || snapshot.candle_freshness.state === 'STALE';
  if (!snapshot.assessment || embeddedStale || (expiry && now.getTime() >= Date.parse(expiry))) {
    return { state: 'STALE', snapshot, assessment: snapshot.assessment, lastSuccessfulContact, reason: 'Assessment expired or server marked it stale' };
  }
  return { state: 'LIVE', snapshot, assessment: snapshot.assessment, lastSuccessfulContact, reason: 'Validated current analysis-only telemetry' };
}
