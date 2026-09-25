export interface ResearchSessionDTO {
  id: string;
  dataset: { provider: string; symbol: string; timeframe: string; start: string; end: string; candle_count: number; content_hash: string };
  strategy: Record<string, unknown>;
  volume_metadata: { available: boolean; type: string; source: string };
}
export interface ResearchReplayDTO {
  id: string; cursor: number; complete: boolean;
  candles: { candle_index: number; candle: { time: string; open: number; high: number; low: number; close: number; volume?: number | null };
    indicators: { candle_index: number; timestamp: string; ema50?: number | null; ema200?: number | null; rsi?: number | null; atr?: number | null; regime?: string | null } }[];
  signals: { candle_index: number; timestamp: string; signal: string; confidence: number; state: string; reasons: string[] }[];
  trades: { trade_id: number; entry_index: number; entry_timestamp: string; direction: string; entry_price: number; stop_price: number; target_price: number; exit_index?: number; exit_timestamp?: string; exit_price?: number; net_pnl?: number }[];
  balance_curve: { candle_index: number; timestamp: string; balance: number; drawdown: number; drawdown_percent: number }[];
  metrics?: Record<string, unknown>;
}

export interface VolumeProfileSnapshotDTO {
  dataset_identity: string; range_start_index: number; range_end_index: number;
  start_time: string; end_time: string; candle_count: number;
  volume_type: string; volume_source: string; profile_low: string; profile_high: string;
  total_volume: string; bin_size: string; bin_count: number; value_area_fraction: string;
  allocation_method: string; algorithm_version: string; point_of_control: string;
  value_area_high: string; value_area_low: string; range_has_gaps: boolean; gap_count: number;
  bins: { low: string; high: string; volume: string }[];
}
export interface VolumeProfileResultDTO {
  eligible: boolean; eligibility: string; reason: string; snapshot?: VolumeProfileSnapshotDTO;
}
export interface ExperimentMetricsDTO {
  trade_count: number; win_rate: number; net_pnl: number; expectancy: number;
  profit_factor?: number | null; max_drawdown: number; average_result: number;
  median_result: number; sample_sufficient: boolean;
}
export interface ExperimentComparisonDTO {
  baseline: ExperimentMetricsDTO; variant: ExperimentMetricsDTO;
  deltas: { trade_count_delta: number; net_pnl_delta: number; win_rate_delta: number;
    expectancy_delta: number; profit_factor_delta?: number | null; max_drawdown_delta: number };
}
export interface ResearchExperimentDTO {
  status: string; reason: string; experiment_id: string; dataset_identity: string;
  strategy_identity: string; experiment_version: string; frvp_algorithm_version: string;
  volume_type: string; volume_source: string; split_boundaries: [number, number];
  selected_threshold?: string | null; selection_metric: string;
  conclusion: string;
  train?: ExperimentComparisonDTO | null; validation?: ExperimentComparisonDTO | null;
  out_of_sample?: ExperimentComparisonDTO | null;
}
export interface MarketInstrumentDTO {
  provider: string; provider_symbol: string; canonical_symbol: string; display_name: string;
  market: string; market_display_name?: string | null; subgroup: string; submarket: string;
  submarket_display_name?: string | null; instrument_type: string; pip_size: number;
  exchange_is_open: boolean; is_trading_suspended: boolean; historical_data_supported: string;
  timeframes: string[];
}
export interface ResearchMarketsDTO {
  catalogue: { provider: string; fetched_at?: string | null; instruments: MarketInstrumentDTO[];
    source_status: string; cache_status: string; error?: string | null };
  cached_datasets: { provider: string; canonical_symbol: string; provider_symbol: string;
    timeframe: string; start: string; end: string; candle_count: number; dataset_identity: string;
    volume_type: string; volume_source: string; gap_count: number }[];
  watchlist?: { symbol: string; timeframe: string; scope: string; added_at: string }[];
  watchlist_count?: number;
}

export type AcquisitionState = 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
export interface HistoricalAcquisitionJobDTO {
  job_id: string; request_identity: string; state: AcquisitionState;
  created_at: string; started_at?: string | null; completed_at?: string | null;
  spec: { provider: string; canonical_symbol: string; provider_symbol: string; timeframe: string;
    requested_start: string; requested_end: string; requested_max_candles: number };
  outcome?: { cached_before: number; stored_after: number; inserted: number; duplicates?: number | null;
    gap_count: number; coverage_complete: boolean; first_timestamp?: string | null;
    last_timestamp?: string | null; dataset_hash?: string | null; volume_type?: string | null;
    volume_source?: string | null; provider_received?: number | null; provider_request_count: number } | null;
  error_code?: string | null; error_message?: string | null;
}
