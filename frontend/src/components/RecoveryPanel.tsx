import React from 'react';
import { AlertTriangle, CheckCircle2, HelpCircle } from 'lucide-react';
import { RecoveryDiagnosticsResponse } from '../types/api';

interface RecoveryPanelProps {
  recovery: RecoveryDiagnosticsResponse | null;
  loading: boolean;
  unavailable: boolean;
  stale: boolean;
}

const formatTime = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
};

export const RecoveryPanel: React.FC<RecoveryPanelProps> = ({
  recovery,
  loading,
  unavailable,
  stale,
}) => {
  const unknown = unavailable || stale || !recovery || recovery.status === 'UNKNOWN';
  const blocked = !unknown && (recovery.status === 'BLOCKED' || recovery.execution_blocked);
  const status = unknown ? 'UNKNOWN' : blocked ? 'BLOCKED' : 'CLEAR';
  const Icon = unknown ? HelpCircle : blocked ? AlertTriangle : CheckCircle2;
  const badgeClass = unknown ? 'badge-neutral' : blocked ? 'badge-red' : 'badge-green';
  const message = unknown
    ? 'Recovery status unavailable — execution safety cannot be determined'
    : recovery.reason;

  return (
    <section className="quant-panel" aria-label="Execution recovery diagnostics">
      <div className="quant-panel-header">
        <div className="quant-panel-title"><Icon size={14} /> Execution recovery</div>
        <span className={`badge ${badgeClass}`}>{loading && !recovery ? 'UNKNOWN' : status}</span>
      </div>
      <div className="quant-panel-body">
        <div className={blocked ? 'text-red' : unknown ? 'text-amber' : 'text-secondary'} style={{ fontSize: 12 }}>
          {message}
        </div>
        {!unknown && recovery.intents.length > 0 && (
          <div className="quant-table-wrapper" style={{ marginTop: 12 }}>
            <table className="quant-table">
              <thead><tr>
                <th>Intent</th><th>State</th><th>Scope</th><th>Instrument</th>
                <th>Quantity</th><th>Created</th><th>Updated</th><th>Reason</th>
              </tr></thead>
              <tbody>{recovery.intents.map(intent => (
                <tr key={intent.idempotency_key}>
                  <td title={intent.idempotency_key}>{intent.idempotency_key.slice(0, 12)}…</td>
                  <td>{intent.intent_state}</td>
                  <td>{intent.broker || '—'} / {intent.account_id || '—'}</td>
                  <td>{intent.symbol || '—'} {intent.side || ''}</td>
                  <td>{intent.quantity ? `${intent.quantity.value} ${intent.quantity.unit}` : 'Unavailable'}</td>
                  <td>{formatTime(intent.created_at)}</td>
                  <td>{formatTime(intent.updated_at)}</td>
                  <td>{intent.blocking_reason}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
};
