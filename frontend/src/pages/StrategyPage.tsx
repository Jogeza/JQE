import React from 'react';
import { StrategySignalPanel } from '../components/StrategySignalPanel';
import { SignalResponse } from '../types/api';

interface StrategyPageProps {
  signal: SignalResponse | null;
  loading: boolean;
  stale?: boolean;
}

export const StrategyPage: React.FC<StrategyPageProps> = ({ signal, loading, stale }) => {
  return (
    <div className="dashboard-page-container">
      <StrategySignalPanel signal={signal} loading={loading} stale={stale} />
    </div>
  );
};
