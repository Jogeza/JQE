import React from 'react';
import {
  SystemStatusResponse,
  CandlesResponse,
  SignalResponse,
  RiskStatusResponse,
  MarketSetup,
  OfflineMonitoringResponse,
  BrokerStatusResponse,
  PaperRuntimeStatusResponse,
} from '../types/api';
import { TelemetryLifecycle } from '../services/telemetryLifecycle';
import { TelemetryLifecyclePanel } from './TelemetryLifecyclePanel';
import { ActiveBrokerIdentityPanel } from './ActiveBrokerIdentityPanel';

interface OwnerEvidencePanelProps {
  telemetryLifecycle: TelemetryLifecycle;
  brokerStatus: BrokerStatusResponse | null;
  loading: boolean;
  systemStatus: SystemStatusResponse | null;
  backendOffline: boolean;
  monitoringData: OfflineMonitoringResponse | null;
  candlesData: CandlesResponse | null;
  signalData: SignalResponse | null;
  setupData: MarketSetup | null;
  riskData: RiskStatusResponse | null;
  paperRuntimeData: PaperRuntimeStatusResponse | null;
}

export const OwnerEvidencePanel: React.FC<OwnerEvidencePanelProps> = ({
  telemetryLifecycle,
  brokerStatus,
  loading,
  systemStatus,
  backendOffline,
  monitoringData,
  candlesData,
  signalData,
  setupData,
  riskData,
  paperRuntimeData,
}) => {
  const FreshnessDot: React.FC<{ tone: 'green' | 'amber' | 'red' | 'neutral' }> = ({ tone }) => {
    const cls = tone === 'green' ? 'dot-green' : tone === 'amber' ? 'dot-amber' : tone === 'red' ? 'dot-red' : 'dot-neutral';
    return <span className={`freshness-dot ${cls}`} />;
  };

  return <details className="dashboard-details">
    <summary>Connection and data provenance</summary>
    <TelemetryLifecyclePanel lifecycle={telemetryLifecycle} />

    <div style={{ margin: '12px 0' }}>
      <ActiveBrokerIdentityPanel brokerStatus={brokerStatus ?? null} loading={loading} />
    </div>

    {/* Active Market Telemetry Synchronization Strip */}
    <div className="active-market-freshness-bar" aria-label="Telemetry Freshness and Synchronization">
      <div className="freshness-indicator" title={`Backend Server Time: ${systemStatus?.server_time ?? 'Unavailable'}`}>
        <span className="freshness-indicator-label">1. Service Heartbeat</span>
        <span className="freshness-indicator-value">
          <FreshnessDot tone={backendOffline ? 'red' : monitoringData?.backend.state === 'LIVE' ? 'green' : 'neutral'} />
          {backendOffline ? 'OFFLINE' : monitoringData?.backend.state ?? 'UNAVAILABLE'}
        </span>
      </div>

      <div className="freshness-indicator" title={`Market Data Freshness: ${setupData?.data_freshness.reason ?? candlesData?.market_data_status ?? 'Unknown'}`}>
        <span className="freshness-indicator-label">2. Market Data</span>
        <span className="freshness-indicator-value">
          <FreshnessDot
            tone={
              monitoringData?.candle_freshness.state === 'FRESH'
                ? 'green'
                : setupData?.data_freshness.freshness_state === 'FORMING'
                ? 'amber'
                : 'red'
            }
          />
          {monitoringData?.candle_freshness.state ?? 'UNAVAILABLE'}
        </span>
      </div>

      <div className="freshness-indicator" title={`Strategy Evaluation: ${signalData?.signal ?? 'None'} · Regime: ${signalData?.regime ?? 'UNKNOWN'}`}>
        <span className="freshness-indicator-label">3. Strategy Pipeline</span>
        <span className="freshness-indicator-value">
          <FreshnessDot tone={monitoringData?.strategy.state === 'FRESH' ? 'green' : monitoringData?.strategy.state === 'STALE' ? 'amber' : 'neutral'} />
          {monitoringData?.strategy.state === 'STALE' ? `STALE · ${monitoringData.strategy.value}` : signalData?.signal === 'NO_TRADE' ? 'NO TRADE' : signalData?.signal ?? 'UNAVAILABLE'}
        </span>
      </div>

      <div className="freshness-indicator" title={`Risk Sizing Status: ${setupData?.risk_authorization.reason ?? riskData?.risk_message ?? 'Pending'}`}>
        <span className="freshness-indicator-label">4. Risk Verification</span>
        <span className="freshness-indicator-value">
          <FreshnessDot tone={monitoringData?.risk.state === 'FRESH' ? 'green' : monitoringData?.risk.state === 'STALE' ? 'amber' : monitoringData?.risk.state === 'BLOCKED' ? 'red' : 'neutral'} />
          {monitoringData?.risk.state ?? 'UNAVAILABLE'}
        </span>
      </div>

      <div className="freshness-indicator" title={`Setup State: ${setupData?.setup_state ?? 'FORMING'} · Expiry: ${setupData?.expires_at ?? '—'}`}>
        <span className="freshness-indicator-label">5. Setup Lifecycle</span>
        <span className="freshness-indicator-value">
          <FreshnessDot
            tone={
              setupData?.setup_state === 'READY'
                ? 'green'
                : setupData?.setup_state === 'FORMING'
                ? 'amber'
                : 'neutral'
            }
          />
          {setupData?.setup_state ?? 'FORMING'}
        </span>
      </div>

      <div className="freshness-indicator" title={`Paper Runtime: ${paperRuntimeData?.runtime_mode ?? 'OFFLINE'} · Action: ${paperRuntimeData?.last_action ?? 'Idle'}`}>
        <span className="freshness-indicator-label">6. Paper Runtime</span>
        <span className="freshness-indicator-value">
          <FreshnessDot tone={paperRuntimeData?.running ? 'green' : 'neutral'} />
          {paperRuntimeData?.running ? 'RUNNING' : 'STANDBY'}
        </span>
      </div>
    </div>

    <div className="offline-gate-details">
      <span>Observed: {monitoringData?.observed_at ?? 'UNAVAILABLE'}</span>
      <span>Source: OFFLINE_EVIDENCE</span>
      <span>Environment: {monitoringData?.environment ?? 'UNAVAILABLE'}</span>
      <span>Scope: {monitoringData?.simulation_submissions.account_scope ?? 'UNAVAILABLE'}</span>
      <span>Simulation starts: {monitoringData ? `${monitoringData.simulation_submissions.utc_count}/${monitoringData.simulation_submissions.limit}` : 'UNAVAILABLE'}</span>
      <span>Reset: {monitoringData?.simulation_submissions.reset_at ?? 'UNAVAILABLE'}</span>
      <span>Reasons: {monitoringData ? [...monitoringData.strategy.reason_codes, ...monitoringData.candle_freshness.reason_codes, ...monitoringData.risk.reason_codes, ...monitoringData.execution_authorization.reason_codes, ...monitoringData.simulation_submissions.reason_codes].join(', ') || 'NONE' : 'BACKEND_OFFLINE'}</span>
      <span>Dataset: {setupData?.dataset_hash ?? 'UNAVAILABLE'}</span>
      <span>Seed: {setupData?.dataset_seed ?? 'UNAVAILABLE'}</span>
      <span>Structure: {setupData?.evidence.find(item => item.factor === 'structure')?.assessment ?? 'UNAVAILABLE'}</span>
      <span>Momentum: {setupData?.evidence.find(item => item.factor === 'momentum')?.assessment ?? 'UNAVAILABLE'}</span>
      <span>Volatility: {setupData?.evidence.find(item => item.factor === 'volatility')?.assessment ?? 'UNAVAILABLE'}</span>
      <span>Score: {setupData?.confidence_score ?? 'UNAVAILABLE'}</span>
    </div>
  </details>;
};
