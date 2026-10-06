import React, { useState } from 'react';
import { ChevronUp } from 'lucide-react';
import type { MarketSetup, SignalResponse } from '../types/api';

interface ChartDecisionCardProps {
  signal: SignalResponse | null;
  setup: MarketSetup | null;
  priceDecimals?: number;
  freshness: string;
  latestClosedCandle?: string | null;
}

const VERDICT_LABELS: Record<string, string> = { BUY: 'BUY', SELL: 'SELL', NO_TRADE: 'NO TRADE' };
const verdictTone = (verdict: string | null) => verdict === 'BUY' ? 'buy' : verdict === 'SELL' ? 'sell' : 'neutral';
const formatPrice = (value: string | null | undefined, decimals: number) => {
  if (value == null) return '—';
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toFixed(decimals) : value;
};
const formatState = (state: string) => state.charAt(0) + state.slice(1).toLowerCase();

export const ChartDecisionCard: React.FC<ChartDecisionCardProps> = ({ signal, setup, priceDecimals = 2, freshness, latestClosedCandle = null }) => {
  const [open, setOpen] = useState(true);
  const verdict = signal?.signal ?? setup?.direction ?? null;
  const label = verdict ? VERDICT_LABELS[verdict] ?? verdict : 'NO SIGNAL';
  const confidence = signal?.confidence ?? setup?.confidence_score ?? null;

  if (!open) return <button type="button" className={`chart-decision-pill tone-${verdictTone(verdict)}`}
    aria-expanded={false} aria-label="Expand decision card" onClick={() => setOpen(true)}>
    <span>{label}</span>{confidence != null && <strong>{confidence}</strong>}
  </button>;

  return <aside className="chart-decision-card" aria-label="Decision card">
    <header>
      <span className={`chart-decision-verdict tone-${verdictTone(verdict)}`}>{label}</span>
      {confidence != null && <span className="chart-decision-confidence">confidence {confidence}</span>}
      <button type="button" className="chart-decision-collapse" aria-expanded={true} aria-label="Collapse decision card" onClick={() => setOpen(false)}><ChevronUp size={14} /></button>
    </header>
    {!signal && !setup ? <p className="chart-decision-empty">No signal evidence for this market yet.</p> : <div className="chart-decision-body">
      {setup && <p className="chart-decision-state">{formatState(setup.setup_state)}{setup.risk_reward_ratio ? ` · R:R ${setup.risk_reward_ratio}` : ''}</p>}
      {setup && <div className="chart-decision-levels">
        <span>Entry<strong>{formatPrice(setup.entry_price, priceDecimals)}</strong></span>
        <span>Stop<strong>{formatPrice(setup.stop_loss, priceDecimals)}</strong></span>
        {setup.targets.slice(0, 2).map((target, index) => <span key={index}>{setup.targets.length > 1 ? `Target ${index + 1}` : 'Target'}<strong>{formatPrice(target, priceDecimals)}</strong></span>)}
      </div>}
      {setup?.risk_authorization && <div className="chart-decision-gates">
        <em data-status={setup.risk_authorization.status}>Risk {setup.risk_authorization.status}</em>
        {setup.execution_authorization && <em data-status={setup.execution_authorization.status}>Execution {setup.execution_authorization.status}</em>}
      </div>}
      <small className="chart-decision-freshness">Weltrade · {freshness} · candle {latestClosedCandle ?? 'unavailable'}</small>
      <small className="chart-decision-note">Evidence only · orders need risk and execution authorization.</small>
    </div>}
  </aside>;
};
