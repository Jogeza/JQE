import React from 'react';
import { MarketChart } from '../components/MarketChart';
import { MarketSummaryResponse, CandlesResponse } from '../types/api';
import { formatInstrumentPrice } from '../utils/format';

interface MarketsPageProps {
  summary: MarketSummaryResponse | null;
  candles: CandlesResponse | null;
  symbol: string;
  timeframe: string;
  loading: boolean;
}

export const MarketsPage: React.FC<MarketsPageProps> = ({
  summary,
  candles,
  symbol,
  timeframe,
  loading,
}) => {
  return (
    <div className="dashboard-page-container">
      {/* Header Snapshot */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: '10px',
        }}
      >
        <div style={{ backgroundColor: 'var(--bg-surface)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>LATEST CLOSE ({symbol})</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 800, marginTop: '2px' }}>
              {summary ? formatInstrumentPrice(summary.latest_close, summary.price_decimals) : '—'}
          </div>
        </div>

        <div style={{ backgroundColor: 'var(--bg-surface)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>SPREAD</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--quant-cyan)', marginTop: '2px' }}>
            {summary ? `${summary.spread.toFixed(1)} pts` : '—'}
          </div>
        </div>

        <div style={{ backgroundColor: 'var(--bg-surface)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>VOLATILITY (ATR 14)</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 700, color: 'var(--quant-amber)', marginTop: '2px' }}>
            {summary ? summary.atr.toFixed(2) : '—'}
          </div>
        </div>

        <div style={{ backgroundColor: 'var(--bg-surface)', padding: '12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>MOMENTUM (RSI 14)</div>
          <div className="font-mono" style={{ fontSize: '18px', fontWeight: 700, color: summary && (summary.rsi > 70 || summary.rsi < 30) ? 'var(--quant-red)' : 'var(--quant-green)', marginTop: '2px' }}>
            {summary ? summary.rsi.toFixed(1) : '—'}
          </div>
        </div>
      </div>

      {/* Main Chart */}
      <MarketChart
        symbol={symbol}
        timeframe={timeframe}
        candles={candles?.candles || []}
        priceDecimals={candles?.price_decimals}
        loading={loading}
      />
    </div>
  );
};
