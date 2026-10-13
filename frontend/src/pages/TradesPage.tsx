import React, { useState } from 'react';
import { DecisionJournal } from '../components/DecisionJournal';
import { PnlSummary } from '../components/PnlSummary';
import { RecentTradesTable } from '../components/RecentTradesTable';
import { TradeCalendar } from '../components/TradeCalendar';
import { ExecutionStateResponse } from '../types/api';

interface TradesPageProps {
  execution: ExecutionStateResponse | null;
  loading: boolean;
  currency?: string;
}

export const TradesPage: React.FC<TradesPageProps> = ({ execution, loading, currency }) => {
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const trades = execution?.recent_trades || [];

  return (
    <div className="dashboard-page-container journal-page">
      <div className="editorial-heading"><div><h1>Journal</h1></div><p>Broker history</p></div>
      <PnlSummary trades={trades} currency={currency} />
      <details className="journal-disclosure">
        <summary>Calendar{selectedDay ? ` · ${selectedDay} UTC` : ''}</summary>
        <TradeCalendar
          trades={trades}
          currency={currency}
          selectedDay={selectedDay}
          onSelectDay={setSelectedDay}
        />
      </details>
      <RecentTradesTable
        trades={trades}
        loading={loading}
        currency={currency}
        broker={execution?.broker}
        dayFilter={selectedDay}
        onClearDayFilter={() => setSelectedDay(null)}
      />
      <details className="journal-disclosure">
        <summary>Decision evidence</summary>
        <DecisionJournal />
      </details>
    </div>
  );
};
