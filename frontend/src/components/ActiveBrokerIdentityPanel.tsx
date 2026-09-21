import React from 'react';
import { ShieldCheck, ShieldAlert, Server, CheckCircle2, AlertTriangle, Key } from 'lucide-react';
import type { BrokerStatusResponse } from '../types/api';

interface ActiveBrokerIdentityPanelProps {
  brokerStatus: BrokerStatusResponse | null;
  loading?: boolean;
}

export const ActiveBrokerIdentityPanel: React.FC<ActiveBrokerIdentityPanelProps> = ({
  brokerStatus,
  loading = false,
}) => {
  const activeIdentity = brokerStatus?.active_broker_identity;
  const isDemo = (activeIdentity?.trade_mode?.toUpperCase() === 'DEMO') ||
    (brokerStatus?.account_trade_mode?.toUpperCase() === 'DEMO') ||
    (brokerStatus?.active_broker?.toLowerCase() === 'simulation');

  const demoGuardPassed = activeIdentity?.demo_guard_passed ?? (brokerStatus?.identity_state === 'PASSED');

  const maskDisplay = activeIdentity?.account_id_masked || brokerStatus?.account_id_masked || '—';
  const serverDisplay = activeIdentity?.server || brokerStatus?.account_server || '—';
  const brokerDisplay = (activeIdentity?.broker || brokerStatus?.active_broker || 'SIMULATION').toUpperCase();
  const verifiedAt = activeIdentity?.verified_at || brokerStatus?.last_verified_at;

  const formattedVerifiedAt = (() => {
    if (!verifiedAt) return 'Never / Not Observed';
    try {
      const d = new Date(verifiedAt);
      if (Number.isNaN(d.getTime())) return verifiedAt;
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    } catch {
      return verifiedAt;
    }
  })();

  return (
    <section
      className="quant-panel active-broker-identity-panel"
      aria-label="Active Broker Identity"
      style={{ opacity: loading ? 0.75 : 1, transition: 'opacity 0.2s ease' }}
    >
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <Server size={14} color="var(--quant-cyan)" />
          <span>Active Broker Identity & Demo Guard Authority</span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {isDemo ? (
            <span className="badge badge-green" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 700 }}>
              <ShieldCheck size={12} />
              DEMO MODE
            </span>
          ) : (
            <span className="badge badge-red" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontWeight: 800 }}>
              <ShieldAlert size={12} />
              NON-DEMO WARNING
            </span>
          )}
          <span className={`badge ${brokerStatus?.connected ? 'badge-cyan' : 'badge-neutral'}`}>
            {brokerStatus?.connected ? 'CONNECTED' : 'DISCONNECTED'}
          </span>
        </div>
      </div>

      <div className="quant-panel-body" style={{ padding: '14px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '12px',
          }}
        >
          {/* Active Broker */}
          <div
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: '9.5px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              Active Broker
            </div>
            <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, marginTop: '3px', color: 'var(--quant-cyan)' }}>
              {brokerDisplay}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Env: {brokerStatus?.environment?.toUpperCase() || 'DEVELOPMENT'}
            </div>
          </div>

          {/* Account ID (Masked) */}
          <div
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: '9.5px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <Key size={10} />
              Account Identity
            </div>
            <div className="font-mono" style={{ fontSize: '15px', fontWeight: 800, marginTop: '3px', color: 'var(--text-primary)' }}>
              {maskDisplay}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Server: {serverDisplay}
            </div>
          </div>

          {/* Demo Only Guard Verification */}
          <div
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: '9.5px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              DemoOnlyGuard Check
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px' }}>
              {demoGuardPassed ? (
                <>
                  <CheckCircle2 size={15} color="var(--status-green)" />
                  <span className="font-mono" style={{ fontSize: '14px', fontWeight: 800, color: 'var(--status-green)' }}>
                    VERIFIED DEMO
                  </span>
                </>
              ) : (
                <>
                  <AlertTriangle size={15} color="var(--quant-amber)" />
                  <span className="font-mono" style={{ fontSize: '14px', fontWeight: 700, color: 'var(--quant-amber)' }}>
                    {brokerStatus?.identity_state || 'UNVERIFIED'}
                  </span>
                </>
              )}
            </div>
            <div style={{ fontSize: '9px', color: 'var(--text-secondary)', marginTop: '2px', fontFamily: 'var(--font-mono)' }}>
              {formattedVerifiedAt}
            </div>
          </div>

          {/* Safety Authorization State */}
          <div
            style={{
              backgroundColor: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
            }}
          >
            <div style={{ fontSize: '9.5px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              Safety Authorization
            </div>
            <div
              className="font-mono"
              style={{
                fontSize: '14px',
                fontWeight: 800,
                marginTop: '3px',
                color: brokerStatus?.execution_authorization === 'AUTHORIZED' ? 'var(--status-green)' : 'var(--text-primary)',
              }}
            >
              {brokerStatus?.execution_authorization || 'NOT_EVALUATED'}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Emergency Stop: <strong style={{ color: brokerStatus?.emergency_stop_state === 'CLEAR' ? 'var(--status-green)' : 'var(--quant-amber)' }}>{brokerStatus?.emergency_stop_state || 'UNKNOWN'}</strong>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
