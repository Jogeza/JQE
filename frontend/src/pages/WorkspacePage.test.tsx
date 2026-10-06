// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  BrokerStatusResponse, ExecutionSafetyResponse, ObservationHealthResponse,
  OfflineMonitoringResponse, ResourceState, RiskStatusResponse, WatchlistCapUsageResponse, TerminalObservationResponse,
  WatchlistResponse, ExecutionStateResponse, AssistantStatusResponse, ActiveMarketAnalysisResponse,
} from '../types/api';
import type { TelemetryLifecycle } from '../services/telemetryLifecycle';
import { WorkspacePage } from './WorkspacePage';
import { formatAge, panelState, validAssessment, validBroker, WORKSPACE_FRESHNESS_THRESHOLDS_MS } from './workspaceEvidence';

vi.mock('../components/MarketChart', () => ({ MarketChart: ({ dataStatus }: { dataStatus?: string }) => <div data-testid="market-chart" data-status={dataStatus}>Chart</div> }));
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
  internalDetails: true,
});

describe('Workspace and Settings evidence views', () => {
  let host: HTMLDivElement;
  let root: Root;
  const render = async (overrides: Partial<Props> = {}) => {
    await act(async () => root.render(<><WorkspacePage {...baseProps()} {...overrides} /><WorkspacePage {...baseProps()} {...overrides} configurationOnly /></>));
  };
  const panel = (name: string) => host.querySelector(`[aria-label="${name}"]`) as HTMLElement;
  const demoCard = () => host.querySelector('.workspace-demo-result') as HTMLElement;
  const plain = () => host.children[0] as HTMLElement;
  const settings = () => host.children[1] as HTMLElement;
  it('shows supervisor evidence while terminal observation is unavailable and expires its live glow', async () => {
    await render({observationHealth: resource({execution_supervisor: {state:'RUNNING', updated_at:'2026-09-20T12:01:00Z', stale:false, process_alive:true, execution_enabled:true, cycle_number:19, max_age_seconds:10}} as unknown as ObservationHealthResponse)});
    const evidence = panel('Execution supervisor evidence');
    expect(evidence.dataset.state).toBe('LIVE');
    expect(evidence.textContent).toContain('cycle 19');
    expect(evidence.textContent).toContain('stale No');
    expect(evidence.textContent).toContain('does not authorize orders');
    await act(async () => vi.advanceTimersByTime(15000));
    expect(evidence.dataset.state).toBe('STALE');
    expect(evidence.textContent).toContain('stale Yes');
  });
  it('expires retained supervisor evidence on the clock without a new response', async () => {
    await render({ terminalObservation: resource({state:'CONNECTED',positions:[],recent_trades:[]} as unknown as TerminalObservationResponse),
      observationHealth: resource({execution_supervisor: {state:'RUNNING', updated_at:'2026-09-20T12:01:00Z',
        stale:false, process_alive:true, execution_enabled:true, cycle_number:9, max_age_seconds:10}} as unknown as ObservationHealthResponse) });
    expect(panel('Weltrade terminal').textContent).toContain('RUNNING');
    await act(async () => vi.advanceTimersByTime(15000));
    expect(panel('Weltrade terminal').textContent).toContain('STALE');
    expect(panel('Weltrade terminal').textContent).not.toContain('RUNNING');
  });
  it('shows initial market and terminal requests as loading, then failures as unavailable', async () => {
    await render({ activeAnalysis: resource<ActiveMarketAnalysisResponse>(null, { loading: true }), terminalObservation: resource<TerminalObservationResponse>(null, { loading: true }) });
    expect(panel('Market chart').dataset.state).toBe('LOADING');
    expect(panel('Weltrade terminal').dataset.state).toBe('LOADING');
    expect(host.textContent).toContain('Fetching closed candles from Weltrade');
    expect(host.textContent).toContain('Checking Weltrade terminal');
    await render({ activeAnalysis: resource<ActiveMarketAnalysisResponse>(null, { error: 'network failure' }), terminalObservation: resource<TerminalObservationResponse>(null, { error: 'network failure' }) });
    expect(panel('Market chart').dataset.state).toBe('UNAVAILABLE');
    expect(panel('Weltrade terminal').dataset.state).toBe('UNAVAILABLE');
    expect(host.textContent).not.toContain('Checking Weltrade terminal');
  });
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-20T12:01:00Z'));
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it('keeps Workspace limited to decision and market views without source details', async () => {
    await act(async () => root.render(<WorkspacePage {...baseProps()} />));
    expect(host.querySelectorAll('.workspace-card')).toHaveLength(3);
    expect(panel('Weltrade terminal')).not.toBeNull();
    expect(panel('Decision trail')).not.toBeNull();
    expect(panel('Market chart')).not.toBeNull();
    expect(host.querySelector('.workspace-topbar-facts')).toBeNull();
    expect(host.querySelector('.workspace-operational-details')).toBeNull();
    expect(host.querySelector('.workspace-more-details')).toBeNull();
    expect(host.querySelector('.workspace-provenance')).toBeNull();
    expect(host.querySelector('.workspace-source-observation')).toBeNull();
    expect(host.textContent).not.toContain('Source details');
    expect(host.textContent).not.toContain('Source and observation details');
    expect(host.textContent).not.toContain('GET /');
  });
  it('hides owner-only source and operational disclosures from non-admin users', async () => {
    await render({ internalDetails: false });
    expect(host.querySelector('.workspace-provenance')).toBeNull();
    expect(host.querySelector('.workspace-operational-details')).toBeNull();
    expect(host.querySelector('.workspace-source-observation')).toBeNull();
    expect(host.querySelector('[aria-label="Readiness"]')).toBeNull();
    expect(host.textContent).not.toContain('Source details');
    expect(host.textContent).not.toContain('Connection and operational checks');
    expect(host.textContent).not.toContain('Source and observation details');
    expect(host.textContent).not.toContain('Separate broker context');
    expect(host.textContent).not.toContain('GET /');
    expect(panel('Decision trail').textContent).toContain('NO_SIGNAL');
    expect(panel('Weltrade terminal')).not.toBeNull();
    expect(panel('Market chart')).not.toBeNull();
    expect(host.querySelector('.workspace-topbar-facts')).not.toBeNull();
  });
  it('shows owner-only source and operational disclosures in Settings only', async () => {
    await render();
    expect(settings().querySelectorAll('.workspace-provenance').length).toBeGreaterThan(0);
    expect(settings().textContent).toContain('Source details');
    expect(settings().textContent).toContain('Source observation');
    expect(settings().textContent).toContain('Connection and operational checks');
    expect(settings().querySelector('.workspace-operational-details')).not.toBeNull();
    expect(settings().textContent).toContain('Source and observation details');
    expect(settings().textContent).toContain('Separate broker context');
    expect(settings().textContent).toContain('GET /brokers/status');
    expect(plain().querySelector('.workspace-provenance')).toBeNull();
    expect(plain().querySelector('.workspace-source-observation')).toBeNull();
    expect(plain().textContent).not.toContain('Source details');
    expect(plain().textContent).not.toContain('Source and observation details');
    expect(plain().textContent).not.toContain('GET /');
  });
  it('uses starting balance and separates realized P&L from the advisory target', async () => {
    await render({terminalObservation: resource({state:'CONNECTED', observed_at:observed, balance:150, positions:[],recent_trades:[],
      daily_accounting:{starting_balance:100,current_balance:150,realized_net_pnl:5,
        advisory_target_amount:20,currency:'USD',utc_date:'2026-09-20',net_funding:45,
        observed_at:observed,starting_balance_method:'RECONSTRUCTED_FROM_COMPLETE_BROKER_HISTORY',day_boundary:'00:00 UTC'}} as unknown as TerminalObservationResponse)});
    expect(host.textContent).toContain('20.00 USD');
    expect(host.textContent).toContain('100.00 USD');
    expect(host.textContent).toContain('5.00 USD');
  });
  it('does not invent a daily baseline from current balance when history is unavailable', async () => {
    await render({terminalObservation:resource({state:'CONNECTED',observed_at:observed,balance:150,positions:[],recent_trades:[]} as unknown as TerminalObservationResponse)});
    expect(host.textContent).toContain('Awaiting complete daily broker history');
    expect(host.textContent).not.toContain('30.00 USD');
  });
  it('docks research AI without trapping chart keyboard focus on desktop', async () => {
    await render({ assistantStatus: resource({state: 'READY', enabled: true, configured: true,
      healthy: true, model: 'test', context_mode: 'workspace', reason_codes: []} as AssistantStatusResponse) });
    expect(host.querySelector('.workspace-ai-dock [role="complementary"]')).not.toBeNull();
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    const prompt = Array.from(host.querySelectorAll('.workspace-ai-prompts button')).find(b => b.textContent?.includes('Explain the trend')) as HTMLButtonElement;
    await act(async () => prompt.click());
    expect((host.querySelector('[aria-label="Ask JQE AI"]') as HTMLTextAreaElement).value).toBe('Explain the trend');
    expect(host.textContent).not.toContain('Thinking…');
  });
  it('routes timeframe selection through the selected-market callback', async () => {
    const change = vi.fn();
    await render({ onMarketChange: change });
    const h1 = Array.from(host.querySelectorAll('.workspace-chart-controls button')).find(b => b.textContent === 'H1') as HTMLButtonElement;
    await act(async () => h1.click());
    expect(change).toHaveBeenCalledWith(baseProps().selectedSymbol, 'H1');
  });
  it('renders LOADING state', async () => {
    await render({ watchlist: resource<WatchlistResponse>(null, { loading: true }) });
    expect(panel('Watchlist').dataset.state).toBe('LOADING');
  });
  it('renders LIVE state', async () => {
    await render();
    expect(panel('Watchlist').dataset.state).toBe('LIVE');
  });
  it('shows uncertain candle freshness and disabled execution independently of a live demo connection', async () => {
    await render({
      broker: resource({ ...broker, active_broker: 'weltrade', active_broker_identity: {
        ...broker.active_broker_identity!, broker: 'weltrade', trade_mode: 'DEMO',
      }, live_connection_state: 'CONNECTED', broker_execution_enabled: false }),
      safety: resource({ observed_at: observed, observation_state: 'STALE',
        execution_authorization: 'UNKNOWN', emergency_stop_state: 'UNKNOWN',
        reason_codes: ['SNAPSHOT_STALE'] } as ExecutionSafetyResponse),
      activeAnalysis: resource({ context: { freshness_state: 'UNKNOWN',
        freshness_reason_codes: ['MARKET_CLOCK_AHEAD'], latest_closed_candle_at: observed },
        candles: { symbol: 'FX Vol 20', timeframe: 'M5', candles: [{ time: observed, open: 1, high: 2, low: 1, close: 2, volume: 1 }],
          market_data_status: 'CURRENT' } } as unknown as NonNullable<Props['activeAnalysis']>['data']),
    });
    const facts = host.querySelector('[aria-label="Broker and execution status"]') as HTMLElement;
    expect(facts.textContent).toContain('Market data freshnessunknown · MARKET_CLOCK_AHEAD');
    expect(facts.textContent).toContain('Broker executiondisabled');
    const details = host.querySelector('.workspace-operational-facts') as HTMLElement;
    expect(details.textContent).toContain('Research batch jobunknown · no live job telemetry');
    expect(details.textContent).toContain('Execution snapshotstale · fail closed');
    expect(panel('Market chart').textContent).toContain('Weltrade · unknown · MARKET_CLOCK_AHEAD');
    expect(panel('Market chart').textContent).not.toContain('freshness unknown');
    expect(settings().textContent).toContain('freshness unknown · MARKET_CLOCK_AHEAD');
    expect(host.querySelector('[data-testid="market-chart"]')?.getAttribute('data-status')).toBe('UNKNOWN');
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
    expect(host.textContent).toContain('Watchlist unavailable. See Notifications.');
    expect(host.textContent).not.toContain('request failed');
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
    const context = settings().querySelector('.workspace-context') as HTMLElement;
    expect(context.textContent).toContain('Separate broker context');
    expect(context.textContent).toContain('GET /brokers/status');
    expect(panel('Decision trail').querySelector('.workspace-context')).toBeNull();
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
    expect(host.querySelector('[aria-label="Weltrade supervisor heartbeat"]')?.getAttribute('data-state')).toBe(state);
  });
  it('rejects invalid timestamps', async () => {
    expect(validBroker({ ...broker, observed_at: 'invalid' })).toBe(false);
    expect(validAssessment({ ...assessment, candle_close_time: 'invalid' })).toBe(false);
  });
  it('derives broker freshness in readiness and expandable safety evidence from observation age', async () => {
    await render();
    expect(panel('Readiness').dataset.state).toBe('LIVE');
    expect(host.querySelector('.workspace-context')?.textContent).toContain('GET /brokers/status: LIVE');
    vi.setSystemTime(new Date(Date.parse(observed) + WORKSPACE_FRESHNESS_THRESHOLDS_MS.brokerStatus + 1));
    await render();
    expect(panel('Readiness').dataset.state).toBe('STALE');
    expect(host.querySelector('.workspace-context')?.textContent).toContain('GET /brokers/status: STALE');
    expect(host.querySelector('.workspace-context')?.textContent).not.toContain('GET /brokers/status: LIVE');
  });
  it('uses one human broker age in the top card and MT5 checklist detail', async () => {
    vi.setSystemTime(new Date('2026-09-27T12:00:00Z'));
    await render({ broker: resource({ ...broker, live_connection_state: 'CONNECTED', live_checked_at: observed }) });
    const facts = host.querySelector('.workspace-operational-facts') as HTMLElement;
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
  it('explains an unavailable live connection with neutral styling', async () => {
    await render({ broker: resource({ ...broker, live_connection_state: 'DISCONNECTED' }, { stale: true }) });
    expect(demoCard().textContent).toContain('unverified · live connection unavailable (status age 1m)');
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
    expect(facts.textContent).toContain('Live broker connectionunavailable');
    expect(facts.textContent).toContain('Demo verifiedYes');
    expect(facts.querySelectorAll(':scope > div')).toHaveLength(4);
  });
  it('renders the connected execution status when supplied', async () => {
    await render({ execution: resource({ connected: true, open_positions_count: 2 } as ExecutionStateResponse) });
    expect(host.querySelector('.workspace-operational-facts')?.textContent).toContain('Executionconnected · 2 open');
    expect(panel('Readiness').textContent).toContain('Execution statusConnected · 2 open positions');
  });
  it('does not offer broker switching in Workspace', async () => {
    await render();
    expect(host.textContent).toContain('Weltrade');
    expect(host.querySelector('select')).toBeNull();
  });
  it('keeps broker details in Settings without a separate broker destination', () => {
    const app = readFileSync('src/App.tsx', 'utf8');
    const sidebar = readFileSync('src/components/Sidebar.tsx', 'utf8');
    const settings = readFileSync('src/pages/SettingsPage.tsx', 'utf8');
    expect(app).not.toContain("case 'brokers'");
    expect(sidebar).not.toContain("id: 'brokers'");
    expect(settings).toContain('Weltrade connection');
    expect(settings).toContain('Demo verification');
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
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })));
    await act(async () => (Array.from(host.querySelectorAll('.workspace-palette nav button')).find(button => button.textContent === 'Markets') as HTMLButtonElement).click());
    expect(onNavigate).toHaveBeenCalledWith('markets');
  });
  it('opens palette with Control K and closes with Escape', async () => {
    await render();
    const trigger = host.querySelector('.workspace-ai-launcher') as HTMLButtonElement;
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
    const close = host.querySelector('.workspace-ai-close') as HTMLButtonElement;
    close.focus();
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    await act(async () => window.dispatchEvent(event));
    expect(event.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(host.querySelector('.workspace-ai-panel button'));
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
    expect(host.querySelector('.workspace-chart-overlay')?.textContent).toContain('see Notifications');
    expect(panel('Market chart').classList).toContain('workspace-chart-unavailable');
    expect(panel('Market chart').textContent).not.toContain('share one observation');
    expect(settings().textContent).toContain('strategy, setup, and candles share one observation.');
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
