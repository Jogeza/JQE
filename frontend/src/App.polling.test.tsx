// @vitest-environment happy-dom
import { act, StrictMode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const allowed = [
  '/market/active-analysis', '/brokers/terminal-observation', '/observation/health', '/risk',
  '/brokers/status', '/execution/safety', '/monitoring/offline', '/watchlist',
  '/watchlist/cap-usage', '/execution', '/assistant/status', '/notifications/status',
];
const legacyOnly = [
  '/system', '/market/summary', '/market/candles', '/signal',
  '/performance', '/execution/recovery', '/execution/paper-runtime',
  '/research/paper-diagnostics',
];
type Call = { path: string; method: string; signal?: AbortSignal };

vi.mock('./pages/OverviewPage', () => ({ OverviewPage: () => <div>Legacy overview</div> }));
vi.mock('./pages/MarketsPage', () => ({ MarketsPage: ({ candles }: { candles: unknown }) => <div>Legacy candles: {candles ? 'available' : 'unavailable'}</div> }));
vi.mock('./components/MarketChart', () => ({
  MarketChart: ({ symbolControls, candles, emptyMessage }: { symbolControls?: React.ReactNode; candles?: unknown[]; emptyMessage?: React.ReactNode }) =>
    <div>Rendered chart{symbolControls}{(candles?.length ?? 0) === 0 ? <>{emptyMessage ?? null}</> : null}</div>,
}));
vi.mock('./components/Header', () => ({ Header: () => <header>Legacy header</header> }));

const bodyFor = (path: string): unknown => {
  if (path === '/brokers/status') return {
    active_broker: 'weltrade', observation_state: 'LIVE', broker_execution_enabled: false,
  };
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
  const banner = async () => {
    const trigger = host.querySelector('.notification-trigger') as HTMLButtonElement;
    if (trigger.getAttribute('aria-expanded') !== 'true') await act(async () => trigger.click());
    return host.querySelector('.notification-panel')?.textContent?.match(/Telemetry errors: [^.]+\./)?.[0] ?? null;
  };

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
    expect(host.querySelector('[aria-label="Market chart"]')?.textContent).toContain('Rendered chart');
    expect(host.querySelector('[role="status"]')?.textContent).toContain('Observation API · orders disabled');
    expect(host.querySelector('[role="status"]')?.textContent).not.toContain('OFFLINE SIMULATION');
  });

  it('updates timeframe and terminal evidence while unrelated monitoring is pending', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      urls.push(url);
      const path = new URL(url, 'http://localhost').pathname.replace('/api/v1', '');
      if (path === '/notifications/status') return new Promise(() => {});
      const body = path === '/brokers/terminal-observation'
        ? { state: 'CONNECTED', environment: 'demo', positions: [], recent_trades: [], execution_enabled: false }
        : bodyFor(path);
      return Promise.resolve({ ok: true, json: async () => body });
    }));
    await mount();
    expect(host.querySelector('[aria-label="Weltrade terminal"]')?.textContent).toContain('Guarded demo supervisor');
    const button = Array.from(host.querySelectorAll('.chart-symbol-controls button')).find(button => button.textContent === 'M1') as HTMLButtonElement;
    const beforeSwitch = urls.length;
    await act(async () => button.click());
    expect(urls.slice(beforeSwitch).map(url => new URL(url, 'http://localhost').pathname.replace('/api/v1', ''))).toEqual(['/market/active-analysis', '/brokers/terminal-observation', '/risk']);
    expect(button.getAttribute('aria-pressed')).toBe('true');
    expect(urls.some(url => url.includes('/market/active-analysis') && url.includes('timeframe=M1'))).toBe(true);
    expect(host.querySelector('[aria-label="Weltrade terminal"]')?.textContent).toContain('Guarded demo supervisor');
  });

  it('renders four sidebar groups with every existing destination', async () => {
    await mount();
    expect(Array.from(host.querySelectorAll('.desktop-sidebar .nav-section-label')).map(node => node.textContent)).toEqual(['Overview', 'Markets', 'Analysis', 'System']);
    expect(Array.from(host.querySelectorAll('.desktop-sidebar nav button')).map(node => node.textContent?.replace(/UNKNOWN|STALE|LOCK|OK|\d+/g, '').trim())).toEqual([
      'Workspace', 'Overview', 'Markets', 'SyntX Markets', 'Watchlist', 'Positions', 'Journal',
      'Strategy', 'Risk Control', 'Performance', 'Research', 'System Logs', 'Settings',
    ]);
  });

  it('switches the whole site theme and preserves the choice', async () => {
    window.localStorage.removeItem('jqe-site-theme');
    await mount();
    const app = host.querySelector('.app-container') as HTMLElement;
    expect(app.dataset.theme).toBe('light');
    const toggle = host.querySelector('.desktop-sidebar .site-theme-toggle') as HTMLButtonElement;
    await act(async () => toggle.click());
    expect(app.dataset.theme).toBe('dark');
    expect(window.localStorage.getItem('jqe-site-theme')).toBe('dark');
  });

  it.each(legacyOnly)('does not request excluded %s on Workspace mount', async path => {
    await mount();
    expect(paths()).not.toContain(path);
  });

  it('avoids full workspace batches on four-second ticks and staggers due resources', async () => {
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(paths()).toEqual(allowed);
    await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
    expect(paths().slice(allowed.length)).toEqual(['/market/active-analysis', '/observation/health']);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(allowed.length)).toEqual([
      '/market/active-analysis', '/observation/health', '/risk', '/execution/safety',
    ]);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(allowed.length)).toEqual([
      '/market/active-analysis', '/observation/health', '/risk', '/execution/safety',
      '/brokers/terminal-observation', '/execution',
    ]);
    expect(calls.every(call => call.method === 'GET')).toBe(true);
  });

  it('staggers legacy profile ticks instead of refiring the whole cohort', async () => {
    await mount();
    await nav('Overview');
    await act(async () => pending.get('/system')?.resolve({ ok: true, json: async () => ({}) }));
    const before = calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(paths().slice(before)).toEqual([]);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(before)).toEqual(['/observation/health']);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(before)).toEqual(['/observation/health', '/risk', '/execution/safety']);
  });

  it('pauses automatic polling in hidden tabs and resumes due work when visible', async () => {
    await mount();
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await act(async () => { await vi.advanceTimersByTimeAsync(64000); });
    expect(paths()).toEqual(allowed);
    visibility.mockReturnValue('visible');
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(allowed.length)).toEqual([
      '/market/active-analysis', '/brokers/terminal-observation', '/observation/health',
      '/risk', '/brokers/status', '/execution/safety', '/monitoring/offline', '/watchlist', '/execution',
    ]);
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().slice(allowed.length + 9)).toEqual(['/watchlist/cap-usage']);
    visibility.mockRestore();
  });

  it('backs off failed observations while allowing an immediate manual refresh', async () => {
    rejectedPaths.add('/market/active-analysis');
    await mount();
    await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
    expect(paths().filter(path => path === '/market/active-analysis')).toHaveLength(1);
    const refresh = host.querySelector('button[aria-label="Retry data refresh"]') as HTMLButtonElement;
    await act(async () => refresh.click());
    expect(paths().filter(path => path === '/market/active-analysis')).toHaveLength(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(56000); });
    expect(paths().filter(path => path === '/market/active-analysis')).toHaveLength(2);
    rejectedPaths.clear();
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    expect(paths().filter(path => path === '/market/active-analysis')).toHaveLength(3);
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
      '/brokers/status', '/watchlist', '/watchlist/cap-usage', '/notifications/status', '/assistant/status',
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
    expect(paths().slice(before)).toEqual(allowed);
    expect(host.querySelector('[aria-label="Market chart"]')?.textContent).toContain('No market snapshot. See Notifications.');
  });

  it('ignores late legacy failures and keeps their errors out of Workspace', async () => {
    await mount();
    await nav('Overview');
    await nav('Workspace');
    await act(async () => pending.get('/system')?.reject(new Error('late system failure')));
    expect(await banner()).toBeNull();
  });

  it('hides retained system and execution errors on Workspace and restores them on a legacy tab', async () => {
    await mount();
    rejectedPaths.add('/system');
    rejectedPaths.add('/execution');
    await nav('Overview');
    // The system request is held by the transport fixture; reject it explicitly.
    await act(async () => pending.get('/system')?.reject(new Error('failed /system')));
    expect(await banner()).toContain('system');
    expect(await banner()).toContain('execution');
    await nav('Workspace');
    expect(await banner()).toContain('execution');
    expect(host.querySelector('.telemetry-ribbon')).toBeNull();
    await nav('Overview');
    expect(await banner()).toContain('system');
    expect(await banner()).toContain('execution');
    expect(host.querySelector('.telemetry-ribbon')?.textContent).toContain('OFFLINE');
  });

  it('shows a Workspace-allowed resource failure', async () => {
    rejectedPaths.add('/watchlist');
    await mount();
    expect(await banner()).toContain('watchlist');
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
    expect(await banner()).not.toContain('system');
  });

  it('accounts for StrictMode by aborting its first request batch and making one replacement batch', async () => {
    await mount(true);
    expect(paths()).toEqual([...allowed.slice(0, 3), ...allowed]);
    expect(calls.slice(0, 3).every(call => call.signal?.aborted)).toBe(true);
    expect(calls.slice(3).every(call => !call.signal?.aborted)).toBe(true);
  });
});
