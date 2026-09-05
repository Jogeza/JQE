import React from 'react';
import { BrainCircuit, ArrowUpRight, ArrowDownRight, Minus } from 'lucide-react';
import { SignalResponse } from '../types/api';
import { formatInstrumentPrice } from '../utils/format';

interface StrategySignalPanelProps {
  signal: SignalResponse | null;
  loading: boolean;
  stale?: boolean;
}

const factorTone = (score: number, value: string) => {
  const status = value.toUpperCase();
  if (score === 0 || ['NONE', 'NEUTRAL', 'UNAVAILABLE', 'UNKNOWN'].includes(status)) return 'neutral';
  if (['GOOD', 'FAVORABLE', 'HEALTHY', 'CLEAR'].includes(status)) return 'positive';
  if (['HIGH', 'WARNING', 'ELEVATED'].includes(status)) return 'warning';
  if (['BLOCKED', 'UNFAVORABLE', 'CRITICAL'].includes(status)) return 'negative';
  return 'accent';
};

export const StrategySignalPanel: React.FC<StrategySignalPanelProps> = ({ signal, loading, stale }) => {
  const currentSignal = signal?.signal;
  const confidence = signal?.confidence ?? 0;
  const breakdown = signal?.confidence_breakdown;
  const plan = signal?.trade_plan;

  const getSignalBadge = () => {
    if (stale) return <span className="badge badge-neutral" style={{ fontSize: '12px', padding: '3px 8px' }}>STALE DECISION</span>;
    if (!currentSignal) return <span className="badge badge-neutral" style={{ fontSize: '12px', padding: '3px 8px' }}>{loading ? 'LOADING' : 'UNKNOWN'}</span>;
    if (currentSignal === 'BUY') {
      return (
        <span className="badge badge-green" style={{ fontSize: '12px', padding: '3px 8px' }}>
          <ArrowUpRight size={14} /> BUY SIGNAL
        </span>
      );
    }
    if (currentSignal === 'SELL') {
      return (
        <span className="badge badge-red" style={{ fontSize: '12px', padding: '3px 8px' }}>
          <ArrowDownRight size={14} /> SELL SIGNAL
        </span>
      );
    }
    return (
      <span className="badge badge-neutral" style={{ fontSize: '12px', padding: '3px 8px' }}>
        <Minus size={14} /> NO TRADE
      </span>
    );
  };

  const factorBars = [
    { label: 'Trend Alignment', score: breakdown?.trend_score ?? 0, max: 25, value: breakdown?.factors?.trend || signal?.trend || 'NEUTRAL' },
    { label: 'Market Structure', score: breakdown?.structure_score ?? 0, max: 20, value: breakdown?.factors?.structure || 'NEUTRAL' },
    { label: 'Liquidity Health', score: breakdown?.liquidity_score ?? 0, max: 20, value: breakdown?.factors?.liquidity || signal?.liquidity || 'NORMAL' },
    { label: 'Momentum Alignment', score: breakdown?.momentum_score ?? 0, max: 15, value: breakdown?.factors?.momentum || signal?.momentum || 'NEUTRAL' },
    { label: 'Volatility Guard', score: breakdown?.volatility_score ?? 0, max: 10, value: breakdown?.factors?.volatility || signal?.volatility || 'NORMAL' },
    { label: 'Risk Environment', score: breakdown?.risk_score ?? 0, max: 10, value: breakdown?.factors?.risk || 'NEUTRAL' },
  ];

  return (
    <div className="quant-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <BrainCircuit size={14} color="var(--quant-cyan)" />
          <span>Strategy Decision & 6-Factor Confidence</span>
        </div>
        <span className="badge badge-neutral">WEIGHTED MODEL</span>
      </div>

      <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {/* Signal & Score Row */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor: 'var(--bg-card-subtle)',
            padding: '12px 16px',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-card)',
          }}
        >
          <div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px', fontWeight: 600 }}>
              CURRENT DECISION ({signal?.symbol || '—'})
            </div>
            {getSignalBadge()}
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '2px', fontWeight: 600 }}>
              CONFIDENCE INDEX
            </div>
            <div className="font-mono" style={{ fontSize: '22px', fontWeight: 800, color: confidence >= 75 ? 'var(--quant-green)' : confidence >= 50 ? 'var(--quant-amber)' : 'var(--text-secondary)' }}>
              {signal ? `${confidence}%` : '—'}
            </div>
          </div>
        </div>

        {/* Compact 6-factor score overview */}
        <div className="factor-score-section">
          <div className="factor-score-header">
            6-Factor Scoring
          </div>

          <div className="factor-score-grid">
            {factorBars.map((fb) => {
              const pct = Math.min(100, Math.max(0, (fb.score / fb.max) * 100));
              const circumference = 2 * Math.PI * 30;
              const tone = factorTone(fb.score, fb.value);
              return (
                <div
                  className={`factor-score-card factor-score-${tone}`}
                  key={fb.label}
                  aria-label={`${fb.label} score ${fb.score} out of ${fb.max}, ${fb.value}`}
                >
                  <div className="factor-score-ring">
                    <svg viewBox="0 0 72 72" aria-hidden="true">
                      <circle className="factor-ring-track" cx="36" cy="36" r="30" />
                      <circle
                        className="factor-ring-value"
                        cx="36"
                        cy="36"
                        r="30"
                        strokeDasharray={circumference}
                        strokeDashoffset={circumference * (1 - pct / 100)}
                      />
                    </svg>
                    <div className="factor-score-number font-mono">
                      <strong>{fb.score}</strong>
                      <span>/{fb.max}</span>
                    </div>
                  </div>
                  <div className="factor-score-copy">
                    <span className="factor-score-label">{fb.label}</span>
                    <span className="factor-score-status">{fb.value}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Trade Plan Details if available */}
        {plan && plan.signal !== 'NO_TRADE' ? (
          <div
            style={{
              backgroundColor: 'var(--bg-card-subtle)',
              border: '1px solid var(--border-card)',
              borderRadius: 'var(--radius-sm)',
              padding: '10px 14px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
              fontSize: '11.5px',
              fontFamily: 'var(--font-mono)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-muted)', fontSize: '10px', fontWeight: 600 }}>
              <span>STRUCTURED TRADE PLAN</span>
              <span style={{ color: 'var(--quant-green)' }}>R:R {plan.risk_reward?.toFixed(1) ?? '—'}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
              <div>
                <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>ENTRY</span>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{plan.entry === null ? '—' : formatInstrumentPrice(plan.entry, signal?.price_decimals)}</div>
              </div>
              <div>
                <span style={{ color: 'var(--quant-red)', fontSize: '10px' }}>STOP LOSS</span>
                <div style={{ fontWeight: 600, color: 'var(--quant-red)' }}>{plan.stop_loss === null ? '—' : formatInstrumentPrice(plan.stop_loss, signal?.price_decimals)}</div>
              </div>
              <div>
                <span style={{ color: 'var(--quant-green)', fontSize: '10px' }}>TAKE PROFIT</span>
                <div style={{ fontWeight: 600, color: 'var(--quant-green)' }}>{plan.take_profit === null ? '—' : formatInstrumentPrice(plan.take_profit, signal?.price_decimals)}</div>
              </div>
            </div>
          </div>
        ) : (
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontStyle: 'italic', padding: '6px 0' }}>
            {signal?.reasons?.length ? `Filter reason: ${signal.reasons.join(', ')}` : signal ? 'No trade plan returned.' : loading ? 'Loading strategy telemetry...' : 'Strategy telemetry unavailable.'}
          </div>
        )}
      </div>
    </div>
  );
};
