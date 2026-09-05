import React from 'react';
import { MarketChart } from '../components/MarketChart';
import { MarketSummaryResponse, CandlesResponse, SignalResponse } from '../types/api';
import { formatInstrumentPrice } from '../utils/format';

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
  return (
    <div className="dashboard-page-container">
      {/* Header Snapshot Row */}
      <div
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

      {/* Main Quantitative Market Chart */}
      <MarketChart
        symbol={symbol}
        timeframe={timeframe}
        candles={candles?.candles || []}
        signal={signal}
        priceDecimals={candles?.price_decimals}
        loading={loading}
        error={candleError}
        height={520}
      />
    </div>
  );
};
