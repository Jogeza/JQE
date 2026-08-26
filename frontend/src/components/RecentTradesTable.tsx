import React from 'react';
import { History, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { TradeHistoryDTO } from '../types/api';
import { formatInstrumentPrice, formatMoney } from '../utils/format';

interface RecentTradesTableProps {
  trades: TradeHistoryDTO[];
  loading?: boolean;
  currency?: string;
}

export const RecentTradesTable: React.FC<RecentTradesTableProps> = ({ trades, loading, currency }) => {
  const formatTime = (timeStr: string) => {
    const d = new Date(timeStr);
    if (Number.isNaN(d.getTime())) return timeStr || '—';
    return d.toLocaleTimeString('en-GB', { hour12: false }) + ' ' + d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' });
  };

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <History size={14} color="var(--quant-cyan)" />
          <span>Execution History ({trades.length})</span>
        </div>
        <span className="badge badge-neutral">API HISTORY</span>
      </div>

      <div className="quant-table-wrapper">
        <table className="quant-table">
          <thead>
            <tr>
              <th>Close Time</th>
              <th>Trade ID</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Volume</th>
              <th>Open Price</th>
              <th>Close Price</th>
              <th style={{ textAlign: 'right' }}>Realized P&L</th>
            </tr>
          </thead>
          <tbody>
            {trades.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                  {loading ? 'Fetching trade history...' : 'NO RECENT EXECUTED TRADES FOUND'}
                </td>
              </tr>
            ) : (
              trades.map((t) => {
                const isBuy = t.side.toUpperCase() === 'BUY';
                const isWin = t.profit >= 0;

                return (
                  <tr key={t.id}>
                    <td style={{ color: 'var(--text-secondary)' }}>{formatTime(t.close_time)}</td>
                    <td style={{ color: 'var(--text-dim)' }}>#{t.id}</td>
                    <td style={{ fontWeight: 700 }}>{t.symbol}</td>
                    <td>
                      <span className={`badge ${isBuy ? 'badge-green' : 'badge-red'}`} style={{ padding: '1px 5px' }}>
                        {isBuy ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                        {t.side}
                      </span>
                    </td>
                    <td>{t.volume.toFixed(2)}</td>
                    <td>{formatInstrumentPrice(t.open_price, t.price_decimals)}</td>
                    <td>{formatInstrumentPrice(t.close_price, t.price_decimals)}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700, color: isWin ? 'var(--quant-green)' : 'var(--quant-red)' }}>
                      {formatMoney(t.profit, currency, true)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
