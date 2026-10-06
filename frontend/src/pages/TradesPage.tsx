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
    <div className="dashboard-page-container">
      <PnlSummary trades={trades} currency={currency} />
      <TradeCalendar
        trades={trades}
        currency={currency}
        selectedDay={selectedDay}
        onSelectDay={setSelectedDay}
      />
      <DecisionJournal />
      <RecentTradesTable
        trades={trades}
        loading={loading}
        currency={currency}
        broker={execution?.broker}
        dayFilter={selectedDay}
        onClearDayFilter={() => setSelectedDay(null)}
      />
    </div>
  );
};
