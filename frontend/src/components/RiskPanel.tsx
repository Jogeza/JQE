import React from 'react';
import { ShieldAlert, AlertOctagon, Lock, ShieldCheck, AlertTriangle } from 'lucide-react';
import { RiskStatusResponse } from '../types/api';

interface RiskPanelProps {
  risk: RiskStatusResponse | null;
  loading: boolean;
  brokerConnected?: boolean;
  stale?: boolean;
}

export const RiskPanel: React.FC<RiskPanelProps> = ({ risk, brokerConnected, stale }) => {
  const maxLoss = risk?.max_daily_loss ?? 0;
  const currentLoss = risk?.daily_loss_percent ?? 0.0;
  const maxTrades = risk?.max_trades_daily ?? 0;
  const currentTrades = risk?.daily_trades_count ?? 0;
  const riskAllowed = risk?.risk_allowed;
  const rejectionReason = risk?.rejection_reason || risk?.risk_message || 'Risk telemetry unavailable';
  const observationStale = stale || risk?.observation_status === 'STALE';
  const observationUnavailable = !risk
    || risk.observation_status === 'NOT_OBSERVED'
    || risk.observation_status === 'UNAVAILABLE'
    || risk.observation_status === 'CONTEXT_MISMATCH';
  const riskStatus = observationStale
    ? 'Stale'
    : observationUnavailable
    ? 'Unavailable'
    : risk.risk_authorized
      ? 'Authorized'
      : 'Blocked';
  const authorizedRisk = risk?.risk_authorized
    && risk.authorized_risk_amount !== null
    && risk.authorized_risk_percent !== null
      ? `${risk.currency} ${risk.authorized_risk_amount.toFixed(2)} (${risk.authorized_risk_percent.toFixed(2)}%)`
      : 'Unavailable';
  const executionQuantityAvailable = risk?.observation_fresh
    && risk?.execution_quantity_available
    && risk.execution_quantity_value !== null
    && risk.execution_quantity_unit !== null;
  const executionQuantity = executionQuantityAvailable
    ? `${risk.execution_quantity_value!.toFixed(4)} ${risk.execution_quantity_unit!.replace(/_/g, ' ').toLowerCase()}`
    : 'Unavailable';
  const executionQuantityReason = executionQuantityAvailable
    ? null
    : observationStale ? 'Risk observation is stale' : risk?.execution_quantity_reason || 'Risk observation unavailable';
  const observationMetadata = risk?.observation_timestamp
    ? `${risk.observation_status.toLowerCase()} · ${risk.observation_age_seconds?.toFixed(1) ?? '—'}s old · ${risk.observation_timestamp}`
    : risk?.observation_reason || 'No durable-cycle risk observation';

  // Calculate percentage of daily loss limit consumed
  const lossProgress = Math.min(100, Math.max(0, (currentLoss / (maxLoss || 1)) * 100));
  const getRiskBanner = () => {
    if (observationStale) {
      return {
        text: 'RISK STATE STALE',
        sub: 'The durable-cycle observation is stale; no quantity is currently executable',
        bg: 'var(--quant-amber-subtle)', border: 'rgba(142,142,142, 0.3)', color: 'var(--quant-amber)', icon: AlertTriangle,
      };
    }
    if (observationUnavailable || brokerConnected === undefined) {
      return {
        text: 'RISK OBSERVATION UNAVAILABLE',
        sub: risk?.observation_reason || 'The durable cycle has not published authoritative risk state',
        bg: 'var(--bg-app)', border: 'var(--border-medium)', color: 'var(--text-muted)', icon: AlertTriangle,
      };
    }
    if (!brokerConnected) {
      return {
        text: 'BROKER DISCONNECTED',
        sub: 'Trading halted due to lack of broker telemetry',
        bg: 'var(--quant-red-subtle)',
        border: 'var(--quant-red-border)',
        color: 'var(--quant-red)',
        icon: AlertOctagon,
      };
    }
    if (currentLoss >= maxLoss) {
      return {
        text: 'DAILY LIMIT REACHED',
        sub: `Realized loss hit max daily limit of ${maxLoss.toFixed(1)}%`,
        bg: 'var(--quant-red-subtle)',
        border: 'var(--quant-red-border)',
        color: 'var(--quant-red)',
        icon: Lock,
      };
    }
    if (currentTrades >= maxTrades) {
      return {
        text: 'TRADE FREQUENCY CAPPED',
        sub: `Reached max execution limit of ${maxTrades} trades/day`,
        bg: 'var(--quant-amber-subtle)',
        border: 'rgba(142,142,142, 0.3)',
        color: 'var(--quant-amber)',
        icon: AlertTriangle,
      };
    }
    if (!risk.observation_fresh || !riskAllowed || !risk.risk_authorized) {
      return {
        text: 'RISK BLOCKED',
        sub: rejectionReason,
        bg: 'var(--quant-red-subtle)',
        border: 'var(--quant-red-border)',
        color: 'var(--quant-red)',
        icon: ShieldAlert,
      };
    }
    return {
      text: 'RISK LIMITS CLEAR',
      sub: 'Daily limits allow evaluation; execution still requires risk and quantity authorization',
      bg: 'var(--quant-green-subtle)',
      border: 'var(--quant-green-border)',
      color: 'var(--quant-green)',
      icon: ShieldCheck,
    };
  };

  const banner = getRiskBanner();
  const BannerIcon = banner.icon;

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <ShieldAlert size={14} color="var(--quant-amber)" />
          <span>Risk Control</span>
        </div>
        <span className="badge badge-neutral">API RISK SNAPSHOT</span>
      </div>

      <div className="quant-panel-body operations-panel-body">
        <div className="risk-notice" style={{ backgroundColor: banner.bg, color: banner.color }}>
          <BannerIcon size={18} color={banner.color} />
          <div>
            <strong>{banner.text}</strong>
            <span>{banner.sub}</span>
          </div>
        </div>

        <div className="risk-utilization">
          <span className="operations-eyebrow">Daily loss utilization</span>
          <div className="risk-utilization-value font-mono" style={{ color: currentLoss > 0 ? 'var(--quant-red)' : 'var(--text-primary)' }}>
            {currentLoss.toFixed(2)}%
          </div>
          <span className="risk-utilization-limit">of <span className="font-mono">{maxLoss.toFixed(2)}%</span> maximum</span>
          <div className="risk-meter" aria-label={`${currentLoss.toFixed(2)}% daily loss used of ${maxLoss.toFixed(2)}% maximum`}>
            <div
              className="risk-meter-fill"
              style={{
                width: `${lossProgress}%`,
                backgroundColor: lossProgress > 80 ? 'var(--quant-red)' : lossProgress > 50 ? 'var(--quant-amber)' : 'var(--quant-cyan)',
              }}
            />
          </div>
          <div className="risk-meter-scale">
            <span><strong className="font-mono">{currentLoss.toFixed(2)}%</strong> current utilization</span>
            <span><strong className="font-mono">{maxLoss.toFixed(2)}%</strong> maximum</span>
          </div>
        </div>

        <div className="operations-metric-grid risk-metric-grid">
          <div className="operations-metric-cell">
            <span>Trades today</span>
            <strong className="font-mono">{currentTrades} <small>/ {maxTrades}</small></strong>
          </div>
          <div className="operations-metric-cell">
            <span>Risk status</span>
            <strong style={{ color: riskStatus === 'Authorized' ? 'var(--quant-green)' : riskStatus === 'Blocked' ? 'var(--quant-red)' : 'var(--quant-amber)' }}>{riskStatus}</strong>
          </div>
          <div className="operations-metric-cell">
            <span>Authorized risk</span>
            <strong className="font-mono">{authorizedRisk}</strong>
          </div>
          <div className="operations-metric-cell">
            <span>Execution quantity</span>
            <strong className="font-mono">{executionQuantity}</strong>
            {executionQuantityReason && <small>{executionQuantityReason}</small>}
          </div>
        </div>
        <div className="operations-metadata">
          Observation · <span className="font-mono">{observationMetadata}</span>
        </div>
      </div>
    </div>
  );
};
