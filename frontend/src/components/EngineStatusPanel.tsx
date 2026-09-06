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

  const heartbeat = (() => {
    if (!systemStatus?.server_time) return { time: '—', date: null };
    const parsed = new Date(systemStatus.server_time);
    if (Number.isNaN(parsed.getTime())) return { time: systemStatus.server_time, date: null };
    return {
      time: parsed.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      date: parsed.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }),
    };
  })();

  const getStatusBadge = (connected: boolean | undefined, labelOnline: string = 'CONNECTED', labelOffline: string = 'OFFLINE') => {
    if (connected === undefined) return <span className="operations-health-value neutral"><span className="status-dot" />UNKNOWN</span>;
    if (connected) {
      return <span className="operations-health-value positive"><span className="status-dot status-dot-green" />{labelOnline}</span>;
    }
    return <span className="operations-health-value negative"><span className="status-dot status-dot-red" />{labelOffline}</span>;
  };

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <Cpu size={14} color="var(--quant-cyan)" />
          <span>System Health</span>
        </div>
        <span className="badge badge-neutral">CLEAN ARCH</span>
      </div>

      <div className="quant-panel-body operations-panel-body">
        <div className="operations-health-strip">
          <div className="operations-health-item">
            {stale?.system ? <span className="operations-health-value neutral"><span className="status-dot" />STALE</span> : getStatusBadge(isOnline, 'ONLINE', 'STOPPED')}
            <span className="operations-health-label">Engine</span>
          </div>
          <div className="operations-health-item">
            {stale?.system ? <span className="operations-health-value neutral"><span className="status-dot" />STALE</span> : getStatusBadge(brokerConnected, 'CONNECTED', 'DISCONNECTED')}
            <span className="operations-health-label">Gateway · {systemStatus?.broker || 'Unknown'}</span>
          </div>
          <div className="operations-health-item">
            {stale?.strategy ? <span className="operations-health-value neutral"><span className="status-dot" />STALE</span> : signal ? <span className="operations-health-value information"><Zap size={11} />EVALUATED</span> : <span className="operations-health-value neutral"><span className="status-dot" />UNKNOWN</span>}
            <span className="operations-health-label">Strategy</span>
          </div>
          <div className="operations-health-item">
            {stale?.risk ? (
              <span className="operations-health-value neutral"><span className="status-dot" />STALE</span>
            ) : riskAllowed === undefined ? (
              <span className="operations-health-value neutral"><span className="status-dot" />UNKNOWN</span>
            ) : riskAllowed ? (
              <span className="operations-health-value positive"><ShieldCheck size={11} />PERMITTED</span>
            ) : (
              <span className="operations-health-value negative"><AlertTriangle size={11} />BLOCKED</span>
            )}
            <span className="operations-health-label">Risk</span>
          </div>
        </div>

        <dl className="operations-definition-list">
          <div>
            <dt>Target symbol</dt>
            <dd>{systemStatus?.default_symbol || '—'}</dd>
          </div>
          <div>
            <dt>Default timeframe</dt>
            <dd>{systemStatus?.default_timeframe || '—'}</dd>
          </div>
          <div>
            <dt>Minimum confidence</dt>
            <dd>{systemStatus ? `${systemStatus.min_confidence_threshold}%` : '—'}</dd>
          </div>
          <div>
            <dt>Detected regime</dt>
            <dd className="text-amber">{signal?.regime || '—'}</dd>
          </div>
          <div>
            <dt>Server heartbeat</dt>
            <dd className="operations-time"><strong>{heartbeat.time}</strong>{heartbeat.date && <small>{heartbeat.date}</small>}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
};
