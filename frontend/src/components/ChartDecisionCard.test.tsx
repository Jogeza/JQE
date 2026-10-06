// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import type { MarketSetup, SignalResponse } from '../types/api';
import { ChartDecisionCard } from './ChartDecisionCard';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const signal = {
  symbol: 'FX Vol 20', signal: 'BUY', confidence: 82, quality: 'HIGH', score: 0.8, reasons: [],
  regime: 'TRENDING', trend: 'UP', momentum: 'STRONG', volatility: 'NORMAL', liquidity: 'OK',
  confidence_breakdown: null, trade_plan: null, generated_at: '2026-09-20T12:00:00Z', price_decimals: 2,
} as SignalResponse;

const readySetup = {
  direction: 'BUY', setup_state: 'READY', entry_price: '1234.567', stop_loss: '1200.123',
  targets: ['1300.89', '1350.5'], risk_reward_ratio: '2.5',
  risk_authorization: { status: 'AUTHORIZED' }, execution_authorization: { status: 'BLOCKED' },
} as MarketSetup;

const formingSetup = {
  direction: 'NO_TRADE', setup_state: 'FORMING', entry_price: null, stop_loss: null,
  targets: ['1.5'], risk_reward_ratio: null, confidence_score: 25,
  risk_authorization: { status: 'NOT_EVALUATED' },
} as MarketSetup;

describe('ChartDecisionCard', () => {
  let host: HTMLDivElement;
  let root: Root;

  const render = async (props: Partial<React.ComponentProps<typeof ChartDecisionCard>> = {}) => {
    await act(async () => root.render(
      <ChartDecisionCard signal={null} setup={null} freshness="CURRENT" {...props} />,
    ));
  };

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
  });

  it('shows the no-signal empty state with a neutral tone', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render();
    const verdict = host.querySelector('.chart-decision-verdict');
    expect(verdict?.textContent).toBe('NO SIGNAL');
    expect(verdict?.className).toContain('tone-neutral');
    expect(host.textContent).toContain('No signal evidence for this market yet.');
    expect(host.querySelector('.chart-decision-confidence')).toBeNull();
    expect(host.querySelector('.chart-decision-note')).toBeNull();
  });

  it('renders BUY levels, authorization gates, freshness and the evidence-only note', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render({ signal, setup: readySetup, latestClosedCandle: '12:30' });

    const verdict = host.querySelector('.chart-decision-verdict');
    expect(verdict?.textContent).toBe('BUY');
    expect(verdict?.className).toContain('tone-buy');
    expect(host.querySelector('.chart-decision-confidence')?.textContent).toBe('confidence 82');
    expect(host.querySelector('.chart-decision-state')?.textContent).toBe('Ready · R:R 2.5');

    expect(Array.from(host.querySelectorAll('.chart-decision-levels strong')).map(node => node.textContent))
      .toEqual(['1234.57', '1200.12', '1300.89', '1350.50']);
    const levels = Array.from(host.querySelectorAll('.chart-decision-levels span')).map(node => node.textContent ?? '');
    expect(levels[0]).toContain('Entry');
    expect(levels[2]).toContain('Target 1');
    expect(levels[3]).toContain('Target 2');

    const gates = Array.from(host.querySelectorAll('.chart-decision-gates em'));
    expect(gates[0].getAttribute('data-status')).toBe('AUTHORIZED');
    expect(gates[0].textContent).toBe('Risk AUTHORIZED');
    expect(gates[1].getAttribute('data-status')).toBe('BLOCKED');
    expect(gates[1].textContent).toBe('Execution BLOCKED');

    expect(host.querySelector('.chart-decision-freshness')?.textContent).toBe('Weltrade · CURRENT · candle 12:30');
    expect(host.querySelector('.chart-decision-note')?.textContent).toBe('Evidence only · orders need risk and execution authorization.');
  });

  it('collapses to a pill and expands back', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render({ signal, setup: readySetup });

    const collapse = host.querySelector('.chart-decision-collapse') as HTMLButtonElement;
    expect(collapse.getAttribute('aria-label')).toBe('Collapse decision card');
    await act(async () => collapse.click());

    const pill = host.querySelector('.chart-decision-pill') as HTMLButtonElement;
    expect(pill).not.toBeNull();
    expect(pill.getAttribute('aria-expanded')).toBe('false');
    expect(pill.getAttribute('aria-label')).toBe('Expand decision card');
    expect(pill.textContent).toContain('BUY');
    expect(pill.textContent).toContain('82');
    expect(host.querySelector('.chart-decision-card')).toBeNull();

    await act(async () => pill.click());
    expect(host.querySelector('.chart-decision-card')).not.toBeNull();
  });

  it('handles a forming NO_TRADE setup with fallback prices and a single target', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render({ setup: formingSetup });

    const verdict = host.querySelector('.chart-decision-verdict');
    expect(verdict?.textContent).toBe('NO TRADE');
    expect(verdict?.className).toContain('tone-neutral');
    expect(host.querySelector('.chart-decision-state')?.textContent).toBe('Forming');

    expect(Array.from(host.querySelectorAll('.chart-decision-levels strong')).map(node => node.textContent))
      .toEqual(['—', '—', '1.50']);
    expect(Array.from(host.querySelectorAll('.chart-decision-levels span')).map(node => node.textContent ?? '')[2]).toContain('Target');

    const gates = Array.from(host.querySelectorAll('.chart-decision-gates em'));
    expect(gates).toHaveLength(1);
    expect(gates[0].getAttribute('data-status')).toBe('NOT_EVALUATED');
    expect(host.querySelector('.chart-decision-freshness')?.textContent).toBe('Weltrade · CURRENT · candle unavailable');
  });
});
