import React from 'react';
import { BarChart3, CheckCircle2 } from 'lucide-react';
import { PaperDiagnosticsResponse } from '../types/api';

interface PaperDiagnosticsPanelProps {
  diagnostics: PaperDiagnosticsResponse | null;
  unavailable: boolean;
  stale: boolean;
}

const number = (item: number | undefined, unavailable: boolean) => unavailable || item === undefined ? 'UNAVAILABLE' : item.toLocaleString('en-GB');
const percent = (item: string | null | undefined) => item === null || item === undefined ? '—' : `${Number(item).toFixed(1)}%`;

export const PaperDiagnosticsPanel: React.FC<PaperDiagnosticsPanelProps> = ({ diagnostics, unavailable, stale }) => {
  const metrics = diagnostics?.metrics;
  const missing = unavailable || !diagnostics || !metrics;
  const funnel = metrics?.funnel;
  const blockers = metrics?.block_reasons ? Object.entries(metrics.block_reasons).sort((a, b) => b[1] - a[1]).slice(0, 5) : [];
  const regimes = metrics?.by_regime ? Object.entries(metrics.by_regime) : [];
  const directions = metrics?.directions ? Object.entries(metrics.directions).filter(([key]) => key === 'BUY' || key === 'SELL') : [];
  const stages = funnel ? [
    ['OBSERVATIONS', funnel.observations, null], ['SIGNALS', funnel.raw_signals, funnel.raw_signal_rate],
    ['CONFIRMED', funnel.confirmed, funnel.confirmation_rate], ['AUTHORIZED', funnel.risk_authorized, funnel.authorization_rate],
    ['OPENED', funnel.opened, funnel.entry_rate], ['CLOSED', funnel.closed, null],
  ] as const : [];
  return (
    <section className="quant-panel paper-diagnostics-panel" aria-label="Paper research diagnostics">
      <div className="quant-panel-header">
        <div className="quant-panel-title"><BarChart3 size={13} color="var(--quant-blue)" /><span>Paper Research / Diagnostics</span></div>
        <span className={`badge ${missing || stale ? 'badge-neutral' : 'badge-cyan'}`}>{missing ? 'UNAVAILABLE' : stale ? 'STALE' : diagnostics.status}</span>
      </div>
      <div className="quant-panel-body">
        <div className="paper-diagnostics-summary">
          {['observations', 'signals', 'confirmations', 'authorized_entries', 'opened_positions', 'closed_positions'].map((key) => (
            <div key={key}><span>{key.replace(/_/g, ' ')}</span><strong>{number(metrics?.[key as keyof typeof metrics] as number | undefined, missing)}</strong></div>
          ))}
        </div>
        <div className="paper-funnel" aria-label="Paper strategy funnel">
          {stages.length ? stages.map(([label, count, rate], index) => <React.Fragment key={label}>
            <div className="paper-funnel-stage"><strong>{number(count, false)}</strong><span>{label}</span>{rate !== null && <small>{percent(rate)}</small>}</div>
            {index < stages.length - 1 && <span className="paper-funnel-arrow" aria-hidden="true">↓</span>}
          </React.Fragment>) : <span className="text-muted">UNAVAILABLE</span>}
        </div>
        <div className="paper-diagnostics-columns">
          <div><h4>Strategy filters</h4>{blockers.length ? blockers.map(([reason, count]) => <p key={reason}><span>{reason.replace(/_/g, ' ')}</span><strong>{count.toLocaleString('en-GB')}</strong></p>) : <p className="text-muted">UNAVAILABLE</p>}</div>
          <div><h4>Regimes</h4>{regimes.length ? regimes.map(([regime, item]) => <p key={regime}><span>{regime}</span><strong>{item.observations.toLocaleString('en-GB')}</strong></p>) : <p className="text-muted">UNAVAILABLE</p>}</div>
          <div><h4>Direction</h4>{directions.length ? directions.map(([direction, count]) => <p key={direction}><span>{direction}</span><strong>{count.toLocaleString('en-GB')}</strong></p>) : <p className="text-muted">UNAVAILABLE</p>}</div>
        </div>
        <div className="paper-diagnostics-footer">
          <span>Net P/L <strong>{missing ? 'UNAVAILABLE' : metrics?.net_pnl ?? '0'}</strong></span>
          <span>Average R <strong>{missing ? 'UNAVAILABLE' : metrics?.average_r ?? '0'}</strong></span>
          <span>Drawdown <strong>{missing ? 'UNAVAILABLE' : metrics?.max_drawdown ?? '0'}</strong></span>
          <span><CheckCircle2 size={12} /> Sample {missing ? 'UNAVAILABLE' : diagnostics.sample_size_insufficient ? 'INSUFFICIENT' : 'SUFFICIENT'}</span>
        </div>
      </div>
    </section>
  );
};