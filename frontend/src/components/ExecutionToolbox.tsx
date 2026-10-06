import React, { useState } from 'react';
import type { PositionDTO, TradeHistoryDTO } from '../types/api';
import { formatTime, type PanelState } from '../pages/workspaceEvidence';

interface ExecutionToolboxProps {
  positions: PositionDTO[];
  trades: TradeHistoryDTO[];
  state: PanelState;
  currency?: string | null;
  observedAt?: string | null;
}

const price = (value: number | null, decimals: number) => value == null ? '—' : value.toFixed(decimals);
const money = (value: number, currency?: string | null) => `${value > 0 ? '+' : ''}${value.toFixed(2)}${currency ? ` ${currency}` : ''}`;
const tone = (value: number) => value > 0 ? ' is-profit' : value < 0 ? ' is-loss' : '';
const sideTone = (side: string) => side === 'BUY' ? ' is-buy' : side === 'SELL' ? ' is-sell' : '';

export const ExecutionToolbox: React.FC<ExecutionToolboxProps> = ({ positions, trades, state, currency = null, observedAt = null }) => {
  const [tab, setTab] = useState<'positions' | 'history'>('positions');

  return <section className="workspace-card workspace-toolbox" data-state={state} aria-label="Execution and history">
    <div className="workspace-card-heading"><h2>Execution &amp; history</h2><span className="workspace-state">{state === 'ERROR' ? 'UNAVAILABLE' : state}</span></div>
    <div className="workspace-toolbox-tabs" role="tablist" aria-label="Execution and history views">
      <button type="button" role="tab" aria-selected={tab === 'positions'} onClick={() => setTab('positions')}>
        Positions <em>{positions.length}</em>
      </button>
      <button type="button" role="tab" aria-selected={tab === 'history'} onClick={() => setTab('history')}>
        History <em>{trades.length}</em>
      </button>
    </div>
    {state !== 'LIVE' && <p className="workspace-empty">Terminal observation {state.toLowerCase()} · no current broker records.</p>}
    {tab === 'positions'
      ? <ul className="workspace-toolbox-rows" aria-label="Open positions">
          {positions.length === 0 && <li className="workspace-toolbox-empty">No open positions reported.</li>}
          {positions.map(position => <li key={position.id}>
            <div className="workspace-toolbox-row-top">
              <strong>{position.symbol}</strong>
              <em className={`workspace-toolbox-side${sideTone(position.side)}`}>{position.side}</em>
              <span className="workspace-toolbox-volume">{position.volume}</span>
              <span className={`workspace-toolbox-profit${tone(position.profit)}`}>{money(position.profit, currency)}</span>
            </div>
            <small>#{position.id} · {price(position.open_price, position.price_decimals)} → {price(position.current_price, position.price_decimals)} · SL {price(position.stop_loss, position.price_decimals)} · TP {price(position.take_profit, position.price_decimals)}</small>
          </li>)}
        </ul>
      : <ul className="workspace-toolbox-rows" aria-label="Closed trade history">
          {trades.length === 0 && <li className="workspace-toolbox-empty">No closed trades in the returned window.</li>}
          {[...trades].reverse().map(trade => <li key={trade.id}>
            <div className="workspace-toolbox-row-top">
              <strong>{trade.symbol}</strong>
              <em className={`workspace-toolbox-side${sideTone(trade.side)}`}>{trade.side}</em>
              <span className="workspace-toolbox-volume">{trade.volume}</span>
              <span className={`workspace-toolbox-profit${tone(trade.profit)}`}>{money(trade.profit, currency)}</span>
            </div>
            <small>#{trade.id} · {price(trade.open_price, trade.price_decimals)} → {price(trade.close_price, trade.price_decimals)} · closed {formatTime(trade.close_time)}</small>
          </li>)}
        </ul>}
    <small className="workspace-toolbox-source">Weltrade terminal · observed {formatTime(observedAt)}{currency ? ` · ${currency}` : ''}</small>
  </section>;
};
