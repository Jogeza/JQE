import React from 'react';
import { RecentTradesTable } from '../components/RecentTradesTable';
import { ExecutionStateResponse } from '../types/api';

interface TradesPageProps {
  execution: ExecutionStateResponse | null;
  loading: boolean;
  currency?: string;
}

export const TradesPage: React.FC<TradesPageProps> = ({ execution, loading, currency }) => {
  return (
    <div className="dashboard-page-container">
      <RecentTradesTable
        trades={execution?.recent_trades || []}
        loading={loading}
        currency={currency}
      />
    </div>
  );
};
