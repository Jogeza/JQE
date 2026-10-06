import React, { Fragment, useState } from 'react';
import { History, ArrowUpRight, ArrowDownRight, X } from 'lucide-react';
import { TradeHistoryDTO } from '../types/api';
import { formatInstrumentPrice, formatMoney, formatUtcDateTime, utcDayKey } from '../utils/format';

interface RecentTradesTableProps {
  trades: TradeHistoryDTO[];
  loading?: boolean;
  currency?: string;
  broker?: string;
  dayFilter?: string | null;
  onClearDayFilter?: () => void;
}

export const RecentTradesTable: React.FC<RecentTradesTableProps> = ({ trades, loading, currency, broker, dayFilter, onClearDayFilter }) => {
  const [openId, setOpenId] = useState<string | null>(null);
  const formatTime = (timeStr: string) => {
    const d = new Date(timeStr);
    if (Number.isNaN(d.getTime())) return timeStr || '—';
    return d.toLocaleTimeString('en-GB', { hour12: false }) + ' ' + d.toLocaleDateString('en-GB', { day: '2-digit', month: '2-digit' });
  };

  const visible = dayFilter ? trades.filter((trade) => utcDayKey(trade.close_time) === dayFilter) : trades;

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <History size={14} color="var(--quant-cyan)" />
          <span>Execution History ({dayFilter ? `${visible.length} of ${trades.length}` : trades.length})</span>
        </div>
        <div className="trade-table-heading-right">
          {dayFilter && (
            <span className="trade-day-filter">
              {dayFilter} UTC
              {onClearDayFilter && (
                <button type="button" aria-label="Clear day filter" onClick={onClearDayFilter}>
                  <X size={11} />
                </button>
              )}
            </span>
          )}
          <span className="badge badge-neutral">{broker?.toLowerCase() === 'weltrade' ? 'WELTRADE MT5 HISTORY' : 'BROKER SOURCE UNAVAILABLE'}</span>
        </div>
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
            {visible.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                  {loading
                    ? 'Fetching trade history...'
                    : dayFilter ? `NO CLOSED TRADES ON ${dayFilter} (UTC)` : 'NO RECENT EXECUTED TRADES FOUND'}
                </td>
              </tr>
            ) : (
              visible.map((t) => {
                const isBuy = t.side.toUpperCase() === 'BUY';
                const isWin = t.profit >= 0;
                const open = openId === t.id;
                const toggle = () => setOpenId(open ? null : t.id);

                return (
                  <Fragment key={t.id}>
                    <tr
                      className={`trade-row${open ? ' is-open' : ''}`}
                      tabIndex={0}
                      aria-expanded={open}
                      onClick={toggle}
                      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }}
                    >
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
                    {open && (
                      <tr className="trade-detail-row">
                        <td colSpan={8}>
                          <div className="trade-detail">
                            <span><em>Trade ID</em>#{t.id}</span>
                            <span><em>Side</em>{t.side}</span>
                            <span><em>Volume</em>{t.volume.toFixed(2)}</span>
                            <span><em>Realized P&L</em>{formatMoney(t.profit, currency, true)}</span>
                            <span><em>Open price</em>{formatInstrumentPrice(t.open_price, t.price_decimals)}</span>
                            <span><em>Close price</em>{formatInstrumentPrice(t.close_price, t.price_decimals)}</span>
                            <span><em>Open time</em>{formatUtcDateTime(t.open_time)}</span>
                            <span><em>Close time</em>{formatUtcDateTime(t.close_time)}</span>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
