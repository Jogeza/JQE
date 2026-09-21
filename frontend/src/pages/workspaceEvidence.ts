import type {
  BrokerStatusResponse, ExecutionSafetyResponse, MarketSetup, ObservationHealthResponse,
  ResourceState, RiskStatusResponse, WatchlistCapUsageResponse, WatchlistResponse,
} from '../types/api';

export type PanelState = 'LOADING' | 'LIVE' | 'STALE' | 'OFFLINE' | 'UNAVAILABLE' | 'ERROR';

export const WORKSPACE_FRESHNESS_THRESHOLDS_MS = {
  brokerStatus: 5 * 60_000,
  executionSafety: 5 * 60_000,
  risk: 5 * 60_000,
  monitoring: 15 * 60_000,
  observationHealth: 2 * 60_000,
  watchlist: null,
  watchlistCapUsage: 15 * 60_000,
  demoVerification: 24 * 60 * 60_000,
} as const;

const record = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const validDate = (value: unknown): value is string =>
  typeof value === 'string' && Number.isFinite(Date.parse(value));
const codes = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string');

export function panelState<T>(resource: ResourceState<T>): PanelState {
  if (resource.loading && resource.data === null) return 'LOADING';
  if (resource.error && resource.data !== null) return 'OFFLINE';
  if (resource.error) return 'ERROR';
  if (resource.stale) return 'STALE';
  return resource.data === null ? 'UNAVAILABLE' : 'LIVE';
}

export function observationState<T>(
  resource: ResourceState<T>,
  observedAt: unknown,
  thresholdMs: number | null,
  now = Date.now(),
): PanelState {
  const transportState = panelState(resource);
  if (transportState !== 'LIVE' || thresholdMs === null) return transportState;
  if (!validDate(observedAt)) return 'UNAVAILABLE';
  return now - Date.parse(observedAt) > thresholdMs ? 'STALE' : 'LIVE';
}

export function validBroker(value: unknown): value is BrokerStatusResponse {
  if (!record(value) || typeof value.active_broker !== 'string' || !value.active_broker ||
      typeof value.connected !== 'boolean' || typeof value.observation_state !== 'string' ||
      (value.observed_at !== null && !validDate(value.observed_at))) return false;
  const identity = value.active_broker_identity;
  if (identity === null) return true;
  return record(identity) && typeof identity.broker === 'string' &&
    typeof identity.demo_guard_passed === 'boolean' &&
    (identity.verified_at === null || validDate(identity.verified_at)) &&
    (identity.account_id_masked === null || typeof identity.account_id_masked === 'string');
}

export function validAssessment(value: unknown): value is MarketSetup {
  if (!record(value) || !validDate(value.observed_at) || !validDate(value.candle_close_time) ||
      (value.expires_at !== null && !validDate(value.expires_at)) ||
      typeof value.symbol !== 'string' || !value.symbol ||
      typeof value.timeframe !== 'string' || !value.timeframe ||
      !['BUY', 'SELL', 'NO_TRADE'].includes(String(value.direction)) ||
      !codes(value.reason_codes) || !Array.isArray(value.evidence)) return false;
  for (const evidence of value.evidence) {
    if (!record(evidence) || typeof evidence.factor !== 'string' ||
        typeof evidence.assessment !== 'string' ||
        typeof evidence.score !== 'number' || !Number.isFinite(evidence.score) ||
        typeof evidence.maximum_score !== 'number' || !Number.isFinite(evidence.maximum_score)) return false;
  }
  if (!record(value.data_freshness) || typeof value.data_freshness.status !== 'string' ||
      !codes(value.data_freshness.reason_codes)) return false;
  for (const key of ['risk_authorization', 'execution_authorization']) {
    const stage = value[key];
    if (!record(stage) || typeof stage.status !== 'string' || !codes(stage.reason_codes)) return false;
  }
  return true;
}

export function validSafety(value: unknown): value is ExecutionSafetyResponse {
  return record(value) && typeof value.observation_state === 'string' &&
    typeof value.execution_authorization === 'string' &&
    typeof value.emergency_stop_state === 'string' && codes(value.reason_codes) &&
    (value.observed_at === null || validDate(value.observed_at));
}

export function validRisk(value: unknown): value is RiskStatusResponse {
  return record(value) && typeof value.observation_status === 'string' &&
    typeof value.observation_fresh === 'boolean' && typeof value.risk_authorized === 'boolean' &&
    (value.observation_age_seconds === null ||
      (typeof value.observation_age_seconds === 'number' && Number.isFinite(value.observation_age_seconds)));
}

export function validHealth(value: unknown): value is ObservationHealthResponse {
  return record(value) && typeof value.running === 'boolean' && typeof value.healthy === 'boolean' &&
    validDate(value.updated_at) &&
    (value.last_success_at === null || validDate(value.last_success_at));
}

export function validWatchlist(value: unknown): value is WatchlistResponse {
  return record(value) && Array.isArray(value.items) && value.items.every(item =>
    record(item) && typeof item.symbol === 'string' && typeof item.timeframe === 'string' &&
    typeof item.scope === 'string');
}

export function validCaps(value: unknown): value is WatchlistCapUsageResponse {
  return record(value) && validDate(value.observed_at) && Array.isArray(value.items) &&
    value.items.every(item => record(item) && typeof item.symbol === 'string' &&
      typeof item.timeframe === 'string' && typeof item.scope === 'string' &&
      Number.isInteger(item.daily_count) && Number.isInteger(item.daily_limit) &&
      typeof item.available === 'boolean' && validDate(item.reset_at));
}

export const formatTime = (value: unknown): string => validDate(value)
  ? new Date(value).toLocaleString('en-GB') : 'unavailable';

export const formatAge = (value: unknown, now = Date.now()): string => {
  if (!validDate(value)) return 'unavailable';
  const seconds = Math.max(0, Math.round((now - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
};

export const withinAge = (value: unknown, thresholdMs: number, now = Date.now()): boolean =>
  validDate(value) && now - Date.parse(value) <= thresholdMs;

export const reasonText = (value: unknown): string => codes(value) && value.length
  ? value.join(' · ') : 'No reason code supplied';
