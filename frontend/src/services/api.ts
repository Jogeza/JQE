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
  LiveExecutionResponse,
  ExecutionSafetyResponse,
  RecoveryDiagnosticsResponse,
  PaperRuntimeStatusResponse,
  PaperDiagnosticsResponse,
  PerformanceSummaryResponse,
  ExperimentListFilters,
  ExperimentListResponse,
  ExperimentDetailDTO,
  ExperimentComparisonResponse,
  MarketSetup,
  PaperExecutionOutcomeDTO,
  ActiveMarketAnalysisResponse,
  OfflineMonitoringResponse,
  ObservationHealthResponse,
  BrokerStatusResponse,
  SelectBrokerRequest,
  SelectBrokerResponse,
  WatchlistResponse,
  WatchlistItemDTO,
  WatchlistCapUsageResponse,
  AssistantStatusResponse,
  AssistantChatResponse,
  NotificationStatusResponse,
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
    let errorData: unknown;
    try {
      const errJson = await response.json();
      errorData = errJson;
      const detail = errJson?.detail;
      if (typeof detail === 'string') errorDetail = detail;
      else if (detail && typeof detail === 'object') {
        errorDetail = detail.message ?? detail.reason_code ?? JSON.stringify(detail);
      } else if (typeof errJson?.message === 'string') errorDetail = errJson.message;
    } catch {
      // Keep the transport-level message when the response is not JSON.
    }
    throw new ApiError(response.status, errorDetail, errorData);
  }

  return response.json();
}

export const jqeApi = {
  async getOfflineMonitoring(signal?: AbortSignal): Promise<OfflineMonitoringResponse> {
    return fetchJson(`${API_BASE}/monitoring/offline`, { signal });
  },
  async getObservationHealth(signal?: AbortSignal): Promise<ObservationHealthResponse> {
    return fetchJson(`${API_BASE}/observation/health`, { signal });
  },
  async getAssistantStatus(signal?: AbortSignal): Promise<AssistantStatusResponse> {
    return fetchJson(`${API_BASE}/assistant/status`, { signal });
  },
  async chatWithAssistant(message: string, signal?: AbortSignal): Promise<AssistantChatResponse> {
    return fetchJson(`${API_BASE}/assistant/chat`, {
      method: 'POST',
      body: JSON.stringify({ message }),
      signal,
    });
  },
  async getNotificationStatus(signal?: AbortSignal): Promise<NotificationStatusResponse> {
    return fetchJson(`${API_BASE}/notifications/status`, { signal });
  },
  async runOfflineAnalysis(symbol: string, timeframe: string, signal?: AbortSignal): Promise<MarketSetup> {
    const params = new URLSearchParams({ symbol, timeframe });
    return fetchJson(`${API_BASE}/monitoring/offline/analyze?${params}`, { method: 'POST', signal });
  },
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

  async getMarketSetup(symbol?: string, timeframe?: string, count?: number, signal?: AbortSignal): Promise<MarketSetup> {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    if (count) params.append('count', count.toString());
    const query = params.size ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/market/setup${query}`, { signal });
  },

  async getActiveMarketAnalysis(symbol?: string, timeframe?: string, count?: number, signal?: AbortSignal): Promise<ActiveMarketAnalysisResponse> {
    const params = new URLSearchParams();
    if (symbol) params.append('symbol', symbol);
    if (timeframe) params.append('timeframe', timeframe);
    if (count) params.append('count', count.toString());
    const query = params.size ? `?${params.toString()}` : '';
    return fetchJson(`${API_BASE}/market/active-analysis${query}`, { signal });
  },

  async executePaperSetup(setupId: string, signal?: AbortSignal): Promise<PaperExecutionOutcomeDTO> {
    return fetchJson(`${API_BASE}/market/setups/${encodeURIComponent(setupId)}/paper-execute`, {
      method: 'POST', signal,
    });
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

  async executeLiveCycle(signal?: AbortSignal): Promise<LiveExecutionResponse> {
    return fetchJson(`${API_BASE}/execution/cycle?confirmed=true`, {
      method: 'POST', signal,
    });
  },

  /** Read-only canonical execution-safety publication; never evaluates policy */
  async getExecutionSafety(signal?: AbortSignal): Promise<ExecutionSafetyResponse> {
    return fetchJson(`${API_BASE}/execution/safety`, { signal });
  },

  /** Read-only durable startup recovery diagnostics; never triggers recovery */
  async getRecoveryDiagnostics(signal?: AbortSignal): Promise<RecoveryDiagnosticsResponse> {
    return fetchJson(`${API_BASE}/execution/recovery`, { signal });
  },

  async getPaperRuntimeStatus(signal?: AbortSignal): Promise<PaperRuntimeStatusResponse> {
    return fetchJson(`${API_BASE}/execution/paper-runtime`, { signal });
  },

  async getPaperDiagnostics(signal?: AbortSignal): Promise<PaperDiagnosticsResponse> {
    return fetchJson(`${API_BASE}/research/paper-diagnostics`, { signal });
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

  /** Multi-broker connection status and DemoOnlyGuard verification */
  async getBrokerStatus(signal?: AbortSignal): Promise<BrokerStatusResponse> {
    return fetchJson(`${API_BASE}/brokers/status`, { signal });
  },

  /** Validate and persist the operator broker selection */
  async selectBroker(broker: string, reason: string = '', signal?: AbortSignal): Promise<SelectBrokerResponse> {
    return fetchJson(`${API_BASE}/brokers/select`, {
      method: 'POST',
      body: JSON.stringify({ broker, reason } satisfies SelectBrokerRequest),
      signal,
    });
  },

  /** Persisted watchlist of observed instruments */
  async getWatchlist(signal?: AbortSignal): Promise<WatchlistResponse> {
    return fetchJson(`${API_BASE}/watchlist`, { signal });
  },

  /** Add an instrument to the durable watchlist */
  async addToWatchlist(symbol: string, timeframe: string = 'H1', signal?: AbortSignal): Promise<WatchlistItemDTO> {
    return fetchJson(`${API_BASE}/watchlist`, {
      method: 'POST',
      body: JSON.stringify({ symbol, timeframe }),
      signal,
    });
  },

  /** Remove an instrument from the durable watchlist */
  async deleteFromWatchlist(symbol: string, timeframe?: string, signal?: AbortSignal): Promise<{ deleted: boolean; symbol: string }> {
    const query = timeframe ? `?timeframe=${encodeURIComponent(timeframe)}` : '';
    return fetchJson(`${API_BASE}/watchlist/${encodeURIComponent(symbol)}${query}`, {
      method: 'DELETE',
      signal,
    });
  },

  /** Daily cap usage for watchlisted instruments from DailyInstrumentTradeGuard */
  async getWatchlistCapUsage(accountScope?: string, signal?: AbortSignal): Promise<WatchlistCapUsageResponse> {
    const query = accountScope ? `?account_scope=${encodeURIComponent(accountScope)}` : '';
    return fetchJson(`${API_BASE}/watchlist/cap-usage${query}`, { signal });
  },
};

export { ApiError };
