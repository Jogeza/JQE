// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
import { createResearchWorkspace, updateResearchWorkspace, type ResearchWorkspaceState } from './researchWorkspace';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../MarketChart', () => ({ MarketChart: ({ symbol }: { symbol: string }) => <div data-testid="chart">{symbol}</div> }));
import { ResearchChartWorkspace } from './ResearchChartWorkspace';

const instrument = (provider_symbol = 'frxXAUUSD', timeframe = ['M15', 'H1']) => ({ provider: 'deriv', provider_symbol,
  canonical_symbol: provider_symbol.replace('frx', ''), display_name: provider_symbol, market: 'forex', subgroup: '', submarket: '',
  instrument_type: 'forex', pip_size: 5, exchange_is_open: true, is_trading_suspended: false,
  historical_data_supported: 'UNKNOWN', timeframes: timeframe } as MarketInstrumentDTO);
const gold = instrument();
const markets = { catalogue: { provider: 'deriv', instruments: [gold, instrument('frxEURUSD')], source_status: 'AVAILABLE', cache_status: 'HIT' },
  cached_datasets: [{ provider: 'deriv', canonical_symbol: 'XAUUSD', provider_symbol: 'frxXAUUSD', timeframe: 'M15', start: '', end: '',
    candle_count: 288, dataset_identity: 'hash', volume_type: 'UNAVAILABLE', volume_source: 'Deriv', gap_count: 0 }] } as ResearchMarketsDTO;
const session = { id: 'session-1', dataset: { provider: 'deriv', symbol: 'XAUUSD', timeframe: 'M15', start: '', end: '', candle_count: 288, content_hash: 'hash' },
  strategy: { entrypoint: 'strategy.pipeline.generate_trading_signal' }, volume_metadata: { available: false, type: 'UNAVAILABLE', source: 'Deriv' } };
const replay = { id: 'session-1', cursor: 0, complete: false, candles: [], signals: [], trades: [], balance_curve: [] };
const jsonResponse = (value: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(value) } as Response);

describe('ResearchChartWorkspace request and cleanup boundary', () => {
  let host: HTMLDivElement; let root: Root; let state: ResearchWorkspaceState;
  const dispatch = vi.fn(); const onMarketsChanged = vi.fn();
  const render = async (next = state) => act(async () => { root.render(<ResearchChartWorkspace state={next} markets={markets} active
    dispatch={dispatch} onActivate={() => undefined} onMarketsChanged={onMarketsChanged} />); });
  beforeEach(() => { host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    state = createResearchWorkspace('primary', gold, 'M15'); dispatch.mockReset(); onMarketsChanged.mockReset(); vi.restoreAllMocks(); });
  afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); });

  it('does not fetch on mount, disclosure expansion, selection changes, or presentation changes', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse({}));
    await render(); expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => (host.querySelector('summary') as HTMLElement).click()); expect(fetchMock).not.toHaveBeenCalled();
    await render(updateResearchWorkspace(state, { type: 'toggle-overlay', overlay: 'ema50' })); expect(fetchMock).not.toHaveBeenCalled();
    await render(updateResearchWorkspace(state, { type: 'toggle-pane', pane: 'rsi' })); expect(fetchMock).not.toHaveBeenCalled();
    await render(updateResearchWorkspace(state, { type: 'select-timeframe', timeframe: 'H1' })); expect(fetchMock).not.toHaveBeenCalled();
  });

  it('uses one session request, one initial replay request, and one request per replay step', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => String(input).includes('/replay') ? jsonResponse(replay) : jsonResponse(session));
    await render(); const run = [...host.querySelectorAll('button')].find(button => button.textContent === 'Run cached backtest')!;
    await act(async () => { run.click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock.mock.calls.map(call => String(call[0]))).toEqual(['/api/v1/research/backtests', '/api/v1/research/backtests/session-1/replay?cursor=0']);
    const next = host.querySelector('button[aria-label="Next candle"]') as HTMLButtonElement;
    await act(async () => { next.click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledTimes(3); expect(String(fetchMock.mock.calls[2][0])).toContain('cursor=1');
  });

  it('keeps acquisition collapsed and sends exactly one deliberate scoped request while blocking repeats', async () => {
    vi.useFakeTimers();
    const job = { job_id: 'job-1', request_identity: 'r', state: 'RUNNING', created_at: '', spec: { provider: 'deriv', canonical_symbol: 'XAUUSD',
      provider_symbol: 'frxXAUUSD', timeframe: 'M15', requested_start: '', requested_end: '', requested_max_candles: 300 } };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => jsonResponse(job));
    await render(); const details = host.querySelector('details')!; expect(details.open).toBe(false); expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => (details.querySelector('summary') as HTMLElement).click()); expect(fetchMock).not.toHaveBeenCalled();
    const acquire = [...details.querySelectorAll('button')].find(button => button.textContent === 'Acquire Historical Data')!;
    await act(async () => { acquire.click(); await Promise.resolve(); await Promise.resolve(); });
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(String(fetchMock.mock.calls[0][0])).toBe('/api/v1/research/history/acquisitions');
    const running = [...details.querySelectorAll('button')].find(button => button.textContent === 'Acquisition running…') as HTMLButtonElement;
    expect(running.disabled).toBe(true); running.click(); expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(1);
    await act(async () => root.unmount()); expect(vi.getTimerCount()).toBe(0); root = createRoot(host);
  });

  it('aborts an in-flight explicit request when the workspace unmounts', async () => {
    const signals: AbortSignal[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation((_input, init) => {
      if (init?.signal instanceof AbortSignal) signals.push(init.signal);
      return new Promise<Response>(() => undefined);
    });
    await render(); const run = [...host.querySelectorAll('button')].find(button => button.textContent === 'Run cached backtest')!;
    await act(async () => run.click()); expect(signals[0]?.aborted).toBe(false);
    await act(async () => root.unmount()); expect(signals[0]?.aborted).toBe(true); root = createRoot(host);
  });
});
