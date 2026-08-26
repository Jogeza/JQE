import React from 'react';
import { PerformanceSection } from '../components/PerformanceSection';
import { PerformanceSummaryResponse, ExecutionStateResponse } from '../types/api';

interface PerformancePageProps {
  performance: PerformanceSummaryResponse | null;
  execution: ExecutionStateResponse | null;
  loading: boolean;
  currency?: string;
}

export const PerformancePage: React.FC<PerformancePageProps> = ({
  performance,
  execution,
  loading,
  currency,
}) => {
  return (
    <div className="dashboard-page-container">
      <PerformanceSection
        performance={performance}
        trades={execution?.recent_trades || []}
        loading={loading}
        currency={currency}
      />
    </div>
  );
};
