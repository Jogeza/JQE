/**
 * JQE API Client Service Layer
 * Centralized, typed API access for all frontend components.
 */

import {
  SystemStatusResponse,
  MarketSummaryResponse,
  CandlesResponse,
  SignalResponse,
  RiskStatusResponse,
  ExecutionStateResponse,
  ExecutionSafetyResponse,
  RecoveryDiagnosticsResponse,
  PerformanceSummaryResponse,
  ExperimentListFilters,
  ExperimentListResponse,
  ExperimentDetailDTO,
  ExperimentComparisonResponse,
} from '../types/api';

const API_BASE = '/api/v1';

class ApiError extends Error {
  constructor(public status: number, message: string, public data?: unknown) {
    super(message);
    this.name = 'ApiError';
  }
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const errJson = await response.json();
      if (errJson?.detail) errorDetail = errJson.detail;
      else if (errJson?.message) errorDetail = errJson.message;
    } catch {
      // ignore parse error
    }
    throw new ApiError(response.status, errorDetail);
  }

  return response.json();
}

export const jqeApi = {
  /** Health check endpoint */
  async getHealth(): Promise<{ status: string; environment: string }> {
    return fetchJson('/health');
  },

  /** System configuration, broker connectivity, and server status */
  async getSystemStatus(signal?: AbortSignal): Promise<SystemStatusResponse> {
    return fetchJson(`${API_BASE}/system`, { signal });
  },

  /** Latest market summary & indicator snapshot */
  async getMarketSummary(symbol?: string, timeframe?: string, count?: number, signal?: AbortSignal): Promise<MarketSummaryResponse> {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    if (count) params.append('count', count.toString());
    const query = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/market/summary${query}`, { signal });
  },

  /** Recent historical candles with computed indicators (EMA, RSI, ATR) */
  async getMarketCandles(symbol?: string, timeframe?: string, count: number = 60, signal?: AbortSignal): Promise<CandlesResponse> {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    if (count) params.append('count', count.toString());
    const query = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/market/candles${query}`, { signal });
  },

  /** Strategy evaluation, 6-factor confidence breakdown, and Trade Plan */
  async getStrategySignal(symbol?: string, timeframe?: string, count?: number, signal?: AbortSignal): Promise<SignalResponse> {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    if (count) params.append('count', count.toString());
    const query = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/signal${query}`, { signal });
  },

  /** Broker-neutral risk authorization and typed quantity observation */
  async getRiskStatus(symbol?: string, timeframe?: string, signal?: AbortSignal): Promise<RiskStatusResponse> {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    const query = params.toString() ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/risk${query}`, { signal });
  },

  /** Execution layer open positions and recent trade history */
  async getExecutionState(signal?: AbortSignal): Promise<ExecutionStateResponse> {
    return fetchJson(`${API_BASE}/execution`, { signal });
  },

  /** Read-only canonical execution-safety publication; never evaluates policy */
  async getExecutionSafety(signal?: AbortSignal): Promise<ExecutionSafetyResponse> {
    return fetchJson(`${API_BASE}/execution/safety`, { signal });
  },

  /** Read-only durable startup recovery diagnostics; never triggers recovery */
  async getRecoveryDiagnostics(signal?: AbortSignal): Promise<RecoveryDiagnosticsResponse> {
    return fetchJson(`${API_BASE}/execution/recovery`, { signal });
  },

  /** Quantitative performance summary derived from closed trade executions */
  async getPerformanceSummary(signal?: AbortSignal): Promise<PerformanceSummaryResponse> {
    return fetchJson(`${API_BASE}/performance`, { signal });
  },

  async listExperiments(filters: ExperimentListFilters = {}, signal?: AbortSignal): Promise<ExperimentListResponse> {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const query = params.size ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/research/experiments${query}`, { signal });
  },

  async getExperiment(experimentId: string, signal?: AbortSignal): Promise<ExperimentDetailDTO> {
    return fetchJson(`${API_BASE}/research/experiments/${encodeURIComponent(experimentId)}`, { signal });
  },

  async compareExperiments(leftId: string, rightId: string, signal?: AbortSignal): Promise<ExperimentComparisonResponse> {
    const params = new URLSearchParams({ left: leftId, right: rightId });
    return fetchJson(`${API_BASE}/research/experiments/compare?${params.toString()}`, { signal });
  },
};

export { ApiError };
