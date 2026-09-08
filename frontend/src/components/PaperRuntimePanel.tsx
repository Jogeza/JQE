import React from 'react';
import { Activity, Bell, CircleAlert, ShieldCheck } from 'lucide-react';
import { PaperRuntimeStatusResponse } from '../types/api';

interface PaperRuntimePanelProps {
  runtime: PaperRuntimeStatusResponse | null;
  telegramStatus?: string;
  unavailable: boolean;
}

const value = (item: string | number | null | undefined) => item === null || item === undefined || item === '' ? 'UNAVAILABLE' : String(item);
const time = (item: string | null | undefined) => item ? new Date(item).toLocaleString('en-GB') : 'UNAVAILABLE';

export const PaperRuntimePanel: React.FC<PaperRuntimePanelProps> = ({ runtime, telegramStatus, unavailable }) => {
  const missing = unavailable || !runtime;
  const state = missing ? 'UNAVAILABLE' : runtime.running ? 'RUNNING' : 'STOPPED';
  const stateClass = missing ? 'neutral' : runtime.running ? 'positive' : 'negative';
  return (
    <section className="quant-panel paper-runtime-panel" aria-label="Paper runtime">
      <div className="quant-panel-header">
        <div className="quant-panel-title"><Activity size={13} color="var(--quant-blue)" /><span>Paper Runtime</span></div>
        <span className={`badge ${stateClass === 'positive' ? 'badge-green' : stateClass === 'negative' ? 'badge-red' : 'badge-neutral'}`}>{state}</span>
      </div>
      <div className="quant-panel-body">
        <div className="paper-runtime-grid">
          <div><span>Mode</span><strong>{value(runtime?.runtime_mode)}</strong></div>
          <div><span>Last cycle</span><strong>{time(runtime?.last_cycle_at)}</strong></div>
          <div><span>Cycles</span><strong>{value(runtime?.cycles_completed)}</strong></div>
          <div><span>Last candle</span><strong>{time(runtime?.last_processed_observation)}</strong></div>
          <div><span>Symbols</span><strong>{runtime?.symbols_monitored.length ? runtime.symbols_monitored.join(', ') : value(null)}</strong></div>
          <div><span>Open paper positions</span><strong>{value(runtime?.open_paper_positions)}</strong></div>
          <div><span>Last signal / action</span><strong>{value(runtime?.last_signal)} / {value(runtime?.last_action)}</strong></div>
          <div><span>Notifications</span><strong className={runtime?.notification_state === 'READY' ? 'text-green' : ''}><Bell size={11} /> {value(runtime?.notification_state)}</strong></div>
        </div>
        <div className="paper-runtime-safety">
          <span><ShieldCheck size={12} /> Paper execution: {runtime ? (runtime.paper_execution_enabled ? 'ENABLED' : 'DISABLED') : 'UNAVAILABLE'}</span>
          <span><CircleAlert size={12} /> Broker execution: {runtime ? (runtime.broker_execution_enabled ? 'ENABLED' : 'DISABLED') : 'UNAVAILABLE'}</span>
        </div>
        <div className="paper-runtime-footer">Telegram <strong>{telegramStatus || 'UNAVAILABLE'}</strong>{runtime?.last_error && <span className="text-red">Last error: {runtime.last_error}</span>}</div>
      </div>
    </section>
  );
};