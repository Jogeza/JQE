import React, { useMemo } from 'react';
import { BarChart3 } from 'lucide-react';
import { TradeHistoryDTO } from '../types/api';
import { formatMoney, utcDayKey } from '../utils/format';

interface PnlSummaryProps {
  trades: TradeHistoryDTO[];
  currency?: string;
}

const roundCents = (value: number) => Math.round(value * 100) / 100;

export const PnlSummary: React.FC<PnlSummaryProps> = ({ trades, currency }) => {
  const stats = useMemo(() => {
    let profit = 0;
    let wins = 0;
    let losses = 0;
    const byDay = new Map<string, number>();
    for (const trade of trades) {
      profit += trade.profit;
      if (trade.profit > 0) wins += 1;
      else if (trade.profit < 0) losses += 1;
      const key = utcDayKey(trade.close_time);
      if (key) byDay.set(key, (byDay.get(key) ?? 0) + trade.profit);
    }
    const days = [...byDay.entries()].map(([key, value]) => ({ key, value: roundCents(value) }));
    const best = days.length ? days.reduce((a, b) => (b.value > a.value ? b : a)) : null;
    const worst = days.length ? days.reduce((a, b) => (b.value < a.value ? b : a)) : null;
    return { profit: roundCents(profit), wins, losses, closed: trades.length, best, worst };
  }, [trades]);

  const format = (value: number) => currency
    ? formatMoney(value, currency, value !== 0)
    : `${value > 0 ? '+' : ''}${value.toFixed(2)}`;
  const tone = (value: number) => value === 0 ? 'is-flat' : value > 0 ? 'is-profit' : 'is-loss';
  const winRate = stats.wins + stats.losses > 0
    ? `${Math.round((stats.wins / (stats.wins + stats.losses)) * 100)}%`
    : '—';

  return (
    <div className="quant-panel pnl-summary-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <BarChart3 size={14} color="var(--quant-cyan)" />
          <span>Realized P&amp;L</span>
        </div>
        <span className="badge badge-neutral">30-DAY BROKER WINDOW (UTC)</span>
      </div>
      <div className="quant-panel-body">
        <div className="pnl-summary-grid">
          <div className="pnl-stat">
            <span className="pnl-stat-label">Window total</span>
            <span className={`pnl-stat-value ${stats.closed === 0 ? 'is-flat' : tone(stats.profit)}`}>
              {stats.closed === 0 ? '—' : format(stats.profit)}
            </span>
            <span className="pnl-stat-detail">{stats.closed} closed execution{stats.closed === 1 ? '' : 's'}</span>
          </div>
          <div className="pnl-stat">
            <span className="pnl-stat-label">Win rate</span>
            <span className={`pnl-stat-value ${stats.wins + stats.losses === 0 ? 'is-flat' : 'is-neutral'}`}>{winRate}</span>
            <span className="pnl-stat-detail">{stats.wins} win{stats.wins === 1 ? '' : 's'} · {stats.losses} loss{stats.losses === 1 ? '' : 'es'}</span>
          </div>
          <div className="pnl-stat">
            <span className="pnl-stat-label">Best day</span>
            <span className={`pnl-stat-value ${stats.best ? tone(stats.best.value) : 'is-flat'}`}>
              {stats.best ? format(stats.best.value) : '—'}
            </span>
            <span className="pnl-stat-detail">{stats.best ? `${stats.best.key} (UTC)` : 'no closed days'}</span>
          </div>
          <div className="pnl-stat">
            <span className="pnl-stat-label">Worst day</span>
            <span className={`pnl-stat-value ${stats.worst ? tone(stats.worst.value) : 'is-flat'}`}>
              {stats.worst ? format(stats.worst.value) : '—'}
            </span>
            <span className="pnl-stat-detail">{stats.worst ? `${stats.worst.key} (UTC)` : 'no closed days'}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
