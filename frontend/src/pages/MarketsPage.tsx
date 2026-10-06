import React from 'react';
import { MarketChart } from '../components/MarketChart';
import { MarketSummaryResponse, CandlesResponse, SignalResponse } from '../types/api';
import { formatInstrumentPrice } from '../utils/format';
import './MarketsPage.css';

interface MarketsPageProps {
  summary: MarketSummaryResponse | null;
  candles: CandlesResponse | null;
  symbol: string;
  timeframe: string;
  loading: boolean;
  signal: SignalResponse | null;
  candleError: string | null;
}

export const MarketsPage: React.FC<MarketsPageProps> = ({
  summary,
  candles,
  symbol,
  timeframe,
  loading,
  signal,
  candleError,
}) => {
  const marketSignal = signal?.symbol === symbol ? signal : null;
  const plan = marketSignal?.trade_plan;
  const levelsValid = Boolean(
    plan?.is_valid && plan.signal === marketSignal?.signal &&
    plan.entry != null && plan.stop_loss != null && plan.take_profit != null &&
    [plan.entry, plan.stop_loss, plan.take_profit].every((value) => Number.isFinite(value) && value > 0) &&
    ((marketSignal?.signal === 'BUY' && plan.stop_loss < plan.entry && plan.entry < plan.take_profit) ||
      (marketSignal?.signal === 'SELL' && plan.take_profit < plan.entry && plan.entry < plan.stop_loss)),
  );

  return (
    <div className="dashboard-page-container markets-page">
      <header className="markets-heading"><div><span className="editorial-kicker">Weltrade markets</span><h1>{symbol}</h1></div><span className="markets-timeframe">{timeframe}<small>Closed-candle analysis</small></span></header>
      <div role="status" style={{ display: 'flex', gap: '7px', alignItems: 'center', minHeight: '22px' }}>
        <span className={`badge ${candles?.degraded ? 'badge-neutral' : 'badge-cyan'}`}>
          {candles?.market_data_source?.replace('_', ' ') ?? 'UNAVAILABLE'}
        </span>
        <span className={`badge ${candles?.market_data_status === 'CURRENT' ? 'badge-cyan' : 'badge-neutral'}`}>
          {candles?.market_data_status ?? 'UNAVAILABLE'}
        </span>
        {candles?.stale && <span className="badge badge-neutral">STALE · DEGRADED</span>}
      </div>
      {/* Header Snapshot Row */}
      <div
        className="markets-snapshot"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
          gap: '10px',
        }}
      >
        <div
          style={{
            backgroundColor: 'var(--bg-surface)',
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <div style={{ fontSize: '9.5px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
            LATEST CLOSE ({symbol})
          </div>
          <div className="font-mono" style={{ fontSize: '17px', fontWeight: 800, marginTop: '2px', color: 'var(--text-primary)' }}>
            {summary ? formatInstrumentPrice(summary.latest_close, summary.price_decimals) : '—'}
          </div>
        </div>

        <div
          style={{
            backgroundColor: 'var(--bg-surface)',
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <div style={{ fontSize: '9.5px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
            SPREAD
          </div>
          <div className="font-mono" style={{ fontSize: '17px', fontWeight: 800, color: 'var(--quant-cyan)', marginTop: '2px' }}>
            {summary?.spread != null ? `${summary.spread.toFixed(1)} pts` : '—'}
          </div>
        </div>

        <div
          style={{
            backgroundColor: 'var(--bg-surface)',
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <div style={{ fontSize: '9.5px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
            VOLATILITY (ATR 14)
          </div>
          <div className="font-mono" style={{ fontSize: '17px', fontWeight: 800, color: 'var(--quant-amber)', marginTop: '2px' }}>
            {summary?.atr != null ? summary.atr.toFixed(2) : '—'}
          </div>
        </div>

        <div
          style={{
            backgroundColor: 'var(--bg-surface)',
            padding: '10px 12px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <div style={{ fontSize: '9.5px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)' }}>
            MOMENTUM (RSI 14)
          </div>
          <div
            className="font-mono"
            style={{
              fontSize: '17px',
              fontWeight: 800,
              color: summary?.rsi != null && (summary.rsi > 70 || summary.rsi < 30) ? 'var(--quant-red)' : 'var(--quant-green)',
              marginTop: '2px',
            }}
          >
            {summary?.rsi != null ? summary.rsi.toFixed(1) : '—'}
          </div>
        </div>
      </div>

      <section className={`market-strategy-strip market-strategy-${marketSignal?.signal?.toLowerCase() ?? 'unavailable'}`} aria-label="JQE strategy analysis">
        <div className="market-strategy-decision">
          <span className="market-strategy-eyebrow">JQE strategy</span>
          <strong>{marketSignal?.signal ?? 'UNAVAILABLE'}</strong>
          <span>{marketSignal ? `${marketSignal.confidence}% confidence · ${marketSignal.quality}` : 'No current decision for this market'}</span>
        </div>
        <div className="market-strategy-level">
          <span>Entry</span>
          <strong>{levelsValid && plan?.entry != null ? formatInstrumentPrice(plan.entry, candles?.price_decimals) : '—'}</strong>
        </div>
        <div className="market-strategy-level market-strategy-stop">
          <span>SL</span>
          <strong>{levelsValid && plan?.stop_loss != null ? formatInstrumentPrice(plan.stop_loss, candles?.price_decimals) : '—'}</strong>
        </div>
        <div className="market-strategy-level market-strategy-target">
          <span>TP</span>
          <strong>{levelsValid && plan?.take_profit != null ? formatInstrumentPrice(plan.take_profit, candles?.price_decimals) : '—'}</strong>
        </div>
        <div className="market-strategy-validity">
          <strong>{levelsValid ? 'VALID STRATEGY PLAN' : 'NO VALID PLAN'}</strong>
          <span>Analysis only · not an order authorization</span>
        </div>
      </section>

      <MarketChart
        symbol={symbol}
        timeframe={timeframe}
        candles={candles?.candles || []}
        signal={signal}
        priceDecimals={candles?.price_decimals}
        loading={loading}
        error={candleError}
        dataStatus={candles?.market_data_status}
        height={640}
      />
    </div>
  );
};
