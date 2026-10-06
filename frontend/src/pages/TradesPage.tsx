import React from 'react';
import { DecisionJournal } from '../components/DecisionJournal';
import { RecentTradesTable } from '../components/RecentTradesTable';
import { TradeCalendar } from '../components/TradeCalendar';
import { ExecutionStateResponse } from '../types/api';

interface TradesPageProps {
  execution: ExecutionStateResponse | null;
  loading: boolean;
  currency?: string;
}

export const TradesPage: React.FC<TradesPageProps> = ({ execution, loading, currency }) => {
  return (
    <div className="dashboard-page-container">
      <TradeCalendar trades={execution?.recent_trades || []} currency={currency} />
      <DecisionJournal />
      <RecentTradesTable
        trades={execution?.recent_trades || []}
        loading={loading}
        currency={currency}
        broker={execution?.broker}
      />
    </div>
  );
};
