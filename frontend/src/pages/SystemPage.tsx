import React from 'react';
import { Terminal } from 'lucide-react';
import { SystemStatusResponse } from '../types/api';

interface SystemPageProps {
  systemStatus: SystemStatusResponse | null;
  loading: boolean;
}

export const SystemPage: React.FC<SystemPageProps> = ({ systemStatus, loading }) => {
  return (
    <div className="dashboard-page-container">
      <div className="quant-panel">
        <div className="quant-panel-header">
          <div className="quant-panel-title">
            <Terminal size={14} color="var(--quant-cyan)" />
            <span>Core System Topology & Diagnostic Telemetry</span>
          </div>
          <span className="badge badge-neutral">DIAGNOSTICS</span>
        </div>

        <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div
            style={{
              backgroundColor: '#050607',
              border: '1px solid var(--border-medium)',
              borderRadius: 'var(--radius-sm)',
              padding: '14px',
              fontFamily: 'var(--font-mono)',
              fontSize: '11.5px',
              color: 'var(--text-secondary)',
              lineHeight: '1.6',
            }}
          >
            <div style={{ color: 'var(--quant-cyan)', fontWeight: 700 }}>[JQE SYSTEM TELEMETRY]</div>
            <div>[SOURCE]: Live API status response; build version is not reported</div>
            <div>[GATEWAY]: {systemStatus?.broker?.toUpperCase() || 'UNKNOWN'}</div>
            <div>[GATEWAY CONNECTION]: {systemStatus ? (systemStatus.broker_connected ? 'CONNECTED' : 'DISCONNECTED') : 'UNKNOWN'}</div>
            <div>[ENVIRONMENT]: {systemStatus?.environment?.toUpperCase() || 'UNKNOWN'}</div>
            <div>[DEFAULT INSTRUMENT]: {systemStatus?.default_symbol || '—'}</div>
            <div>[DEFAULT TIMEFRAME]: {systemStatus?.default_timeframe || '—'}</div>
            <div>[MIN CONFIDENCE THRESHOLD]: {systemStatus ? `${systemStatus.min_confidence_threshold}%` : '—'}</div>
            <div>[SERVER CLOCK]: {systemStatus?.server_time || '—'}</div>
            <div style={{ color: 'var(--text-muted)', marginTop: '8px' }}>[TELEMETRY]: {loading ? 'LOADING' : systemStatus ? 'RECEIVED' : 'UNAVAILABLE'}</div>
          </div>
        </div>
      </div>
    </div>
  );
};
