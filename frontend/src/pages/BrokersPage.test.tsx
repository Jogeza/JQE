// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BrokerItemStatusDTO, BrokerStatusResponse } from '../types/api';
import { BrokersPage } from './BrokersPage';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const item = (broker: string, overrides: Partial<BrokerItemStatusDTO> = {}): BrokerItemStatusDTO => ({
  broker,
  name: broker,
  is_active: false,
  connected: false,
  is_configured: true,
  is_available: true,
  error_message: null,
  can_switch: true,
  switch_blocked_reason: null,
  demo_guard_status: 'UNVERIFIED',
  demo_guard_verified_at: null,
  account_id_masked: null,
  account_server: null,
  account_currency: null,
  account_trade_mode: 'demo',
  environment: null,
  notes: null,
  ...overrides,
});

const status = (overrides: Partial<BrokerStatusResponse> = {}): BrokerStatusResponse => ({
  brokers: [
    item('mt5', { name: 'MT5 Demo', is_active: true, can_switch: false }),
    item('weltrade', { name: 'Weltrade Demo' }),
    item('deriv', { name: 'Deriv Demo' }),
    item('simulation', { name: 'Simulation (Test Only)' }),
  ],
  active_broker: 'mt5',
  active_broker_identity: null,
  emergency_stop_state: 'CLEAR',
  execution_authorization: 'NOT_EVALUATED',
  observed_at: null,
  observation_state: 'NOT_OBSERVED',
  can_switch: true,
  switch_blocked_reason: null,
  unresolved_intent_count: 0,
  broker: 'mt5',
  environment: 'development',
  connected: false,
  last_verified_at: null,
  identity_state: 'NOT_APPLICABLE',
  account_id_masked: null,
  account_server: null,
  account_currency: null,
  account_trade_mode: null,
  ...overrides,
});

const cardFor = (host: HTMLElement, brokerId: string): HTMLElement => {
  const idLine = Array.from(host.querySelectorAll('span.font-mono')).find(
    span => span.textContent === `id: ${brokerId}`,
  );
  if (!idLine) throw new Error(`card for ${brokerId} was not rendered`);
  return idLine.closest('div[style]')?.parentElement as HTMLElement;
};

describe('BrokersPage', () => {
  let host: HTMLDivElement;
  let root: Root;

  const render = async (brokerStatus: BrokerStatusResponse | null) => {
    await act(async () => {
      root.render(<BrokersPage brokerStatus={brokerStatus} loading={false} />);
    });
  };

  beforeEach(() => {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.restoreAllMocks();
  });

  it('renders every configured broker with its own identity', async () => {
    await render(status());
    const text = host.textContent ?? '';
    expect(text).toContain('MT5 Demo');
    expect(text).toContain('Weltrade Demo');
    expect(text).toContain('Deriv Demo');
    expect(text).toContain('Simulation (Test Only)');
    expect(text).toContain('id: weltrade');
    expect(text).toContain('id: mt5');
  });

  it('labels Weltrade demo-guard evidence as Weltrade, never MT5', async () => {
    await render(
      status({
        brokers: [
          item('mt5', {
            name: 'MT5 Demo',
            is_active: true,
            can_switch: false,
            demo_guard_status: 'UNVERIFIED',
            notes: 'DemoOnlyGuard evidence for account ****8111 is not attributable: no configured MT5 Demo account identity',
          }),
          item('weltrade', {
            name: 'Weltrade Demo',
            connected: true,
            demo_guard_status: 'PASSED',
            demo_guard_verified_at: '2026-09-18T22:20:50+00:00',
            account_id_masked: '****8111',
            account_server: 'Weltrade-Demo',
          }),
          item('deriv', { name: 'Deriv Demo' }),
          item('simulation', { name: 'Simulation (Test Only)' }),
        ],
      }),
    );

    const weltrade = cardFor(host, 'weltrade');
    const mt5 = cardFor(host, 'mt5');
    expect(weltrade.textContent).toContain('PASSED');
    expect(weltrade.textContent).toContain('Weltrade-Demo');
    expect(weltrade.textContent).toContain('****8111');
    expect(mt5.textContent).not.toContain('PASSED');
    expect(mt5.textContent).toContain('UNVERIFIED');
    expect(mt5.textContent).toContain('not attributable');
  });

  it('shows a clear reason when a broker is unavailable', async () => {
    await render(
      status({
        brokers: [
          item('mt5', { is_active: true, can_switch: false }),
          item('weltrade', {
            is_configured: false,
            is_available: false,
            can_switch: false,
            error_message: 'Missing required Weltrade configuration: JQE_WELTRADE_TERMINAL_PATH',
            switch_blocked_reason: 'Missing required Weltrade configuration: JQE_WELTRADE_TERMINAL_PATH',
          }),
          item('deriv'),
          item('simulation'),
        ],
      }),
    );
    const weltrade = cardFor(host, 'weltrade');
    expect(weltrade.textContent).toContain('NOT CONFIGURED');
    expect(weltrade.textContent).toContain('UNAVAILABLE');
    expect(weltrade.textContent).toContain('JQE_WELTRADE_TERMINAL_PATH');
  });

  it('surfaces connection, demo-guard, authorization and emergency-stop state', async () => {
    await render(
      status({
        emergency_stop_state: 'ACTIVE',
        execution_authorization: 'BLOCKED',
        observation_state: 'STALE',
        brokers: [
          item('weltrade', {
            name: 'Weltrade Demo',
            is_active: true,
            connected: true,
            can_switch: false,
            demo_guard_status: 'PASSED',
            account_trade_mode: 'demo',
          }),
        ],
        active_broker: 'weltrade',
        active_broker_identity: {
          broker: 'weltrade',
          account_id_masked: '****8111',
          server: 'Weltrade-Demo',
          trade_mode: 'DEMO',
          currency: 'USD',
          verified_at: '2026-09-18T22:20:50+00:00',
          demo_guard_passed: true,
        },
        broker: 'weltrade',
        connected: true,
        identity_state: 'PASSED',
        account_id_masked: '****8111',
        account_server: 'Weltrade-Demo',
        account_trade_mode: 'demo',
      }),
    );
    const text = host.textContent ?? '';
    expect(text).toContain('WELTRADE');
    expect(text).toContain('DEMO MODE');
    expect(text).toContain('VERIFIED DEMO');
    expect(text).toContain('Emergency Stop:');
    expect(text).toContain('ACTIVE');
    expect(text).toContain('BLOCKED');
    expect(text).toContain('CONNECTED · DEMO VERIFIED');
  });
});
