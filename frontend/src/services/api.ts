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
  PerformanceSummaryResponse,
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

  /** Account risk status, daily limit usage, and trade sizing evaluation */
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

  /** Quantitative performance summary derived from closed trade executions */
  async getPerformanceSummary(signal?: AbortSignal): Promise<PerformanceSummaryResponse> {
    return fetchJson(`${API_BASE}/performance`, { signal });
  },
};
