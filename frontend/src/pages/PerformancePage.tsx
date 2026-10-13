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
    <div className="dashboard-page-container performance-page">
      <div className="editorial-heading"><div><h1>Performance</h1></div><p>Observed history</p></div>
      <p className="performance-evidence-note">Broker observations · research expectancy not established.</p>
      <PerformanceSection
        performance={performance}
        trades={execution?.recent_trades || []}
        loading={loading}
        currency={currency}
      />
    </div>
  );
};
