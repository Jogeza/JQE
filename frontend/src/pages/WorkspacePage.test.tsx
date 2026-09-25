// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  BrokerStatusResponse, ExecutionSafetyResponse, ObservationHealthResponse,
  OfflineMonitoringResponse, ResourceState, RiskStatusResponse, WatchlistCapUsageResponse,
  WatchlistResponse, ExecutionStateResponse,
} from '../types/api';
import type { TelemetryLifecycle } from '../services/telemetryLifecycle';
import { WorkspacePage } from './WorkspacePage';
import { formatAge, panelState, validAssessment, validBroker, WORKSPACE_FRESHNESS_THRESHOLDS_MS } from './workspaceEvidence';

vi.mock('../components/MarketChart', () => ({ MarketChart: () => <div data-testid="market-chart">Chart</div> }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const observed = '2026-09-20T12:00:00Z';
const resource = <T,>(data: T | null, overrides: Partial<ResourceState<T>> = {}): ResourceState<T> => ({
  data, loading: false, error: null, lastUpdated: null, stale: false, ...overrides,
});
const broker = {
  active_broker: 'mt5', connected: true, observation_state: 'OBSERVED', observed_at: observed,
  active_broker_identity: { broker: 'mt5', account_id_masked: '***', demo_guard_passed: true, verified_at: observed },
} as BrokerStatusResponse;
const assessment = {
  schema_version: 1, symbol: 'FX Vol 20', timeframe: 'M1', observed_at: observed, candle_close_time: observed, expires_at: '2026-09-20T13:00:00Z',
  direction: 'NO_TRADE', setup_state: 'BLOCKED', confidence_score: 25, reason_codes: ['NO_SIGNAL'], evidence: [
    { factor: 'trend', score: 5, maximum_score: 20, assessment: 'WEAK' },
  ], data_freshness: { status: 'CURRENT', reason_codes: ['CANDLE_CURRENT'] },
  risk_authorization: { status: 'BLOCKED', reason_codes: ['RISK_BLOCKED'] },
  execution_authorization: { status: 'BLOCKED', reason_codes: ['ANALYSIS_ONLY'] },
} as OfflineMonitoringResponse['assessment'];
const monitoring = { assessment, broker_execution_enabled: false } as OfflineMonitoringResponse;
const watchlist = { items: [
  { symbol: 'FX Vol 20', timeframe: 'M1', scope: 'default', added_at: observed },
  { symbol: 'Unexpected Name', timeframe: 'M5', scope: 'default', added_at: observed },
], count: 2 } as WatchlistResponse;
const caps = { observed_at: observed, items: [
  { symbol: 'FX Vol 20', timeframe: 'M1', scope: 'default', daily_count: 1, daily_limit: 2,
    daily_remaining: 1, utc_date: '2026-09-20', reset_at: '2026-09-21T00:00:00Z', available: true },
] } as WatchlistCapUsageResponse;
const lifecycle = { state: 'LIVE', snapshot: monitoring, assessment, lastSuccessfulContact: null, reason: 'current' } as TelemetryLifecycle;
const health = { running: true, healthy: true, updated_at: observed, last_success_at: observed } as ObservationHealthResponse;

type Props = React.ComponentProps<typeof WorkspacePage>;
const baseProps = (): Props => ({
  broker: resource(broker), safety: resource(null as ExecutionSafetyResponse | null),
  risk: resource(null as RiskStatusResponse | null), monitoring: resource(monitoring),
  observationHealth: resource(null as ObservationHealthResponse | null),
  watchlist: resource(watchlist), caps: resource(caps),
  selectedSymbol: 'FX Vol 20', selectedTimeframe: 'M1', lifecycle, onNavigate: vi.fn(),
});

describe('WorkspacePage', () => {
  let host: HTMLDivElement;
  let root: Root;
  const render = async (overrides: Partial<Props> = {}) => {
    await act(async () => root.render(<WorkspacePage {...baseProps()} {...overrides} />));
  };
  const panel = (name: string) => host.querySelector(`[aria-label="${name}"]`) as HTMLElement;
  const demoCard = () => host.querySelector('.workspace-demo-result') as HTMLElement;
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-20T12:01:00Z'));
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it('renders LOADING state', async () => {
    await render({ watchlist: resource<WatchlistResponse>(null, { loading: true }) });
    expect(panel('Watchlist').dataset.state).toBe('LOADING');
  });
  it('renders LIVE state', async () => {
    await render();
    expect(panel('Watchlist').dataset.state).toBe('LIVE');
  });
  it('renders STALE state', async () => {
    await render({ watchlist: resource(watchlist, { stale: true }) });
    expect(panel('Watchlist').dataset.state).toBe('STALE');
  });
  it('renders OFFLINE state for prior data with a failed refresh', async () => {
    await render({ watchlist: resource(watchlist, { error: 'connection lost', stale: true }) });
    expect(panel('Watchlist').dataset.state).toBe('OFFLINE');
  });
  it('renders UNAVAILABLE state', async () => {
    await render({ watchlist: resource<WatchlistResponse>(null) });
    expect(panel('Watchlist').dataset.state).toBe('UNAVAILABLE');
  });
  it('renders ERROR state for a failed first request', async () => {
    await render({ watchlist: resource<WatchlistResponse>(null, { error: 'request failed' }) });
    expect(panel('Watchlist').dataset.state).toBe('ERROR');
    expect(host.textContent).toContain('Watchlist error: request failed');
  });
  it('rejects a malformed broker payload', async () => {
    await render({ broker: resource({ active_broker: 'mt5', connected: 'yes' } as unknown as BrokerStatusResponse) });
    expect(panel('Readiness').dataset.state).toBe('UNAVAILABLE');
    expect(host.textContent).toContain('Reported active brokerunavailable');
  });
  it('rejects a malformed assessment payload', async () => {
    await render({ monitoring: resource({ assessment: { observed_at: observed } } as OfflineMonitoringResponse) });
    expect(panel('Decision trail').dataset.state).toBe('UNAVAILABLE');
    expect(host.textContent).toContain('No current assessment');
  });
  it('renders decision-trail reason codes and an unavailable missing factor', async () => {
    await render();
    expect(panel('Decision trail').textContent).toContain('NO_SIGNAL');
    expect(panel('Decision trail').textContent).toContain('CANDLE_CURRENT');
    expect(panel('Decision trail').textContent).toContain('RISK_BLOCKED');
    expect(panel('Decision trail').textContent).toContain('ANALYSIS_ONLY');
    expect(panel('Decision trail').textContent).toContain('structure: unavailable');
  });
  it('renders supplied reason codes and explicit missing-code text on a fresh assessment without not reached', async () => {
    const partialReasons = {
      ...assessment!,
      reason_codes: [],
      data_freshness: { ...assessment!.data_freshness, reason_codes: ['FRESH_CODE'] },
      risk_authorization: { ...assessment!.risk_authorization, reason_codes: ['RISK_CODE'] },
      execution_authorization: { ...assessment!.execution_authorization, reason_codes: [] },
    };
    await render({ monitoring: resource({ ...monitoring, assessment: partialReasons }) });
    expect(panel('Decision trail').textContent).toContain('FRESH_CODE');
    expect(panel('Decision trail').textContent).toContain('RISK_CODE');
    expect(panel('Decision trail').textContent).toContain('No reason code supplied');
    expect(panel('Decision trail').textContent).not.toContain('not reached');
  });
  it('shows one stale no-current-assessment state without stage-level not reached labels', async () => {
    await render({ monitoring: resource({ ...monitoring, assessment: null }), lifecycle: { ...lifecycle, assessment: null } });
    expect(panel('Decision trail').dataset.state).toBe('STALE');
    expect(panel('Decision trail').textContent).toContain('No current assessment');
    expect(panel('Decision trail').textContent).not.toContain('not reached');
    expect(panel('Decision trail').textContent).toContain('trend: unavailable');
    expect(panel('Decision trail').textContent).toContain('risk: unavailable');
  });
  it('keeps broker context separate from the canonical assessment', async () => {
    await render();
    const context = host.querySelector('.workspace-context') as HTMLElement;
    expect(context.textContent).toContain('Separate broker context');
    expect(context.textContent).toContain('GET /brokers/status');
    expect(context.closest('[aria-label="Decision trail"]')).toBe(panel('Decision trail'));
  });
  it.each([
    ['LOADING', resource<ObservationHealthResponse>(null, { loading: true })],
    ['LIVE', resource(health)],
    ['STALE', resource(health, { stale: true })],
    ['OFFLINE', resource(health, { stale: true, error: 'connection lost' })],
    ['UNAVAILABLE', resource<ObservationHealthResponse>(null)],
    ['ERROR', resource<ObservationHealthResponse>(null, { error: 'request failed' })],
  ] as const)('renders observation heartbeat %s', async (state, observationHealth) => {
    await render({ observationHealth });
    expect(host.querySelector('[aria-label="Observation-daemon heartbeat"]')?.getAttribute('data-state')).toBe(state);
  });
  it('rejects invalid timestamps', async () => {
    expect(validBroker({ ...broker, observed_at: 'invalid' })).toBe(false);
    expect(validAssessment({ ...assessment, candle_close_time: 'invalid' })).toBe(false);
  });
  it('derives both broker freshness badges from observation age', async () => {
    await render();
    expect(panel('Readiness').dataset.state).toBe('LIVE');
    expect(host.querySelector('.workspace-title .workspace-eyebrow')?.textContent).toContain('broker status LIVE');
    vi.setSystemTime(new Date(Date.parse(observed) + WORKSPACE_FRESHNESS_THRESHOLDS_MS.brokerStatus + 1));
    await render();
    expect(panel('Readiness').dataset.state).toBe('STALE');
    expect(host.querySelector('.workspace-title .workspace-eyebrow')?.textContent).toContain('broker status STALE');
    expect(host.querySelector('.workspace-title .workspace-eyebrow')?.textContent).not.toContain('broker status LIVE');
  });
  it('uses one human broker age in the top card and MT5 checklist detail', async () => {
    vi.setSystemTime(new Date('2026-09-27T12:00:00Z'));
    await render();
    const facts = host.querySelector('[aria-label="Broker and execution status"]') as HTMLElement;
    const connection = host.querySelector('[aria-label="MT5 connection"]') as HTMLElement;
    expect(facts.textContent).toContain('Broker-status observation age7d 0h');
    expect(connection.textContent).toContain('age 7d 0h');
    expect(connection.textContent).toContain(new Date(observed).toLocaleString('en-GB'));
  });
  it('formats elapsed times as compact human durations', () => {
    vi.setSystemTime(new Date('2026-09-27T12:00:00Z'));
    expect(formatAge('2026-09-20T12:00:00Z')).toBe('7d 0h');
    expect(formatAge('2026-09-26T01:00:00Z')).toBe('1d 11h');
    expect(formatAge('2026-09-23T14:00:00Z')).toBe('3d 22h');
  });
  it('shows only a masked account identity', async () => {
    await render();
    expect(host.textContent).toContain('Masked account');
    expect(host.textContent).toContain('***');
  });
  it('rejects a mismatched broker identity for demo verification', async () => {
    await render({ broker: resource({ ...broker, active_broker_identity: { ...broker.active_broker_identity!, broker: 'deriv' } }) });
    expect(demoCard().textContent).toContain('unverified · identity mismatch');
    expect(demoCard().classList).toContain('workspace-demo-result-danger');
    expect(host.textContent).toContain(new Date(observed).toLocaleString('en-GB'));
  });
  it('explains stale broker snapshot verification with neutral styling', async () => {
    await render({ broker: resource(broker, { stale: true }) });
    expect(demoCard().textContent).toContain('unverified · snapshot stale (snapshot age 1m)');
    expect(demoCard().classList).toContain('workspace-demo-result-neutral');
    expect(host.textContent).toContain(new Date(observed).toLocaleString('en-GB'));
  });
  it('explains a missing verification time with neutral styling', async () => {
    await render({ broker: resource({ ...broker, active_broker_identity: { ...broker.active_broker_identity!, verified_at: null } }) });
    expect(demoCard().textContent).toContain('unverified · no verification time');
    expect(demoCard().classList).toContain('workspace-demo-result-neutral');
  });
  it('shows demo verification age and expires Yes after the 24-hour threshold', async () => {
    await render();
    expect(host.textContent).toContain('Demo verifiedYes · age 1m');
    const expiredVerification = new Date(Date.now() - WORKSPACE_FRESHNESS_THRESHOLDS_MS.demoVerification - 1).toISOString();
    await render({ broker: resource({ ...broker, observed_at: new Date().toISOString(), active_broker_identity: { ...broker.active_broker_identity!, verified_at: expiredVerification } }) });
    expect(demoCard().textContent).toContain('unverified · evidence expired (age 1d 0h)');
    expect(demoCard().classList).toContain('workspace-demo-result-neutral');
    expect(host.textContent).toContain(new Date(expiredVerification).toLocaleString('en-GB'));
    expect(host.textContent).not.toContain('Demo verifiedYes');
  });
  it('shows only demo guard failure when guard and identity both fail', async () => {
    await render({ broker: resource({ ...broker, active_broker_identity: { ...broker.active_broker_identity!, broker: 'deriv', demo_guard_passed: false } }) });
    expect(demoCard().textContent).toContain('unverified · demo guard not passed');
    expect(demoCard().textContent).not.toContain('identity mismatch');
    expect(demoCard().classList).toContain('workspace-demo-result-danger');
  });
  it('shows top-bar connection and demo verification separately', async () => {
    await render();
    const facts = host.querySelector('[aria-label="Broker and execution status"]') as HTMLElement;
    expect(facts.textContent).toContain('Snapshot-reported connectionYes · snapshot reported');
    expect(facts.textContent).toContain('Demo verifiedYes');
    expect(facts.querySelectorAll(':scope > div')).toHaveLength(7);
  });
  it('renders the connected execution status when supplied', async () => {
    await render({ execution: resource({ connected: true, open_positions_count: 2 } as ExecutionStateResponse) });
    expect(host.querySelector('[aria-label="Broker and execution status"]')?.textContent).toContain('Executionconnected · 2 open');
    expect(panel('Readiness').textContent).toContain('Execution statusConnected · 2 open positions');
  });
  it('does not offer broker switching in Workspace', async () => {
    await render();
    expect(host.textContent).toContain('Switching not available yet.');
    expect(host.querySelector('select')).toBeNull();
  });
  it('preserves existing broker-page switching wiring', () => {
    const app = readFileSync('src/App.tsx', 'utf8');
    expect(app).toContain('onSelectBroker={handleSelectBroker}');
    expect(app).toContain("jqeApi.selectBroker(broker, 'dashboard')");
  });
  it('shows the backend-reported JQE AI status', async () => {
    await render();
    await act(async () => (host.querySelector('.workspace-ai-launcher') as HTMLButtonElement).click());
    expect(host.querySelector('[role="dialog"]')?.textContent).toContain('JQE AI · UNAVAILABLE');
    expect(host.querySelector('[role="dialog"] input')).toBeNull();
  });
  it('closes AI dialog with Escape and restores focus', async () => {
    await render();
    const launcher = host.querySelector('.workspace-ai-launcher') as HTMLButtonElement;
    launcher.focus();
    await act(async () => launcher.click());
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(host.querySelector('[aria-label="JQE AI"]')).toBeNull();
    expect(document.activeElement).toBe(launcher);
  });
  it('uses command palette only for navigation', async () => {
    const onNavigate = vi.fn();
    await render({ onNavigate });
    await act(async () => (host.querySelector('.workspace-command') as HTMLButtonElement).click());
    await act(async () => (Array.from(host.querySelectorAll('.workspace-palette nav button')).find(button => button.textContent === 'Markets') as HTMLButtonElement).click());
    expect(onNavigate).toHaveBeenCalledWith('markets');
  });
  it('opens palette with Control K and closes with Escape', async () => {
    await render();
    const trigger = host.querySelector('.workspace-command') as HTMLButtonElement;
    trigger.focus();
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })));
    expect(host.querySelector('[aria-label="Find page"]')).toBe(document.activeElement);
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(host.querySelector('.workspace-palette')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
  it('opens palette with Command K', async () => {
    await render();
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true })));
    expect(host.querySelector('.workspace-palette')).not.toBeNull();
  });
  it('keeps keyboard focus inside the AI dialog', async () => {
    await render();
    const launcher = host.querySelector('.workspace-ai-launcher') as HTMLButtonElement;
    await act(async () => launcher.click());
    const close = host.querySelector('.workspace-ai-panel button') as HTMLButtonElement;
    close.focus();
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    await act(async () => window.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(close);
  });
  it('displays every returned watchlist row', async () => {
    await render();
    expect(panel('Watchlist').textContent).toContain('FX Vol 20');
    expect(panel('Watchlist').textContent).toContain('Unexpected Name');
  });
  it('routes a watchlist selection to the canonical market context', async () => {
    const onMarketChange = vi.fn();
    await render({ onMarketChange });
    await act(async () => (host.querySelector('[aria-label="Analyze Unexpected Name M5"]') as HTMLButtonElement).click());
    expect(onMarketChange).toHaveBeenCalledWith('Unexpected Name', 'M5');
    expect(host.querySelector('[aria-label="Analyze FX Vol 20 M1"]')?.getAttribute('aria-current')).toBe('true');
  });
  it('labels missing row freshness', async () => {
    await render();
    expect(panel('Watchlist').querySelectorAll('li small')).toHaveLength(2);
    expect(panel('Watchlist').textContent).toContain('Row freshness unavailable');
  });
  it('distinguishes empty and unavailable watchlists', async () => {
    await render({ watchlist: resource({ items: [], count: 0 }) });
    expect(panel('Watchlist').textContent).toContain('Watchlist is empty.');
    await render({ watchlist: resource<WatchlistResponse>(null) });
    expect(panel('Watchlist').textContent).toContain('Watchlist unavailable');
  });
  it('distinguishes cap usage from unavailable cap projection', async () => {
    await render();
    expect(panel('Instrument caps').textContent).toContain('1 / 2 today');
    await render({ caps: resource<WatchlistCapUsageResponse>(null) });
    expect(panel('Instrument caps').textContent).toContain('Cap data unavailable');
  });
  it('shows an unavailable chart when active analysis has no candles', async () => {
    await render();
    expect(panel('Market chart').dataset.state).toBe('UNAVAILABLE');
    expect(panel('Market chart').textContent).toContain('Active market analysis is unavailable.');
    expect(host.querySelector('[data-testid="market-chart"]')).toBeNull();
    expect(host.querySelector('.workspace-chart-overlay')?.textContent).toContain('NO_MARKET_SNAPSHOT');
    expect(panel('Market chart').classList).toContain('workspace-chart-unavailable');
    expect(panel('Market chart').textContent).toContain('strategy, setup, and candles share one observation.');
    expect(panel('Market chart').textContent).not.toContain('Selected FX Vol 20 / M1');
    const css = readFileSync('src/pages/WorkspacePage.css', 'utf8');
    expect(css).toContain('.workspace-chart-unavailable .workspace-chart-frame { min-height: 96px; }');
  });
  it('limits quick actions to frontend navigation', async () => {
    const onNavigate = vi.fn();
    await render({ onNavigate });
    await act(async () => (Array.from(panel('Quick actions').querySelectorAll('button')).find(button => button.textContent === 'Open Watchlist') as HTMLButtonElement).click());
    expect(onNavigate).toHaveBeenCalledWith('watchlist');
  });
  it('performs no network mutation from new Workspace code', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await render();
    await act(async () => (host.querySelector('.workspace-ai-launcher') as HTMLButtonElement).click());
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(panelState(resource(watchlist))).toBe('LIVE');
  });
});
