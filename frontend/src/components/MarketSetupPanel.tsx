import React, { useState } from 'react';
import { AlertCircle, BrainCircuit, ChevronDown, Clock, Info, LockKeyhole, Play, ShieldCheck } from 'lucide-react';
import { jqeApi } from '../services/api';
import type { MarketSetup, PaperExecutionOutcomeDTO } from '../types/api';

interface MarketSetupPanelProps {
  setup: MarketSetup | null;
  loading: boolean;
  stale: boolean;
  onRecorded: () => void;
}

const price = (value: string | null) => value ?? '—';

const formatUtc = (isoString: string | null | undefined): string => {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (Number.isNaN(d.getTime())) return isoString;
    return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
  } catch {
    return isoString;
  }
};

export const MarketSetupPanel: React.FC<MarketSetupPanelProps> = ({ setup, loading, stale, onRecorded }) => {
  const [submitting, setSubmitting] = useState(false);
  const [outcome, setOutcome] = useState<PaperExecutionOutcomeDTO | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isExpired = setup?.setup_state === 'EXPIRED';
  const canExecute = setup?.setup_state === 'READY' && !stale && !submitting && !isExpired;
  const directionDisplay = setup?.direction === 'NO_TRADE' ? 'NO TRADE' : setup?.direction ?? '—';

  const execute = async () => {
    if (!setup || !canExecute) return;
    setSubmitting(true);
    setError(null);
    try {
      const recorded = await jqeApi.executePaperSetup(setup.setup_id);
      setOutcome(recorded);
      onRecorded();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Paper execution failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="quant-panel market-setup-panel" aria-label="AI market setup">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <BrainCircuit size={14} />
          <span>AI Market Analyst</span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {setup?.market_regime === 'UNKNOWN' && (
            <span className="badge badge-amber" title="Market regime is unclassified">
              REGIME UNKNOWN
            </span>
          )}
          <span className="badge badge-neutral">DETERMINISTIC · RESEARCH ONLY</span>
        </div>
      </div>

      <div className="quant-panel-body market-setup-body">
        {!setup ? (
          <div className="setup-empty">{loading ? 'Analyzing the latest closed candle…' : 'Structured setup unavailable.'}</div>
        ) : (
          <>
            {/* Top Command Row: Direction, Score, State */}
            <div className="setup-command-row">
              <div>
                <span className="operations-eyebrow">Strategy Conclusion</span>
                <strong className={`setup-direction setup-${setup.direction.toLowerCase()}`}>{directionDisplay}</strong>
                <small>{setup.symbol} · {setup.timeframe} · Regime: {setup.market_regime}</small>
              </div>

              <div className={`setup-score ${isExpired ? 'setup-score-muted' : ''}`}>
                <span>Quality score {isExpired ? '(EXPIRED)' : ''}</span>
                <strong className="font-mono">{setup.confidence_score}<small>/100</small></strong>
                <small>{setup.confidence_method}</small>
              </div>

              <div style={{ textAlign: 'right' }}>
                <span className={`badge ${setup.setup_state === 'READY' ? 'badge-bull' : setup.setup_state === 'EXPIRED' ? 'badge-neutral' : 'badge-amber'}`}>
                  {setup.setup_state}
                </span>
                {setup.data_freshness.freshness_state && (
                  <div style={{ marginTop: '4px', fontSize: '10px', color: 'var(--text-dark-muted)' }}>
                    Data: <strong>{setup.data_freshness.freshness_state}</strong>
                  </div>
                )}
              </div>
            </div>

            {/* Factual Timestamps */}
            <div className="setup-timestamps-card">
              <div title="Timestamp when setup was observed">
                <Clock size={11} /> Observed: <strong>{formatUtc(setup.observed_at)}</strong>
              </div>
              <div title="Timestamp of candle close evaluated">
                <Clock size={11} /> Candle Close: <strong>{formatUtc(setup.candle_close_time)}</strong>
              </div>
              <div title="Timestamp when this setup expires">
                <Clock size={11} /> Expiry: <strong>{formatUtc(setup.expires_at)}</strong>
              </div>
            </div>

            {/* AI Analyst Grounded Explanation */}
            {setup.explanation && (
              <div className="setup-explanation-card">
                <div className="setup-explanation-header">
                  <Info size={12} />
                  <span>Analyst Synthesis</span>
                </div>
                <p className="setup-explanation-summary">{setup.explanation.decision_summary}</p>
                {setup.explanation.supporting_evidence.length > 0 && (
                  <div className="setup-explanation-drivers">
                    <span>Supporting evidence:</span>
                    <div className="setup-driver-tags">
                      {setup.explanation.supporting_evidence.map((drv, idx) => (
                        <span key={idx} className="setup-driver-tag">{drv}</span>
                      ))}
                    </div>
                  </div>
                )}
                {(setup.explanation.conflicting_evidence.length > 0 || setup.explanation.freshness_warning) && (
                  <div className="setup-explanation-risks">
                    <AlertCircle size={11} color="var(--chart-accent-secondary)" />
                    <span>{[
                      ...setup.explanation.conflicting_evidence,
                      ...(setup.explanation.freshness_warning ? [setup.explanation.freshness_warning] : []),
                    ].join(' · ')}</span>
                  </div>
                )}
              </div>
            )}

            {/* Server-Authoritative Price Levels */}
            <div className="setup-levels">
              <div>
                <span>Entry</span>
                <strong className="font-mono">{setup.direction === 'NO_TRADE' ? 'None (No Trade)' : price(setup.entry_price)}</strong>
              </div>
              <div>
                <span>Stop</span>
                <strong className="font-mono">{setup.direction === 'NO_TRADE' ? 'None (No Trade)' : price(setup.stop_loss)}</strong>
              </div>
              <div>
                <span>Target</span>
                <strong className="font-mono">{setup.direction === 'NO_TRADE' ? 'None (No Trade)' : price(setup.targets[0] ?? null)}</strong>
              </div>
              <div>
                <span>Reward / Risk</span>
                <strong className="font-mono">{setup.direction === 'NO_TRADE' ? '—' : setup.risk_reward_ratio ?? 'Unavailable'}</strong>
              </div>
            </div>

            {/* Observed Structural Levels (Support / Resistance / Range) */}
            {setup.levels && setup.levels.length > 0 && (
              <div className="setup-structural-levels">
                <span className="operations-eyebrow">Observed Range & Pivot Levels</span>
                <div className="setup-structural-grid">
                  {setup.levels.map((lvl) => (
                    <div key={`${lvl.kind}-${lvl.price}-${lvl.method}`} className="setup-level-pill" title={lvl.method}>
                      <span className="setup-level-name">{lvl.kind}</span>
                      <strong className="font-mono">{lvl.price}</strong>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Multi-factor Confluence vs Win Rate Disclaimer */}
            <div className="setup-confluence-disclaimer">
              <Info size={11} />
              <span>
                <strong>Multi-factor confluence:</strong> Score reflects model alignment across 6 technical pillars. It is an authorization filter, not an empirical probability or historical win rate.
              </span>
            </div>

            {/* Expandable Factor Breakdown */}
            <details className="setup-factor-details">
              <summary className="setup-factor-summary">
                <span>Pillar Assessments ({setup.evidence.length} factors evaluated)</span>
                <ChevronDown size={14} className="details-chevron" />
              </summary>
              <div className="setup-factor-grid" style={{ marginTop: '8px' }}>
                {setup.evidence.map((item) => (
                  <div key={item.factor}>
                    <span>{item.factor.replace('_', ' ')}</span>
                    <strong>{item.assessment}</strong>
                    <small className="font-mono">{item.score}/{item.maximum_score}</small>
                  </div>
                ))}
              </div>
            </details>

            {/* Authorizations and Factual Status Grid */}
            <div className="setup-authorization-grid">
              <div>
                <span><ShieldCheck size={13} /> Risk Authorization</span>
                <strong>{setup.risk_authorization.status}</strong>
                <small>{setup.risk_authorization.reason}</small>
              </div>
              <div>
                <span><LockKeyhole size={13} /> Paper Execution</span>
                <strong>{setup.execution_authorization.status}</strong>
                <small>{setup.execution_authorization.reason}</small>
              </div>
              <div>
                <span>Data Freshness</span>
                <strong>{setup.data_freshness.status}</strong>
                <small>{setup.data_freshness.reason}</small>
              </div>
              <div>
                <span>Historical Win Rate</span>
                <strong>
                  {setup.historical_win_rate.status === 'AVAILABLE'
                    ? `${setup.historical_win_rate.win_rate_percent}%`
                    : 'Unavailable'}
                </strong>
                <small>{setup.historical_win_rate.reason}</small>
              </div>
            </div>

            {setup.invalidation_condition && (
              <p className="setup-invalidation"><strong>Invalidation:</strong> {setup.invalidation_condition}</p>
            )}
            {(setup.conflicts.length > 0 || setup.reason_codes.length > 0) && (
              <p className="setup-conflicts">{[...setup.conflicts, ...setup.reason_codes].join(' · ')}</p>
            )}

            {/* Paper Execution Section */}
            <div className="setup-paper-action">
              <div>
                <strong>Offline Paper Order</strong>
                <span>Revalidates stored setup. Zero broker mutation, zero live risk.</span>
              </div>
              <button
                className="btn-quant btn-quant-primary"
                disabled={!canExecute}
                onClick={execute}
              >
                <Play size={13} /> {submitting ? 'Recording…' : isExpired ? 'Setup Expired' : setup.setup_state === 'READY' ? 'Execute on Paper' : 'Execution Blocked'}
              </button>
            </div>
            {outcome && (
              <div className="setup-outcome" role="status">
                <strong>{outcome.status}</strong>
                <span>{outcome.message}</span>
                <code>{outcome.order_id ?? outcome.reason_codes.join(', ')}</code>
              </div>
            )}
            {error && <div className="setup-outcome setup-outcome-error" role="alert">{error}</div>}
          </>
        )}
      </div>
    </section>
  );
};
