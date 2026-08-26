import React from 'react';
import { PlayCircle } from 'lucide-react';

export const BacktestPage: React.FC = () => {
  return (
    <div className="dashboard-page-container">
      <div className="quant-panel">
        <div className="quant-panel-header">
          <div className="quant-panel-title">
            <PlayCircle size={14} color="var(--quant-cyan)" />
            <span>Quantitative Backtesting & Replay Suite</span>
          </div>
          <span className="badge badge-neutral">REFERENCE ONLY</span>
        </div>

        <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ padding: '12px', backgroundColor: 'var(--bg-app)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', fontFamily: 'var(--font-mono)', fontSize: '11.5px' }}>
            <div style={{ color: 'var(--quant-green)', fontWeight: 700, marginBottom: '4px' }}>
              Backtest UI execution telemetry is not exposed by the API.
            </div>
            <div style={{ color: 'var(--text-secondary)' }}>
              Documented local command: <code style={{ color: 'var(--quant-cyan)' }}>D:\JQE\venv\Scripts\python.exe -m backtesting.backtest</code>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '10px' }}>
            <div style={{ backgroundColor: 'var(--bg-app)', padding: '10px', borderRadius: 'var(--radius-sm)' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>REPLAY DEPTH</span>
              <div className="font-mono" style={{ fontSize: '16px', fontWeight: 700 }}>CONFIGURED BY CLI</div>
            </div>
            <div style={{ backgroundColor: 'var(--bg-app)', padding: '10px', borderRadius: 'var(--radius-sm)' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>INSTRUMENT / TIMEFRAME</span>
              <div className="font-mono" style={{ fontSize: '16px', fontWeight: 700 }}>CONFIGURED BY CLI</div>
            </div>
            <div style={{ backgroundColor: 'var(--bg-app)', padding: '10px', borderRadius: 'var(--radius-sm)' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>SIMULATION PARAMETERS</span>
              <div className="font-mono" style={{ fontSize: '16px', fontWeight: 700 }}>NOT REPORTED</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
