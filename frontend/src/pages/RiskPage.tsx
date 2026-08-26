import React from 'react';
import { RiskPanel } from '../components/RiskPanel';
import { RiskStatusResponse } from '../types/api';

interface RiskPageProps {
  risk: RiskStatusResponse | null;
  loading: boolean;
  brokerConnected?: boolean;
  stale?: boolean;
}

export const RiskPage: React.FC<RiskPageProps> = ({ risk, loading, brokerConnected, stale }) => {
  return (
    <div className="dashboard-page-container">
      <RiskPanel risk={risk} loading={loading} brokerConnected={brokerConnected} stale={stale} />
    </div>
  );
};
