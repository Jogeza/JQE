import React from 'react';
import { PositionsTable } from '../components/PositionsTable';
import { ExecutionStateResponse } from '../types/api';

interface PositionsPageProps {
  execution: ExecutionStateResponse | null;
  loading: boolean;
  currency?: string;
}

export const PositionsPage: React.FC<PositionsPageProps> = ({ execution, loading, currency }) => {
  return (
    <div className="dashboard-page-container">
      <div className="editorial-heading"><div><h1>Positions</h1></div><p>Broker exposure</p></div>
      <PositionsTable
        positions={execution?.positions || []}
        brokerName={execution?.broker}
        loading={loading}
        currency={currency}
      />
    </div>
  );
};
