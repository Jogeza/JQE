import React from 'react';
import { LineChart as PerformanceIcon } from 'lucide-react';
import { PerformanceSummaryResponse, TradeHistoryDTO } from '../types/api';
import { formatMoney } from '../utils/format';

interface PerformanceSectionProps {
  performance: PerformanceSummaryResponse | null;
  trades: TradeHistoryDTO[];
  loading?: boolean;
  currency?: string;
}

export const PerformanceSection: React.FC<PerformanceSectionProps> = ({ performance, trades, loading, currency }) => {
  const missing = loading ? '...' : '—';
  const metricStyle = { backgroundColor: 'var(--bg-app)', padding: '10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' };
  const rowStyle = { display: 'flex', justifyContent: 'space-between', padding: '6px 10px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)' };
  return (
    <div className="quant-panel">
      <div className="quant-panel-header"><div className="quant-panel-title"><PerformanceIcon size={14} color="var(--quant-cyan)" /><span>Quantitative Performance Analytics</span></div><span className="badge badge-neutral">API SUMMARY</span></div>
      <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
          <div style={metricStyle}><div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>WIN RATE</div><div className="font-mono" style={{ fontSize: '16px', fontWeight: 700, marginTop: '2px' }}>{performance ? `${performance.win_rate_percent.toFixed(1)}%` : missing}</div></div>
          <div style={metricStyle}><div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>PROFIT FACTOR</div><div className="font-mono" style={{ fontSize: '16px', fontWeight: 700, marginTop: '2px' }}>{performance ? performance.profit_factor.toFixed(2) : missing}</div></div>
          <div style={metricStyle}><div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>NET REALIZED P&amp;L</div><div className="font-mono" style={{ fontSize: '16px', fontWeight: 700, marginTop: '2px', color: performance && performance.net_profit < 0 ? 'var(--quant-red)' : 'var(--quant-green)' }}>{performance ? formatMoney(performance.net_profit, currency, true) : missing}</div></div>
          <div style={metricStyle}><div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>MAX DRAWDOWN (AMOUNT)</div><div className="font-mono" style={{ fontSize: '16px', fontWeight: 700, marginTop: '2px', color: 'var(--quant-red)' }}>{performance ? formatMoney(-Math.abs(performance.max_drawdown_amount), currency) : missing}</div></div>
          <div style={metricStyle}><div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>MAX DRAWDOWN (%)</div><div className="font-mono" style={{ fontSize: '16px', fontWeight: 700, marginTop: '2px', color: 'var(--quant-red)' }}>{performance?.max_drawdown_percent === null ? 'UNAVAILABLE' : performance ? `${performance.max_drawdown_percent.toFixed(2)}%` : missing}</div></div>
          <div style={metricStyle}><div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>TOTAL EXECUTIONS</div><div className="font-mono" style={{ fontSize: '16px', fontWeight: 700, marginTop: '2px' }}>{performance?.total_trades ?? missing}</div></div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
          <div style={rowStyle}><span style={{ color: 'var(--text-muted)' }}>Gross Profit:</span><span style={{ color: 'var(--quant-green)', fontWeight: 600 }}>{performance ? formatMoney(performance.gross_profit, currency, true) : missing}</span></div>
          <div style={rowStyle}><span style={{ color: 'var(--text-muted)' }}>Gross Loss:</span><span style={{ color: 'var(--quant-red)', fontWeight: 600 }}>{performance ? formatMoney(-Math.abs(performance.gross_loss), currency) : missing}</span></div>
          <div style={rowStyle}><span style={{ color: 'var(--text-muted)' }}>Average Execution P&amp;L:</span><span style={{ fontWeight: 600 }}>{performance ? formatMoney(performance.average_trade, currency) : missing}</span></div>
        </div>
        <div style={{ padding: '14px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', textAlign: 'center', color: 'var(--text-dim)', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>DRAWDOWN AMOUNT: REALIZED P&amp;L, {performance?.drawdown_amount_unit || 'UNIT UNAVAILABLE'} · DRAWDOWN % REQUIRES HISTORICAL EQUITY · {trades.length} RECENT CLOSED EXECUTION{trades.length === 1 ? '' : 'S'}</div>
      </div>
    </div>
  );
};
