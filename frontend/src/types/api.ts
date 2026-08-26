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
}

export interface MarketSummaryResponse {
  symbol: string;
  timeframe: string;
  latest_close: number;
  latest_high: number;
  latest_low: number;
  latest_open: number;
  spread: number;
  atr: number;
  rsi: number;
  ema50: number | null;
  ema200: number | null;
  timestamp: string | null;
  price_decimals: number;
}

export interface CandleItemDTO {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
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

export interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  stale: boolean;
}
