// @vitest-environment happy-dom
import { act, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const allowed = [
  '/brokers/status', '/execution/safety', '/risk', '/monitoring/offline',
  '/observation/health', '/watchlist', '/watchlist/cap-usage', '/execution',
  '/market/active-analysis', '/assistant/status', '/notifications/status',
];
const legacyOnly = [
  '/system', '/market/summary', '/market/candles', '/signal',
  '/performance', '/execution/recovery', '/execution/paper-runtime',
  '/research/paper-diagnostics',
];
type Call = { path: string; method: string; signal?: AbortSignal };

vi.mock('./pages/OverviewPage', () => ({ OverviewPage: () => <div>Legacy overview</div> }));
vi.mock('./pages/MarketsPage', () => ({ MarketsPage: ({ candles }: { candles: unknown }) => <div>Legacy candles: {candles ? 'available' : 'unavailable'}</div> }));
vi.mock('./components/MarketChart', () => ({ MarketChart: () => <div>Rendered chart</div> }));
vi.mock('./components/Header', () => ({ Header: () => <header>Legacy header</header> }));

const bodyFor = (path: string): unknown => {
  if (path === '/monitoring/offline') return {
    schema_version: 1, mode: 'OFFLINE_SIMULATION', observed_at: '2026-09-20T12:00:00Z',
    broker_execution_enabled: false, backend: {}, assessment: null,
    strategy: { state: 'UNAVAILABLE' }, candle_freshness: { state: 'UNAVAILABLE' },
    simulation_submissions: { utc_count: 0, limit: 20, reset_at: '2026-09-21T00:00:00Z' },
  };
  if (path === '/market/candles') return { symbol: 'R_75', timeframe: 'H1', candles: [] };
  if (path === '/execution') return { open_positions_count: 3 };
  return {};
};

describe('App polling profiles', () => {
  let host: HTMLDivElement;
  let root: Root;
  let calls: Call[];
  let rejectedPaths: Set<string>;
  let pending: Map<string, { reject: (reason: Error) => void; resolve: (value: unknown) => void }>;

  const mount = async (strict = false) => {
    await act(async () => root.render(strict ? <StrictMode><App /></StrictMode> : <App />));
  };
  const nav = async (label: string) => {
    const button = host.querySelector(`.desktop-sidebar button[aria-label="${label}"]`) as HTMLButtonElement;
    expect(button).toBeTruthy();
    await act(async () => button.click());
  };
  const paths = () => calls.map(call => call.path);
  const banner = () => host.textContent?.match(/Telemetry errors: [^.]+\./)?.[0] ?? null;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-20T12:00:00Z'));
    calls = [];
    rejectedPaths = new Set();
    pending = new Map();
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation(() => ({
      matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    })));
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const path = new URL(url, 'http://localhost').pathname.replace('/api/v1', '');
      calls.push({ path, method: init?.method ?? 'GET', signal: init?.signal ?? undefined });
      if (rejectedPaths.has(path)) return Promise.reject(new Error(`failed ${path}`));
      if (path === '/system' && pending.size === 0) {
        return new Promise((resolve, reject) => pending.set(path, { resolve, reject }));
      }
      return Promise.resolve({ ok: true, json: async () => bodyFor(path) });
    }));
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('starts synchronously with the connected Workspace profile', async () => {
    await mount();
    expect(paths()).toEqual(allowed);
    expect(host.querySelector('[aria-label="Market chart"]')?.textContent).toContain('Active market analysis is unavailable.');
  });

  it('renders four sidebar groups with every existing destination', async () => {
    await mount();
    expect(Array.from(host.querySelectorAll('.desktop-sidebar .nav-section-label')).map(node => node.textContent)).toEqual(['Overview', 'Markets', 'Analysis', 'System']);
    expect(Array.from(host.querySelectorAll('.desktop-sidebar nav button')).map(node => node.textContent?.replace(/UNKNOWN|STALE|LOCK|OK|\d+/g, '').trim())).toEqual([
      'Workspace', 'Overview', 'Markets', 'Watchlist', 'Brokers', 'Positions', 'Trades',
      'Strategy', 'Risk Control', 'Performance', 'Research', 'System Logs', 'Settings',
    ]);
  });

  it.each(legacyOnly)('does not request excluded %s on Workspace mount', async path => {
    await mount();
    expect(paths()).not.toContain(path);
  });

  it('keeps two four-second ticks inside the connected endpoint allowlist with GET only', async () => {
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(paths()).toEqual([...allowed, ...allowed, ...allowed]);
    expect(calls.every(call => call.method === 'GET')).toBe(true);
  });

  it('aborts Workspace and starts the full legacy profile on navigation', async () => {
    await mount();
    const first = calls[0];
    await nav('Overview');
    expect(first.signal?.aborted).toBe(true);
    expect(paths().slice(allowed.length)).toEqual([
      '/system', '/market/summary', '/market/candles', '/signal', '/risk', '/execution',
      '/execution/safety', '/performance', '/execution/recovery', '/execution/paper-runtime',
      '/research/paper-diagnostics', '/monitoring/offline', '/observation/health',
      '/brokers/status', '/watchlist', '/watchlist/cap-usage',
    ]);
  });

  it('aborts legacy requests and never requests excluded URLs after returning to Workspace', async () => {
    await mount();
    await nav('Overview');
    const legacySystem = calls.find(call => call.path === '/system');
    const before = calls.length;
    await nav('Workspace');
    expect(legacySystem?.signal?.aborted).toBe(true);
    expect(paths().slice(before)).toEqual(allowed);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(before)).toEqual([...allowed, ...allowed]);
    expect(host.querySelector('[aria-label="Market chart"]')?.textContent).not.toContain('Rendered chart');
  });

  it('ignores late legacy failures and keeps their errors out of Workspace', async () => {
    await mount();
    await nav('Overview');
    await nav('Workspace');
    await act(async () => pending.get('/system')?.reject(new Error('late system failure')));
    expect(banner()).toBeNull();
  });

  it('hides retained system and execution errors on Workspace and restores them on a legacy tab', async () => {
    await mount();
    rejectedPaths.add('/system');
    rejectedPaths.add('/execution');
    await nav('Overview');
    // The system request is held by the transport fixture; reject it explicitly.
    await act(async () => pending.get('/system')?.reject(new Error('failed /system')));
    expect(banner()).toContain('system');
    expect(banner()).toContain('execution');
    await nav('Workspace');
    expect(banner()).toContain('execution');
    expect(host.querySelector('.telemetry-ribbon')).toBeNull();
    await nav('Overview');
    expect(banner()).toContain('system');
    expect(banner()).toContain('execution');
    expect(host.querySelector('.telemetry-ribbon')?.textContent).toContain('OFFLINE');
  });

  it('shows a Workspace-allowed resource failure', async () => {
    rejectedPaths.add('/watchlist');
    await mount();
    expect(banner()).toContain('watchlist');
  });

  it('keeps Positions navigation without a badge even after a retained legacy count', async () => {
    await mount();
    expect(host.querySelector('.desktop-sidebar button[aria-label="Positions"]')).toBeTruthy();
    await nav('Overview');
    await act(async () => pending.get('/system')?.resolve({ ok: true, json: async () => ({}) }));
    expect(host.querySelector('.desktop-sidebar button[aria-label="Positions, 3"] .nav-badge')?.textContent).toBe('3');
    await nav('Workspace');
    expect(host.querySelector('.desktop-sidebar button[aria-label="Positions"] .nav-badge')).toBeNull();
    expect(paths().slice(-allowed.length)).toEqual(allowed);
  });

  it('retains the legacy candle request and passes its response to the legacy Markets page', async () => {
    await mount();
    await nav('Markets');
    await act(async () => pending.get('/system')?.resolve({ ok: true, json: async () => ({}) }));
    expect(paths()).toContain('/market/candles');
    expect(host.textContent).toContain('Legacy candles: available');
  });

  it('treats AbortError as cancellation rather than a Workspace failure', async () => {
    await mount();
    rejectedPaths.add('/watchlist');
    await nav('Overview');
    await act(async () => pending.get('/system')?.reject(new DOMException('cancelled', 'AbortError')));
    await nav('Workspace');
    expect(banner()).not.toContain('system');
  });

  it('accounts for StrictMode by aborting its first request batch and making one replacement batch', async () => {
    await mount(true);
    expect(paths()).toEqual([...allowed, ...allowed]);
    expect(calls.slice(0, allowed.length).every(call => call.signal?.aborted)).toBe(true);
    expect(calls.slice(allowed.length).every(call => !call.signal?.aborted)).toBe(true);
  });
});
