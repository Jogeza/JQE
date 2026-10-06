import { useEffect, useState } from 'react';
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
  const [supervisor, setSupervisor] = useState<{ state: string; execution_enabled: boolean; cycle_number?: number; reason?: string | null }>();
  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    const refresh = async () => {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      try {
        const result = await jqeApi.getJournal(controller.signal);
        if (!controller.signal.aborted) { setItems(result.items); setState(result.state); setSupervisor(result.supervisor); }
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
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);
  return <section className="workspace-card" aria-label="Decision journal">
    <h2>Journal</h2>
    <p>Weltrade demo · UTC · {state}</p>
    <p role="status">Demo supervisor: {supervisor?.state ?? 'Unavailable'} · {supervisor?.execution_enabled ? 'armed · guarded demo' : 'not verified as armed'} · {supervisor?.cycle_number ?? 0} cycles{supervisor?.reason ? ` · ${supervisor.reason}` : ''}</p>
    <p className="workspace-note">Analysis and decisions are evidence for review. Broker fills appear in trade history below. Strategy changes require separate research validation.</p>
    {!items.length && <p>No recorded decisions yet.</p>}
    <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
      {items.map(item => <details key={item.id} className="workspace-inline-details">
        <summary>{item.symbol} · {item.timeframe} · {item.facts.status ?? item.facts.signal ?? item.stage} · {new Date(item.observed_at).toISOString().replace('T', ' ').slice(0, 19)} UTC</summary>
        <p>{item.facts.decision_code ?? item.facts.reasons?.join(' · ') ?? 'No reason supplied'}</p>
        {item.stage === 'ANALYSIS' && <p>Confidence {item.facts.confidence ?? 'unavailable'} · {item.facts.quality} · {item.facts.regime}</p>}
        {item.facts.order_id && <p>Broker order {item.facts.order_id}</p>}
        {item.facts.factors && <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(item.facts.factors, null, 2)}</pre>}
      </details>)}
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
