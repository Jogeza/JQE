import React from 'react';
import { AlertTriangle, CheckCircle2, Clock3, ShieldAlert } from 'lucide-react';
import { ExecutionSafetyResponse } from '../types/api';

interface ExecutionSafetyPanelProps {
  safety: ExecutionSafetyResponse | null;
  loading: boolean;
  unavailable: boolean;
  stale: boolean;
}

const formatValue = (value: string | number | boolean | null) => {
  if (value === null) return '—';
  if (typeof value === 'boolean') return value ? 'YES' : 'NO';
  return String(value).replace(/_/g, ' ');
};

const formatTime = (value: string | null) => {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('en-GB');
};

export const ExecutionSafetyPanel: React.FC<ExecutionSafetyPanelProps> = ({
  safety,
  loading,
  unavailable,
  stale,
}) => {
  const unverified = unavailable || stale || !safety || safety.observation_state !== 'OBSERVED';
  const authorization = unverified ? 'UNKNOWN' : safety.execution_authorization;
  const isAuthorized = authorization === 'AUTHORIZED';
  const isBlocked = authorization === 'BLOCKED';
  const isInProgress = !unverified && safety.reason_codes.includes('SUBMISSION_IN_PROGRESS');
  const Icon = isAuthorized ? CheckCircle2 : isBlocked ? ShieldAlert : isInProgress ? Clock3 : AlertTriangle;
  const badgeClass = isAuthorized ? 'badge-green' : isBlocked ? 'badge-red' : 'badge-neutral';
  const color = isAuthorized
    ? 'var(--quant-green)'
    : isBlocked
      ? 'var(--quant-red)'
      : 'var(--quant-amber)';
  const explanation = unavailable
    ? 'Safety publication unavailable; execution authorization cannot be verified.'
    : stale
      ? 'Cached safety telemetry is stale; prior authorization is not considered current.'
      : !safety
        ? loading ? 'Loading canonical safety publication…' : 'Safety publication unavailable; execution authorization cannot be verified.'
        : safety.observation_state !== 'OBSERVED'
          ? `Safety publication is ${formatValue(safety.observation_state).toLowerCase()}; execution authorization cannot be verified.`
          : safety.reason_codes.length
            ? safety.reason_codes.map(formatValue).join(' · ')
            : 'No reason codes published.';

  return (
    <section className={`quant-panel execution-safety-panel ${authorization.toLowerCase()}`} aria-label="Execution safety">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <Icon size={13} color={color} />
          <span>Execution Safety & Authorization</span>
        </div>
        <span className={`badge ${badgeClass}`}>{authorization}</span>
      </div>
      <div className="quant-panel-body operations-panel-body">
        <div className={`execution-safety-summary ${isAuthorized ? 'authorized' : isBlocked ? 'blocked' : 'unknown'}`}>
          <div className="execution-safety-state font-mono" style={{ color }}>
            {authorization.replace(/_/g, ' ')}
          </div>
          <div className={unverified ? 'execution-safety-explanation unverified' : 'execution-safety-explanation'}>
            {explanation}
          </div>
        </div>

        <div className="operations-metric-grid execution-safety-grid">
          <div className="operations-metric-cell">
            <span>Observation</span>
            <strong>{safety ? formatValue(safety.observation_state) : 'UNAVAILABLE'}</strong>
          </div>
          <div className="operations-metric-cell">
            <span>Emergency stop</span>
            <strong style={{ color: safety?.emergency_stop_state === 'CLEAR' && !unverified ? 'var(--quant-green)' : 'var(--quant-amber)' }}>
              {safety ? formatValue(safety.emergency_stop_state) : 'UNKNOWN'}
            </strong>
          </div>
          <div className="operations-metric-cell">
            <span>Daily authority</span>
            <strong>{safety ? formatValue(safety.daily_state_authority) : 'UNKNOWN'}</strong>
          </div>
          <div className="operations-metric-cell">
            <span>Unresolved intents</span>
            <strong>{safety ? formatValue(safety.unresolved_intent_count) : '—'}</strong>
          </div>
          <div className="operations-metric-cell">
            <span>Durable executor</span>
            <strong>{safety ? formatValue(safety.durable_executor_enabled) : '—'}</strong>
          </div>
          <div className="operations-metric-cell">
            <span>Mode</span>
            <strong>{safety ? formatValue(safety.execution_mode) : '—'}</strong>
          </div>
        </div>

        <div className="operations-metadata">
          Observed <span className="font-mono">{formatTime(safety?.observed_at ?? null)}</span>
          <span aria-hidden="true">·</span>
          Context <span className="font-mono">{safety?.broker ?? '—'} / {safety?.environment ?? '—'}</span>
          <span aria-hidden="true">·</span>
          Schema <span className="font-mono">{safety?.schema_version ?? '—'}</span>
        </div>
      </div>
    </section>
  );
};
