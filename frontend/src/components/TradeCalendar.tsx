import React, { useMemo, useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { TradeHistoryDTO } from '../types/api';
import { formatMoney, utcDayKey } from '../utils/format';

interface TradeCalendarProps {
  trades: TradeHistoryDTO[];
  currency?: string;
  selectedDay?: string | null;
  onSelectDay?: (day: string | null) => void;
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

export const TradeCalendar: React.FC<TradeCalendarProps> = ({ trades, currency, selectedDay, onSelectDay }) => {
  const initial = new Date();
  const [view, setView] = useState({ year: initial.getUTCFullYear(), month: initial.getUTCMonth() });

  const byDay = useMemo(() => {
    const map = new Map<string, { profit: number; count: number }>();
    for (const trade of trades) {
      const key = utcDayKey(trade.close_time);
      if (!key) continue;
      const cell = map.get(key) ?? { profit: 0, count: 0 };
      cell.profit += trade.profit;
      cell.count += 1;
      map.set(key, cell);
    }
    return map;
  }, [trades]);

  const monthKey = `${view.year}-${String(view.month + 1).padStart(2, '0')}`;
  const daysInMonth = new Date(Date.UTC(view.year, view.month + 1, 0)).getUTCDate();
  const leadingBlanks = (new Date(Date.UTC(view.year, view.month, 1)).getUTCDay() + 6) % 7;
  const cells: Array<number | null> = [
    ...Array.from({ length: leadingBlanks }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => index + 1),
  ];
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: Array<Array<number | null>> = [];
  for (let index = 0; index < cells.length; index += 7) weeks.push(cells.slice(index, index + 7));

  const monthEntries = [...byDay.entries()].filter(([key]) => key.startsWith(monthKey));
  const monthProfit = Math.round(monthEntries.reduce((total, [, cell]) => total + cell.profit, 0) * 100) / 100;
  const monthTrades = monthEntries.reduce((total, [, cell]) => total + cell.count, 0);
  const todayKey = new Date().toISOString().slice(0, 10);
  const monthLabel = `${MONTH_NAMES[view.month]} ${view.year}`;

  const step = (delta: number) => setView(current => {
    const date = new Date(Date.UTC(current.year, current.month + delta, 1));
    return { year: date.getUTCFullYear(), month: date.getUTCMonth() };
  });

  const formatCell = (value: number) => currency
    ? formatMoney(value, currency, value !== 0)
    : `${value > 0 ? '+' : ''}${value.toFixed(2)}`;

  return (
    <div className="quant-panel trade-calendar-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <CalendarDays size={14} color="var(--quant-cyan)" />
          <span>Monthly P&amp;L</span>
        </div>
        <div className="trade-calendar-nav">
          <button type="button" className="trade-calendar-step" aria-label="Previous month" onClick={() => step(-1)}>
            <ChevronLeft size={14} />
          </button>
          <span className="trade-calendar-month" aria-live="polite">{monthLabel}</span>
          <button type="button" className="trade-calendar-step" aria-label="Next month" onClick={() => step(1)}>
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
      <div className="quant-panel-body">
        <table className="trade-calendar" aria-label="Monthly realized P&L by UTC day">
          <thead>
            <tr>{WEEKDAYS.map(day => <th key={day} scope="col">{day}</th>)}</tr>
          </thead>
          <tbody>
            {weeks.map((week, weekIndex) => (
              <tr key={weekIndex}>
                {week.map((day, dayIndex) => {
                  if (day === null) return <td key={dayIndex} className="trade-calendar-cell is-empty" aria-hidden="true" />;
                  const key = `${monthKey}-${String(day).padStart(2, '0')}`;
                  const cell = byDay.get(key);
                  const value = cell ? Math.round(cell.profit * 100) / 100 : 0;
                  const tone = !cell || value === 0 ? 'has-flat' : value > 0 ? 'has-profit' : 'has-loss';
                  const classes = ['trade-calendar-cell', tone];
                  if (cell) classes.push('has-trades');
                  if (key === todayKey) classes.push('is-today');
                  if (key === selectedDay) classes.push('is-selected');
                  const interactive = Boolean(cell && onSelectDay);
                  if (interactive) classes.push('is-clickable');
                  const toggle = () => onSelectDay?.(selectedDay === key ? null : key);
                  return (
                    <td
                      key={dayIndex}
                      className={classes.join(' ')}
                      title={cell ? `${cell.count} closed trade${cell.count === 1 ? '' : 's'} (UTC)` : undefined}
                      role={interactive ? 'button' : undefined}
                      tabIndex={interactive ? 0 : undefined}
                      aria-pressed={interactive ? selectedDay === key : undefined}
                      aria-label={interactive ? `${day} ${monthLabel}: ${cell!.count} closed trade${cell!.count === 1 ? '' : 's'}, ${formatCell(value)}` : undefined}
                      onClick={interactive ? toggle : undefined}
                      onKeyDown={interactive ? (event) => {
                        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
                      } : undefined}
                    >
                      <span className="trade-calendar-day">{day}</span>
                      {cell && <span className="trade-calendar-value">{formatCell(value)}</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="trade-calendar-summary">
          <span className="trade-calendar-summary-label">Month total</span>
          <strong className={`trade-calendar-summary-total ${monthTrades === 0 || monthProfit === 0 ? 'is-flat' : monthProfit > 0 ? 'is-profit' : 'is-loss'}`}>
            {monthTrades === 0 ? '—' : formatCell(monthProfit)}
          </strong>
          <span className="trade-calendar-summary-note">
            {monthTrades === 0
              ? 'No closed trades recorded for this month (broker history window only).'
              : `${monthTrades} closed trade${monthTrades === 1 ? '' : 's'} · broker close date (UTC)`}
          </span>
          {onSelectDay && monthTrades > 0 && (
            <span className="trade-calendar-summary-hint">Click a day to filter history</span>
          )}
        </div>
      </div>
    </div>
  );
};
