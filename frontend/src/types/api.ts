/**
 * JQE Quantitative Trading Terminal — TypeScript API Types
 * Strictly mirrors the backend Pydantic DTOs in api/dto.py.
 */

export interface SystemStatusResponse {
  environment: 'development' | 'demo' | 'production' | string;
  broker: 'simulation' | 'deriv' | 'mt5' | string;
  broker_connected: boolean;
  default_symbol: string;
  default_timeframe: string;
  min_confidence_threshold: number;
  server_time: string;
  status: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | string;
  telegram_enabled: boolean;
  telegram_configured: boolean;
  telegram_status: 'READY' | 'DISABLED' | 'UNAVAILABLE' | string;
}

export interface MarketSummaryResponse {
  symbol: string;
  timeframe: string;
  latest_close: number;
  latest_high: number;
  latest_low: number;
  latest_open: number;
  spread: number | null;
  atr: number | null;
  rsi: number | null;
  ema50: number | null;
  ema200: number | null;
  timestamp: string | null;
  price_decimals: number;
  market_data_source: 'SIMULATION' | 'DERIV_PUBLIC' | 'UNAVAILABLE';
}

export interface CandleItemDTO {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  EMA50: number | null;
  EMA200: number | null;
  RSI: number | null;
  ATR: number | null;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: string;
  count: number;
  candles: CandleItemDTO[];
  price_decimals: number;
  market_data_source: 'SIMULATION' | 'DERIV_PUBLIC' | 'UNAVAILABLE';
}

export interface ConfidenceBreakdownDTO {
  trend_score: number;
  structure_score: number;
  liquidity_score: number;
  momentum_score: number;
  volatility_score: number;
  risk_score: number;
  total: number;
  factors: Record<string, string>;
}

export interface TradePlanDTO {
  symbol: string;
  signal: 'BUY' | 'SELL' | 'NO_TRADE';
  confidence: number;
  quality: string;
  score: number;
  setup_type: string;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  risk_reward: number | null;
  position_size: number | null;
  risk_percent: number | null;
  risk_amount: number | null;
  invalidation: string | null;
  warnings: string[];
  reasons: string[];
  is_valid: boolean;
}

export interface SignalResponse {
  symbol: string;
  signal: 'BUY' | 'SELL' | 'NO_TRADE';
  confidence: number;
  quality: string;
  score: number;
  reasons: string[];
  regime: string;
  trend: string;
  momentum: string;
  volatility: string;
  liquidity: string;
  confidence_breakdown: ConfidenceBreakdownDTO | null;
  trade_plan: TradePlanDTO | null;
  generated_at: string | null;
  price_decimals: number;
}

export interface RiskStatusResponse {
  balance: number;
  equity: number;
  currency: string;
  max_daily_loss: number;
  max_trades_daily: number;
  daily_trades_count: number;
  daily_loss_percent: number;
  risk_allowed: boolean;
  risk_message: string;
  approved: boolean;
  rejection_reason: string;
  observation_available: boolean;
  observation_timestamp: string | null;
  observation_age_seconds: number | null;
  observation_fresh: boolean;
  observation_status: 'FRESH' | 'STALE' | 'NOT_OBSERVED' | 'UNAVAILABLE' | 'CONTEXT_MISMATCH';
  observation_reason: string;
  risk_authorized: boolean;
  authorized_risk_amount: number | null;
  authorized_risk_percent: number | null;
  execution_quantity_available: boolean;
  execution_quantity_value: number | null;
  execution_quantity_unit: string | null;
  execution_quantity_reason: string | null;
  /** @deprecated Compatibility only; always zero and never executable. */
  recommended_lot_size: number;
  risk_percent: number;
}

export interface PositionDTO {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL' | string;
  volume: number;
  open_price: number;
  current_price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  profit: number;
  price_decimals: number;
}

export interface TradeHistoryDTO {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL' | string;
  volume: number;
  open_price: number;
  close_price: number;
  profit: number;
  open_time: string;
  close_time: string;
  price_decimals: number;
}

export interface ExecutionStateResponse {
  broker: string;
  connected: boolean;
  open_positions_count: number;
  positions: PositionDTO[];
  recent_trades_count: number;
  recent_trades: TradeHistoryDTO[];
  currency: string;
}

export interface ExecutionSafetyResponse {
  schema_version: number | null;
  observed_at: string | null;
  observation_state: 'OBSERVED' | 'NOT_OBSERVED' | 'UNAVAILABLE' | 'STALE';
  emergency_stop_state: 'CLEAR' | 'ACTIVE' | 'UNKNOWN';
  execution_mode: 'DURABLE' | null;
  broker: string | null;
  environment: string | null;
  durable_executor_enabled: boolean | null;
  daily_state_authority: 'AUTHORITATIVE' | 'NOT_AUTHORITATIVE' | 'NOT_EVALUATED' | 'UNKNOWN';
  unresolved_intent_count: number | null;
  unresolved_intent_blocked: boolean | null;
  execution_authorization: 'AUTHORIZED' | 'BLOCKED' | 'NOT_EVALUATED' | 'UNKNOWN';
  reason_codes: string[];
}

export interface RecoveryQuantity {
  value: number;
  unit: string;
}

export interface RecoveryIntentDiagnostic {
  idempotency_key: string;
  intent_state: 'PENDING' | 'UNKNOWN';
  broker: string | null;
  account_id: string | null;
  symbol: string | null;
  side: string | null;
  quantity: RecoveryQuantity | null;
  entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  authorized_risk_amount: number | null;
  expected_loss_at_stop: number | null;
  order_id: string | null;
  transaction_id: string | null;
  created_at: string;
  updated_at: string;
  reconstruction_valid: boolean;
  recovery_outcome: string;
  reconciliation_classification: string;
  blocking_reason: string;
  execution_blocked: boolean;
}

export interface RecoveryDiagnosticsResponse {
  status: 'CLEAR' | 'BLOCKED' | 'UNKNOWN';
  unresolved_intent_count: number;
  execution_blocked: boolean;
  reason: string;
  intents: RecoveryIntentDiagnostic[];
}

export interface PaperRuntimeStatusResponse {
  runtime_mode: string;
  running: boolean;
  started_at: string | null;
  last_cycle_at: string | null;
  last_processed_observation: string | null;
  symbols_monitored: string[];
  open_paper_positions: number;
  cycles_completed: number;
  last_signal: string | null;
  last_action: string;
  last_error: string | null;
  notification_state: string;
  shutdown_state: string;
  paper_execution_enabled: boolean;
  broker_execution_enabled: boolean;
}

export interface PaperDiagnosticsResponse {
  status: string;
  sample_size_insufficient: boolean;
  session?: {
    session_id: string;
    started_at: string;
    ended_at: string | null;
    runtime_mode: string;
    source_mode: string;
    symbols: string[];
    timeframes: string[];
    dataset_identity: string | null;
  };
  metrics?: {
    observations: number;
    signals: number;
    confirmations: number;
    authorized_entries: number;
    opened_positions: number;
    closed_positions: number;
    directions: Record<string, number>;
    block_reasons: Record<string, number>;
    net_pnl: string | null;
    average_r: string | null;
    max_drawdown: string | null;
    by_regime: Record<string, { observations: number; signals: number; entries: number; closed_trades: number; net_pnl: string; average_r: string | null; block_reasons: Record<string, number> }>;
    by_volatility: Record<string, { count: number }>;
    by_momentum: Record<string, { count: number }>;
    rejection_layers: Record<string, number>;
    sample_sufficiency: Record<string, boolean>;
    funnel: {
      observations: number;
      raw_signals: number;
      confirmed: number;
      risk_authorized: number;
      opened: number;
      closed: number;
      raw_signal_rate: string | null;
      confirmation_rate: string | null;
      authorization_rate: string | null;
      entry_rate: string | null;
    };
  };
}

export interface PerformanceSummaryResponse {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate_percent: number;
  profit_factor: number;
  max_drawdown_amount: number;
  max_drawdown_percent: number | null;
  drawdown_amount_unit: 'account_currency' | string;
  drawdown_percent_unit: 'percent' | string;
  currency: string | null;
  average_trade: number;
  gross_profit: number;
  gross_loss: number;
  net_profit: number;
}

export type ExperimentStatus = 'COMPLETED' | 'LEGACY_INCOMPLETE';

export type ExperimentComparisonClassification =
  | 'IDENTICAL_RESULT'
  | 'SAME_RUN_CONFIGURATION_DIFFERENT_OBSERVATION'
  | 'SAME_DATASET_DIFFERENT_CONFIGURATION'
  | 'DIFFERENT_DATASET'
  | 'LEGACY_OR_INCOMPLETE';

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface ExperimentDiscoveryIssueDTO {
  file_name: string;
  code: 'INVALID_EXPERIMENT_RECORD' | string;
  message: string;
}

export interface ExperimentSummaryDTO {
  experiment_id: string;
  status: ExperimentStatus;
  created_at: string;
  symbol: string;
  timeframe: string;
  effective_start: string;
  effective_end: string;
  candle_count: number;
  dataset_hash: string | null;
  run_fingerprint: string | null;
  result_hash: string | null;
  engine_version: string | null;
  identity_schema_version: number | null;
  initial_capital: number | null;
  ending_capital: number | null;
  total_return: number | null;
  total_trades: number | null;
  fully_reproducible: boolean;
}

export interface ExperimentListResponse {
  experiments: ExperimentSummaryDTO[];
  issues: ExperimentDiscoveryIssueDTO[];
  total: number;
  limit: number;
  offset: number;
}

export interface ExperimentDetailDTO {
  schema_version: number;
  experiment_id: string;
  status: ExperimentStatus;
  created_at: string;
  dataset_hash: string | null;
  run_fingerprint: string | null;
  result_hash: string | null;
  engine_version: string | null;
  identity_schema_version: number | null;
  symbol: string;
  timeframe: string;
  partition: string;
  partition_first_candle: string;
  partition_last_candle: string;
  partition_candle_count: number;
  strategy_name: string;
  configuration: Record<string, JsonValue>;
  metrics: Record<string, JsonValue>;
  provenance: Record<string, JsonValue>;
}

export interface ExperimentComparisonResponse {
  left_experiment_id: string;
  right_experiment_id: string;
  classification: ExperimentComparisonClassification;
  controlled_comparison: boolean;
  both_fully_reproducible: boolean;
  same_dataset: boolean;
  same_run_configuration: boolean;
  same_result: boolean;
  same_strategy_configuration: boolean;
  same_risk_configuration: boolean;
  same_execution_assumptions: boolean;
  metric_deltas: Record<string, number | null>;
}

export interface ExperimentListFilters {
  symbol?: string;
  timeframe?: string;
  status?: ExperimentStatus;
  fully_reproducible?: boolean;
  dataset_hash?: string;
  run_fingerprint?: string;
  limit?: number;
  offset?: number;
}

export interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  stale: boolean;
}
