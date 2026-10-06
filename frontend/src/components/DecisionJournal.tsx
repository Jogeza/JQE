import { useEffect, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { jqeApi } from '../services/api';
import type { ObservationHealthResponse, ResourceState } from '../types/api';

export interface JournalEntry {
  id: number; observed_at: string; symbol: string; timeframe: string; stage: string;
  facts: { status?: string; signal?: string; confidence?: number; regime?: string;
    quality?: string; reasons?: string[]; decision_code?: string; order_id?: string;
    factors?: Record<string, unknown> };
}

export interface AnalysisStatus {
  state: string; current_pairs: number; total_pairs: number; updated_at?: string;
}

export function DecisionJournal() {
  const [items, setItems] = useState<JournalEntry[]>([]);
  const [state, setState] = useState('Loading');
  const [analysis, setAnalysis] = useState<AnalysisStatus>();
  const [supervisor, setSupervisor] = useState<{ state: string; execution_enabled: boolean; cycle_number?: number; reason?: string | null }>();
  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    const refresh = async () => {
      if (inFlight || controller.signal.aborted || document.visibilityState === 'hidden') return;
      inFlight = true;
      try {
        const result = await jqeApi.getJournal(controller.signal);
        if (!controller.signal.aborted) { setItems(result.items); setState(result.state); setAnalysis(result.analysis); setSupervisor(result.supervisor); }
      } catch {
        if (!controller.signal.aborted) {
          setState('Unavailable');
          setSupervisor(undefined);
          window.dispatchEvent(new CustomEvent('jqe:notification', { detail: {
            title: 'Decision journal', detail: 'Journal evidence unavailable. Check sign-in and workstation relay connectivity.',
          } }));
        }
      } finally {
        inFlight = false;
      }
    };
    const onVisibility = () => { if (document.visibilityState === 'visible') void refresh(); };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    document.addEventListener('visibilitychange', onVisibility);
    return () => { controller.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, []);
  return <section className="quant-panel" aria-label="Decision journal">
    <div className="quant-panel-header">
      <div className="quant-panel-title">
        <BookOpen size={14} color="var(--quant-cyan)" />
        <span>Decision Journal</span>
      </div>
      <span className={`badge ${state === 'OBSERVED' ? 'badge-cyan' : 'badge-neutral'}`}>{state}</span>
    </div>
    <div className="quant-panel-body journal-body">
      <div className="journal-status" role="status">
        <span>Weltrade demo · UTC</span>
        <span className={supervisor?.execution_enabled ? 'journal-status-armed' : undefined}>
          Demo supervisor: {supervisor?.state ?? 'Unavailable'} · {supervisor?.execution_enabled ? 'armed · guarded demo' : 'not verified as armed'} · {supervisor?.cycle_number ?? 0} cycles{supervisor?.reason ? ` · ${supervisor.reason}` : ''}
        </span>
        {analysis && <span>Analysis {analysis.state} · {analysis.current_pairs}/{analysis.total_pairs} pairs</span>}
      </div>
      <p className="journal-note">Analysis and decisions are evidence for review. Broker fills appear in trade history below. Strategy changes require separate research validation.</p>
      {!items.length && <p className="journal-empty">No recorded decisions yet.</p>}
      <div className="journal-scroll">
        {items.map(item => <details key={item.id} className="journal-entry">
          <summary>{item.symbol} · {item.timeframe} · {item.facts.status ?? item.facts.signal ?? item.stage} · {new Date(item.observed_at).toISOString().replace('T', ' ').slice(0, 19)} UTC</summary>
          <p>{item.facts.decision_code ?? item.facts.reasons?.join(' · ') ?? 'No reason supplied'}</p>
          {item.stage === 'ANALYSIS' && <p>Confidence {item.facts.confidence ?? 'unavailable'} · {item.facts.quality} · {item.facts.regime}</p>}
          {item.facts.order_id && <p>Broker order {item.facts.order_id}</p>}
          {item.facts.factors && <pre>{JSON.stringify(item.facts.factors, null, 2)}</pre>}
        </details>)}
      </div>
    </div>
  </section>;
}

export function DemoSupervisorBadge({ health }: { health?: ResourceState<ObservationHealthResponse> }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(timer);
  }, []);
  const status = health?.data?.execution_supervisor;
  const age = status?.updated_at ? (now - Date.parse(status.updated_at)) / 1000 : NaN;
  const stale = health?.stale || !!health?.error || status?.stale || !Number.isFinite(age) || age < 0 || age > (status?.max_age_seconds ?? 0);
  const state = !status ? 'unavailable' : stale ? 'STALE' : status.state;
  return <span className="workspace-execution-status" role="status">Demo supervisor {state} · cycle {status?.cycle_number ?? 'unknown'} · process {status?.process_alive ? 'alive' : 'unverified'}. Monitoring only; no order authorization.</span>;
}
