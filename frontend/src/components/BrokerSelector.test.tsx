// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BrokerItemStatusDTO, BrokerStatusResponse } from '../types/api';
import { BrokerSelector } from './BrokerSelector';

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

describe('BrokerSelector', () => {
  let host: HTMLDivElement;
  let root: Root;

  const render = async (
    brokerStatus: BrokerStatusResponse | null,
    onSelectBroker: (broker: string) => Promise<void>,
  ) => {
    await act(async () => {
      root.render(<BrokerSelector brokerStatus={brokerStatus} onSelectBroker={onSelectBroker} />);
    });
  };

  const select = () => host.querySelector('select[aria-label="Active broker"]') as HTMLSelectElement;
  const options = () => Array.from(select().options);

  const changeTo = async (broker: string) => {
    await act(async () => {
      select().value = broker;
      select().dispatchEvent(new Event('change', { bubbles: true }));
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

  it('renders all four broker options with demo labels', async () => {
    await render(status(), vi.fn());
    const labels = options().map(option => option.textContent ?? '');
    expect(labels.some(label => label.includes('MT5 Demo'))).toBe(true);
    expect(labels.some(label => label.includes('Weltrade Demo'))).toBe(true);
    expect(labels.some(label => label.includes('Deriv Demo'))).toBe(true);
    expect(labels.some(label => label.includes('Simulation (Test Only)'))).toBe(true);
    expect(options()).toHaveLength(4);
  });

  it('identifies the active broker as the selected value', async () => {
    await render(status(), vi.fn());
    expect(select().value).toBe('mt5');
    const activeOption = options().find(option => option.value === 'mt5');
    expect(activeOption?.textContent).toContain('●');
  });

  it('invokes the selection callback with the chosen broker id', async () => {
    const onSelectBroker = vi.fn().mockResolvedValue(undefined);
    await render(status(), onSelectBroker);
    await changeTo('deriv');
    expect(onSelectBroker).toHaveBeenCalledTimes(1);
    expect(onSelectBroker).toHaveBeenCalledWith('deriv');
  });

  it('does not invoke the callback when re-selecting the active broker', async () => {
    const onSelectBroker = vi.fn().mockResolvedValue(undefined);
    await render(status(), onSelectBroker);
    await changeTo('mt5');
    expect(onSelectBroker).not.toHaveBeenCalled();
  });

  it('disables options that cannot be switched to and shows the blocked reason', async () => {
    const blocked = status({
      can_switch: false,
      switch_blocked_reason: '2 unresolved durable execution intent(s) (PENDING/UNKNOWN) must be resolved before switching brokers',
      brokers: [
        item('mt5', { is_active: true, can_switch: false }),
        item('weltrade', { can_switch: false, switch_blocked_reason: 'unresolved intents' }),
        item('deriv', { can_switch: false, switch_blocked_reason: 'unresolved intents' }),
        item('simulation', { can_switch: false, switch_blocked_reason: 'unresolved intents' }),
      ],
    });
    await render(blocked, vi.fn());
    for (const option of options()) {
      if (option.value !== 'mt5') expect(option.disabled).toBe(true);
    }
    expect(host.textContent).toContain('unresolved durable execution intent(s)');
  });

  it('disables an unavailable broker option with its configuration error', async () => {
    const withUnavailable = status({
      brokers: [
        item('mt5', { is_active: true, can_switch: false }),
        item('weltrade', { is_configured: false, is_available: false, can_switch: false, error_message: 'Missing required Weltrade configuration: JQE_WELTRADE_TERMINAL_PATH' }),
        item('deriv'),
        item('simulation'),
      ],
    });
    await render(withUnavailable, vi.fn());
    const weltrade = options().find(option => option.value === 'weltrade');
    expect(weltrade?.disabled).toBe(true);
    expect(weltrade?.title).toContain('JQE_WELTRADE_TERMINAL_PATH');
  });

  it('renders API errors from a failed switch', async () => {
    const onSelectBroker = vi.fn().mockRejectedValue(new Error('HTTP 409: unresolved durable execution intents'));
    await render(status(), onSelectBroker);
    await changeTo('deriv');
    const alert = host.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent).toContain('HTTP 409');
  });

  it('shows a switching state while the selection is in flight', async () => {
    let release: () => void = () => undefined;
    const pending = new Promise<void>(resolve => { release = resolve; });
    const onSelectBroker = vi.fn().mockReturnValue(pending);
    await render(status(), onSelectBroker);
    await act(async () => {
      select().value = 'simulation';
      select().dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(host.textContent).toContain('SWITCHING');
    expect(select().disabled).toBe(true);
    await act(async () => { release(); });
    expect(host.textContent).not.toContain('SWITCHING');
  });
});
