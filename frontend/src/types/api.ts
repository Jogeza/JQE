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
  broker_account_id_masked: string | null;
  broker_account_server: string | null;
  broker_account_currency: string | null;
  broker_account_trade_mode: string | null;
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
  market_data_status: 'CURRENT' | 'CACHED' | 'UNAVAILABLE';
  stale: boolean;
  degraded: boolean;
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
  market_data_status: 'CURRENT' | 'CACHED' | 'UNAVAILABLE';
  stale: boolean;
  degraded: boolean;
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

export type PreciseDecimal = string;

export interface SetupEvidenceDTO {
  factor: string;
  assessment: string;
  score: number;
  maximum_score: number;
}

export interface SetupAuthorizationDTO {
  status: 'AUTHORIZED' | 'BLOCKED' | 'NOT_EVALUATED';
  reason: string;
  reason_codes: string[];
  authorized_risk_amount: PreciseDecimal | null;
  authorized_risk_percent: PreciseDecimal | null;
  quantity: PreciseDecimal | null;
  quantity_unit: string | null;
  expected_loss_at_stop: PreciseDecimal | null;
}

export interface MarketLevelDTO {
  kind: 'SUPPORT' | 'RESISTANCE';
  price: PreciseDecimal;
  method: string;
  name?: string;
}

export interface AnalystExplanation {
  state: 'AVAILABLE' | 'UNAVAILABLE' | string;
  decision_summary: string | null;
  supporting_evidence: string[];
  conflicting_evidence: string[];
  freshness_warning: string | null;
  invalidation_condition: string | null;
  additional_evidence_required: string[];
  method: string;
}

export interface DataFreshnessDTO {
  status: 'CURRENT' | 'CACHED' | 'STALE' | 'UNAVAILABLE';
  source: 'SIMULATION' | 'DERIV_PUBLIC' | 'UNAVAILABLE';
  age_seconds: PreciseDecimal | null;
  maximum_age_seconds: number;
  reason: string;
  latest_closed_candle_at: string | null;
  expected_closed_candle_at: string | null;
  freshness_tolerance_seconds: number | null;
  freshness_age_seconds: PreciseDecimal | null;
  freshness_state: 'FRESH' | 'STALE' | 'FORMING' | 'UNKNOWN';
  freshness_reason_codes: string[];
  reason_codes: string[];
}

export interface HistoricalWinRateDTO {
  status: 'AVAILABLE' | 'UNAVAILABLE';
  win_rate_percent: PreciseDecimal | null;
  sample_size: number | null;
  evaluation_start: string | null;
  evaluation_end: string | null;
  strategy_version: string | null;
  dataset_hash: string | null;
  compatibility_state: 'COMPATIBLE' | 'INCOMPATIBLE' | 'UNVERIFIED';
  reason: string;
}

export interface MarketSetup {
  setup_id: string;
  symbol: string;
  timeframe: string;
  observed_at: string;
  candle_close_time: string;
  expires_at: string | null;
  direction: 'BUY' | 'SELL' | 'NO_TRADE';
  setup_state: 'FORMING' | 'READY' | 'BLOCKED' | 'EXPIRED' | 'EXECUTED';
  entry_price: PreciseDecimal | null;
  stop_loss: PreciseDecimal | null;
  targets: PreciseDecimal[];
  levels: MarketLevelDTO[];
  analyzed_candle_time: string | null;
  risk_reward_ratio: PreciseDecimal | null;
  confidence_score: number;
  confidence_method: string;
  evidence: SetupEvidenceDTO[];
  conflicts: string[];
  market_regime: string;
  invalidation_condition: string | null;
  data_freshness: DataFreshnessDTO;
  risk_authorization: SetupAuthorizationDTO;
  execution_authorization: SetupAuthorizationDTO;
  reason_codes: string[];
  historical_win_rate: HistoricalWinRateDTO;
  explanation?: AnalystExplanation | null;
  schema_version: number;
  dataset_source?: string | null;
  dataset_seed?: number | null;
  dataset_hash?: string | null;
  dataset_first_candle?: string | null;
  dataset_last_candle?: string | null;
}

export interface ActiveMarketContext {
  canonical_symbol: string;
  provider_symbol: string;
  display_name: string;
  selected_timeframe: string;
  timeframe_seconds: number;
  latest_stored_candle_close: string | null;
  expected_latest_closed_candle: string;
  market_data_observation_time: string;
  strategy_evaluation_time: string;
  setup_creation_time: string;
  setup_expiry_time: string;
  data_source: 'SIMULATION' | 'DERIV_PUBLIC' | 'UNAVAILABLE';
  cache_status: 'REFRESHED' | 'FRESH_CACHE' | 'CACHE_ONLY' | 'EMPTY';
  synchronization_state: 'SYNCHRONIZED' | 'STALE' | 'FORMING' | 'UNKNOWN';
  reason_codes: string[];
  latest_closed_candle_at: string | null;
  expected_closed_candle_at: string;
  freshness_age_seconds: PreciseDecimal | null;
  freshness_tolerance_seconds: number;
  freshness_state: 'FRESH' | 'STALE' | 'FORMING' | 'UNKNOWN';
  freshness_reason_codes: string[];
  schema_version: number;
}

export interface ActiveMarketAnalysisResponse {
  context: ActiveMarketContext;
  market: MarketSummaryResponse;
  candles: CandlesResponse;
  signal: SignalResponse;
  setup: MarketSetup;
  explanation: AnalystExplanation;
}

export interface PaperExecutionOutcomeDTO {
  outcome_id: string;
  setup_id: string;
  recorded_at: string;
  status: 'OPENED' | 'BLOCKED' | 'ALREADY_RECORDED' | 'UNKNOWN';
  setup_state: 'READY' | 'BLOCKED' | 'EXPIRED' | 'EXECUTED';
  order_id: string | null;
  execution_price: PreciseDecimal | null;
  quantity: PreciseDecimal | null;
  quantity_unit: string | null;
  realized_pnl: PreciseDecimal | null;
  close_reason: string | null;
  reason_codes: string[];
  message: string;
  paper_only: true;
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

export type MonitoringState = 'LIVE' | 'FRESH' | 'STALE' | 'OFFLINE' | 'UNAVAILABLE' | 'BLOCKED';

export interface MonitoringGateDTO {
  state: MonitoringState;
  value: string;
  observed_at: string | null;
  source: string;
  reason_codes: string[];
}

export interface OfflineMonitoringResponse {
  schema_version: number;
  mode: 'OFFLINE_SIMULATION';
  observed_at: string;
  environment: string;
  backend: MonitoringGateDTO;
  strategy: MonitoringGateDTO;
  candle_freshness: MonitoringGateDTO;
  risk: MonitoringGateDTO;
  execution_authorization: MonitoringGateDTO;
  simulation_submissions: {
    state: 'FRESH' | 'BLOCKED' | 'UNAVAILABLE';
    account_scope: string;
    utc_count: number;
    limit: number;
    utc_date: string;
    reset_at: string;
    reason_codes: string[];
  };
  broker_execution_enabled: false;
  assessment: MarketSetup | null;
}

export interface ObservationHealthResponse {
  running: boolean;
  healthy: boolean;
  updated_at: string;
  last_success_at: string | null;
  last_error: string | null;
  cycles_completed: number;
  session_id: string;
}

export interface ObservationHealthResponse {
  running: boolean;
  healthy: boolean;
  updated_at: string;
  last_success_at: string | null;
  last_error: string | null;
  cycles_completed: number;
  session_id: string;
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

export interface BrokerItemStatusDTO {
  broker: string;
  name: string;
  is_active: boolean;
  connected: boolean;
  is_configured: boolean;
  is_available: boolean;
  error_message: string | null;
  can_switch: boolean;
  switch_blocked_reason: string | null;
  demo_guard_status: string; // 'PASSED' | 'FAILED' | 'UNVERIFIED'
  demo_guard_verified_at: string | null;
  account_id_masked: string | null;
  account_server: string | null;
  account_currency: string | null;
  account_trade_mode: string | null;
  environment: string | null;
  notes?: string | null;
}

export interface ActiveBrokerIdentityDTO {
  broker: string;
  account_id_masked: string | null;
  server: string | null;
  trade_mode: string;
  currency: string | null;
  verified_at: string | null;
  demo_guard_passed: boolean;
}

export interface BrokerStatusResponse {
  brokers: BrokerItemStatusDTO[];
  active_broker: string;
  active_broker_identity: ActiveBrokerIdentityDTO | null;
  emergency_stop_state: string;
  execution_authorization: string;
  observed_at: string | null;
  observation_state: string;
  can_switch: boolean;
  switch_blocked_reason: string | null;
  unresolved_intent_count: number;
  broker: string;
  environment: string;
  connected: boolean;
  last_verified_at: string | null;
  identity_state: string;
  account_id_masked: string | null;
  account_server: string | null;
  account_currency: string | null;
  account_trade_mode: string | null;
}

export interface SelectBrokerRequest {
  broker: string;
  reason?: string;
}

export interface SelectBrokerResponse {
  selected_broker: string;
  persisted: boolean;
  status: BrokerStatusResponse;
}

export interface WatchlistItemDTO {
  symbol: string;
  timeframe: string;
  scope: string;
  added_at: string;
}

export interface WatchlistResponse {
  items: WatchlistItemDTO[];
  count: number;
}

export interface WatchlistCapUsageDTO {
  symbol: string;
  timeframe: string;
  scope: string;
  daily_count: number;
  daily_limit: number;
  daily_remaining: number;
  utc_date: string;
  reset_at: string;
  available: boolean;
}

export interface WatchlistCapUsageResponse {
  items: WatchlistCapUsageDTO[];
  observed_at: string;
}
