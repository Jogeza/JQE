import React from 'react';
import { Cpu, AlertTriangle, ShieldCheck, Zap } from 'lucide-react';
import { SystemStatusResponse, SignalResponse, RiskStatusResponse } from '../types/api';

interface EngineStatusPanelProps {
  systemStatus: SystemStatusResponse | null;
  signal: SignalResponse | null;
  risk: RiskStatusResponse | null;
  stale?: { system: boolean; strategy: boolean; risk: boolean };
}

export const EngineStatusPanel: React.FC<EngineStatusPanelProps> = ({
  systemStatus,
  signal,
  risk,
  stale,
}) => {
  const isOnline = systemStatus ? systemStatus.status === 'ONLINE' : undefined;
  const brokerConnected = systemStatus?.broker_connected;
  const riskAllowed = risk?.risk_allowed;

  const getStatusBadge = (connected: boolean | undefined, labelOnline: string = 'CONNECTED', labelOffline: string = 'OFFLINE') => {
    if (connected === undefined) return <span className="badge badge-neutral">UNKNOWN</span>;
    if (connected) {
      return (
        <span className="badge badge-green">
          <span className="status-dot status-dot-green" />
          {labelOnline}
        </span>
      );
    }
    return (
      <span className="badge badge-red">
        <span className="status-dot status-dot-red" />
        {labelOffline}
      </span>
    );
  };

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <Cpu size={14} color="var(--quant-cyan)" />
          <span>Engine Status & Architecture State</span>
        </div>
        <span className="badge badge-neutral">CLEAN ARCH</span>
      </div>

      <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {/* Status Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
            gap: '8px',
            backgroundColor: 'var(--bg-app)',
            padding: '10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          {/* Core Engine */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Engine State</span>
            {stale?.system ? <span className="badge badge-neutral">STALE</span> : getStatusBadge(isOnline, 'ONLINE', 'STOPPED')}
          </div>

          {/* Broker Gateway */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>
              Broker Gateway ({systemStatus?.broker || 'UNKNOWN'})
            </span>
            {stale?.system ? <span className="badge badge-neutral">STALE</span> : getStatusBadge(brokerConnected, 'CONNECTED', 'DISCONNECTED')}
          </div>

          {/* Strategy Engine */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Strategy Bridge</span>
            {stale?.strategy ? <span className="badge badge-neutral">STALE</span> : signal ? <span className="badge badge-green"><Zap size={10} />EVALUATED</span> : <span className="badge badge-neutral">UNKNOWN</span>}
          </div>

          {/* Risk Engine */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Risk Controller</span>
            {stale?.risk ? (
              <span className="badge badge-neutral">STALE</span>
            ) : riskAllowed === undefined ? (
              <span className="badge badge-neutral">UNKNOWN</span>
            ) : riskAllowed ? (
              <span className="badge badge-green">
                <ShieldCheck size={10} />
                PERMITTED
              </span>
            ) : (
              <span className="badge badge-red">
                <AlertTriangle size={10} />
                BLOCKED
              </span>
            )}
          </div>
        </div>

        {/* Diagnostic Metadata Rows */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Target Symbol:</span>
            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{systemStatus?.default_symbol || '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Default Timeframe:</span>
            <span style={{ color: 'var(--text-secondary)' }}>{systemStatus?.default_timeframe || '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Min Confidence Threshold:</span>
            <span style={{ color: 'var(--quant-cyan)' }}>{systemStatus ? `${systemStatus.min_confidence_threshold}%` : '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.03)', paddingBottom: '4px' }}>
            <span style={{ color: 'var(--text-muted)' }}>Current Detected Regime:</span>
            <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>{signal?.regime || '—'}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: 'var(--text-muted)' }}>Server Heartbeat:</span>
            <span style={{ color: 'var(--text-dim)', fontSize: '10.5px' }}>{systemStatus?.server_time || '—'}</span>
          </div>
        </div>
      </div>
    </div>
  );
};
