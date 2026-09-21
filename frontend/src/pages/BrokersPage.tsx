import React, { useState } from 'react';
import { CheckCircle2, XCircle, RefreshCw, Layers, AlertTriangle, Loader2 } from 'lucide-react';
import type { BrokerStatusResponse } from '../types/api';
import { ActiveBrokerIdentityPanel } from '../components/ActiveBrokerIdentityPanel';

interface BrokersPageProps {
  brokerStatus: BrokerStatusResponse | null;
  loading: boolean;
  onRefresh?: () => void;
  onSelectBroker?: (broker: string) => Promise<void>;
}

export const BrokersPage: React.FC<BrokersPageProps> = ({
  brokerStatus,
  loading,
  onRefresh,
  onSelectBroker,
}) => {
  const brokers = brokerStatus?.brokers || [];
  const [switchingBroker, setSwitchingBroker] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);

  const handleSelect = async (broker: string) => {
    if (!onSelectBroker || switchingBroker) return;
    setSwitchingBroker(broker);
    setSwitchError(null);
    try {
      await onSelectBroker(broker);
    } catch (err) {
      setSwitchError(err instanceof Error ? err.message : 'Broker switch failed');
    } finally {
      setSwitchingBroker(null);
    }
  };

  return (
    <div className="dashboard-page-container brokers-page">
      <div className="editorial-heading">
        <div>
          <span className="editorial-kicker">Execution Architecture & Gateways</span>
          <h1>Brokers & Gateways<span>.</span></h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={loading}
              className="btn-quant"
              style={{ fontSize: '11px', padding: '4px 10px', height: '26px' }}
            >
              <RefreshCw size={11} className={loading ? 'spin' : ''} />
              REFRESH
            </button>
          )}
        </div>
      </div>

      {switchError && (
        <div
          className="broker-switch-error"
          role="alert"
          style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '8px 12px', marginBottom: '12px',
            border: '1px solid var(--quant-red)', borderRadius: 'var(--radius-sm)',
            backgroundColor: 'rgba(255, 23, 68, 0.08)',
            color: 'var(--quant-red)', fontSize: '12px', fontWeight: 700,
          }}
        >
          <AlertTriangle size={14} />
          {switchError}
        </div>
      )}

      {/* Active Broker Identity Banner */}
      <ActiveBrokerIdentityPanel brokerStatus={brokerStatus} loading={loading} />

      {/* Broker Registry Grid */}
      <div className="quant-panel" style={{ marginTop: '16px' }}>
        <div className="quant-panel-header">
          <div className="quant-panel-title">
            <Layers size={14} color="var(--quant-cyan)" />
            <span>Multi-Broker Gateway Topology</span>
          </div>
          <span className="badge badge-neutral">4 CONFIGURED</span>
        </div>

        <div className="quant-panel-body" style={{ padding: '16px' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
              gap: '14px',
            }}
          >
            {brokers.map(b => {
              const isVerifiedDemo = b.demo_guard_status === 'PASSED';
              const isFailed = b.demo_guard_status === 'FAILED';
              const isConnected = b.connected;

              const statusColor = isConnected && isVerifiedDemo
                ? 'var(--status-green)'
                : isConnected
                ? 'var(--quant-amber)'
                : 'var(--text-muted)';

              const statusText = isConnected && isVerifiedDemo
                ? 'CONNECTED · DEMO VERIFIED'
                : isConnected
                ? 'CONNECTED · UNVERIFIED DEMO'
                : 'DISCONNECTED';

              return (
                <div
                  key={b.broker}
                  style={{
                    backgroundColor: b.is_active ? 'var(--bg-card)' : 'var(--bg-surface)',
                    border: `1px solid ${b.is_active ? 'var(--quant-cyan)' : 'var(--border-subtle)'}`,
                    borderRadius: 'var(--radius-sm)',
                    padding: '16px',
                    position: 'relative',
                    boxShadow: b.is_active ? '0 0 12px rgba(0, 229, 255, 0.08)' : 'none',
                  }}
                >
                  {/* Top Bar: Name & Active Tag */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                    <div>
                      <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 800, color: 'var(--text-primary)' }}>
                        {b.name}
                      </h3>
                      <span className="font-mono" style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                        id: {b.broker}
                      </span>
                    </div>
                    {b.is_active && (
                      <span className="badge badge-cyan" style={{ fontSize: '9px', fontWeight: 800 }}>
                        ACTIVE TARGET
                      </span>
                    )}
                  </div>

                  {/* Status Strip */}
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '8px 10px',
                      backgroundColor: 'rgba(0, 0, 0, 0.3)',
                      borderRadius: 'var(--radius-sm)',
                      marginBottom: '12px',
                    }}
                  >
                    <span
                      className="status-dot"
                      style={{
                        backgroundColor: statusColor,
                        boxShadow: isConnected ? `0 0 6px ${statusColor}` : 'none',
                        width: '8px',
                        height: '8px',
                      }}
                    />
                    <span className="font-mono" style={{ fontSize: '11px', fontWeight: 700, color: statusColor }}>
                      {statusText}
                    </span>
                  </div>

                  {/* Details List */}
                  <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '6px', fontSize: '11px' }}>
                    <dt style={{ color: 'var(--text-muted)' }}>Demo Guard:</dt>
                    <dd style={{ margin: 0, fontWeight: 700 }}>
                      {isVerifiedDemo ? (
                        <span style={{ color: 'var(--status-green)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                          <CheckCircle2 size={12} /> PASSED
                        </span>
                      ) : isFailed ? (
                        <span style={{ color: 'var(--quant-red)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                          <XCircle size={12} /> REJECTED
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>UNVERIFIED</span>
                      )}
                    </dd>

                    <dt style={{ color: 'var(--text-muted)' }}>Last Verified:</dt>
                    <dd style={{ margin: 0, fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--text-secondary)' }}>
                      {b.demo_guard_verified_at ? b.demo_guard_verified_at.substring(0, 19) + ' UTC' : '—'}
                    </dd>

                    <dt style={{ color: 'var(--text-muted)' }}>Server:</dt>
                    <dd style={{ margin: 0, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                      {b.account_server || '—'}
                    </dd>

                    <dt style={{ color: 'var(--text-muted)' }}>Account ID:</dt>
                    <dd style={{ margin: 0, fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--text-primary)' }}>
                      {b.account_id_masked || '—'}
                    </dd>

                    <dt style={{ color: 'var(--text-muted)' }}>Trade Mode:</dt>
                    <dd style={{ margin: 0, textTransform: 'uppercase', fontWeight: 700, color: b.account_trade_mode === 'demo' ? 'var(--status-green)' : 'var(--text-secondary)' }}>
                      {b.account_trade_mode || 'UNKNOWN'}
                    </dd>
                  </dl>

                  {/* Configuration & Selection Footer */}
                  <div style={{ marginTop: '12px', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
                    <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '8px' }}>
                      <span className={`badge ${b.is_configured ? 'badge-green' : 'badge-neutral'}`} style={{ fontSize: '9px', fontWeight: 800 }}>
                        {b.is_configured ? 'CONFIGURED' : 'NOT CONFIGURED'}
                      </span>
                      <span className={`badge ${b.is_available ? 'badge-cyan' : 'badge-neutral'}`} style={{ fontSize: '9px', fontWeight: 800 }}>
                        {b.is_available ? 'AVAILABLE' : 'UNAVAILABLE'}
                      </span>
                    </div>
                    {b.error_message && (
                      <div className="font-mono" style={{ fontSize: '10px', color: 'var(--quant-amber)', marginBottom: '8px' }}>
                        {b.error_message}
                      </div>
                    )}
                    {b.notes && (
                      <div className="font-mono" style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px' }}>
                        {b.notes}
                      </div>
                    )}
                    {onSelectBroker && !b.is_active && (
                      <>
                        <button
                          className="btn-quant"
                          onClick={() => handleSelect(b.broker)}
                          disabled={!b.can_switch || switchingBroker !== null}
                          title={b.switch_blocked_reason ?? `Select ${b.name} as the active broker`}
                          style={{ fontSize: '11px', padding: '4px 10px', height: '26px', width: '100%' }}
                        >
                          {switchingBroker === b.broker ? (
                            <>
                              <Loader2 size={11} className="spin" />
                              SWITCHING…
                            </>
                          ) : (
                            `SELECT ${b.broker.toUpperCase()}`
                          )}
                        </button>
                        {!b.can_switch && b.switch_blocked_reason && (
                          <div className="font-mono" style={{ fontSize: '9.5px', color: 'var(--text-muted)', marginTop: '6px' }}>
                            {b.switch_blocked_reason}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
