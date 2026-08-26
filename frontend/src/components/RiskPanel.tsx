import React from 'react';
import { ShieldAlert, AlertOctagon, Lock, Unlock, AlertTriangle } from 'lucide-react';
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

  // Calculate percentage of daily loss limit consumed
  const lossProgress = Math.min(100, Math.max(0, (currentLoss / (maxLoss || 1)) * 100));
  const remainingAllowance = Math.max(0, maxLoss - currentLoss);

  const getRiskBanner = () => {
    if (stale) {
      return {
        text: 'RISK STATE STALE',
        sub: 'The latest refresh failed; displayed limits must not be treated as current approval',
        bg: 'var(--quant-amber-subtle)', border: 'rgba(255, 171, 0, 0.3)', color: 'var(--quant-amber)', icon: AlertTriangle,
      };
    }
    if (!risk || brokerConnected === undefined) {
      return {
        text: 'RISK STATE UNKNOWN',
        sub: 'Current broker and risk telemetry are required before trading status can be shown',
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
        border: 'rgba(255, 171, 0, 0.3)',
        color: 'var(--quant-amber)',
        icon: AlertTriangle,
      };
    }
    if (!riskAllowed) {
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
      text: 'TRADING ENABLED',
      sub: risk.risk_message,
      bg: 'var(--quant-green-subtle)',
      border: 'var(--quant-green-border)',
      color: 'var(--quant-green)',
      icon: Unlock,
    };
  };

  const banner = getRiskBanner();
  const BannerIcon = banner.icon;

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <ShieldAlert size={14} color="var(--quant-amber)" />
          <span>Stateless Risk Controller & Capital Guard</span>
        </div>
        <span className="badge badge-neutral">API RISK SNAPSHOT</span>
      </div>

      <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {/* Prominent Risk State Banner */}
        <div
          style={{
            backgroundColor: banner.bg,
            border: `1px solid ${banner.border}`,
            borderRadius: 'var(--radius-sm)',
            padding: '10px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
          }}
        >
          <BannerIcon size={18} color={banner.color} />
          <div>
            <div
              className="font-mono"
              style={{
                fontSize: '12px',
                fontWeight: 800,
                color: banner.color,
                letterSpacing: '0.04em',
              }}
            >
              {banner.text}
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{banner.sub}</div>
          </div>
        </div>

        {/* Daily Loss Meter */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Daily Loss Used:</span>
            <span>
              <strong style={{ color: currentLoss > 0 ? 'var(--quant-red)' : 'var(--text-primary)' }}>
                {currentLoss.toFixed(2)}%
              </strong>
              <span style={{ color: 'var(--text-dim)' }}> / {maxLoss.toFixed(1)}% max</span>
            </span>
          </div>

          <div
            style={{
              height: '6px',
              backgroundColor: 'var(--bg-app)',
              borderRadius: '3px',
              overflow: 'hidden',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${lossProgress}%`,
                backgroundColor: lossProgress > 80 ? 'var(--quant-red)' : lossProgress > 50 ? 'var(--quant-amber)' : 'var(--quant-cyan)',
                transition: 'width 0.3s ease',
              }}
            />
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
            <span>0.0%</span>
            <span>Remaining: {remainingAllowance.toFixed(2)}%</span>
            <span>{maxLoss.toFixed(1)}% Limit</span>
          </div>
        </div>

        {/* Frequency & Sizing Metrics */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '8px',
            backgroundColor: 'var(--bg-app)',
            padding: '10px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)',
            fontSize: '11.5px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>TRADES TODAY</div>
            <div style={{ fontSize: '14px', fontWeight: 700, marginTop: '2px' }}>
              {currentTrades} <span style={{ fontSize: '11px', color: 'var(--text-dim)' }}>/ {maxTrades} max</span>
            </div>
          </div>

          <div>
            <div style={{ color: 'var(--text-muted)', fontSize: '10px' }}>LOT SIZING PERMITTED</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--quant-cyan)', marginTop: '2px' }}>
              {risk ? `${risk.recommended_lot_size.toFixed(2)} LOTS` : '—'}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
