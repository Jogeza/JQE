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

  it('offers only Weltrade even with a legacy multi-broker response', async () => {
    await render(status(), vi.fn());
    expect(options().map(option => option.value)).toEqual(['weltrade']);
    expect(options()[0].textContent).toContain('Weltrade SyntX');
  });

  it('does not send unsupported selections', async () => {
    const onSelect = vi.fn();
    await render(status(), onSelect);
    await changeTo('deriv');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('allows recovery to the sole supported broker', async () => {
    const onSelect = vi.fn().mockResolvedValue(undefined);
    await render(status(), onSelect);
    await changeTo('weltrade');
    expect(onSelect).toHaveBeenCalledWith('weltrade');
  });

  it('surfaces the safety block and disables unavailable selection', async () => {
    await render(status({ can_switch: false, switch_blocked_reason: 'Unresolved execution intent',
      brokers: [item('weltrade', { can_switch: false })] }), vi.fn());
    expect(options()[0].disabled).toBe(true);
    expect(host.textContent).toContain('Unresolved execution intent');
  });

  it('surfaces backend selection errors', async () => {
    await render(status(), vi.fn().mockRejectedValue(new Error('Terminal unavailable')));
    await changeTo('weltrade');
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Terminal unavailable');
  });
});
