import { useEffect, useRef, useState } from 'react';
import { EmptyStateIllustration } from '../EmptyStateIllustration';
import { MarketChart } from '../MarketChart';
import { adaptExperiment } from '../chart/experimentAdapter';
import { adaptReplay } from '../chart/researchAdapter';
import { isValidProfileRange, volumeProfileLabel } from '../chart/volumeProfilePrimitive';
import type {
  HistoricalAcquisitionJobDTO,
  ResearchExperimentDTO,
  ResearchMarketsDTO,
  ResearchReplayDTO,
  ResearchSessionDTO,
  VolumeProfileResultDTO,
} from '../../types/research';
import { acquisitionSelectionKey, isTerminalAcquisition, jobSelectionKey } from '../chart/acquisitionAdapter';
import { isCached } from '../chart/marketCatalogueAdapter';
import { ReplayControls } from './ReplayControls';
import {
  indicatorVisibility,
  type ResearchWorkspaceAction,
  type ResearchWorkspaceState,
  workspaceSelectionKey,
} from './researchWorkspace';

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Research request failed (${response.status})`);
  }
  return response.json();
}

const timeframeSeconds: Record<string, number> = {
  M1: 60,
  M5: 300,
  M15: 900,
  M30: 1800,
  H1: 3600,
  H4: 14400,
  D1: 86400,
};

function defaultHistoryRange(timeframe: string) {
  const step = timeframeSeconds[timeframe] ?? 900;
  const endSeconds = Math.floor(Date.now() / 1000 / step) * step;
  return {
    start: new Date((endSeconds - step * 299) * 1000).toISOString(),
    end: new Date(endSeconds * 1000).toISOString(),
  };
}

interface Props {
  state: ResearchWorkspaceState;
  markets: ResearchMarketsDTO;
  active: boolean;
  dispatch: (action: ResearchWorkspaceAction) => void;
  onActivate: () => void;
  onMarketsChanged: (markets: ResearchMarketsDTO) => void;
}

export function ResearchChartWorkspace({
  state,
  markets,
  active,
  dispatch,
  onActivate,
  onMarketsChanged,
}: Props) {
  const { instrument, timeframe, workspaceId } = state;
  const [session, setSession] = useState<ResearchSessionDTO | null>(null);
  const [view, setView] = useState<ReturnType<typeof adaptReplay> | null>(null);
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialRange = defaultHistoryRange(timeframe);
  const [historyStart, setHistoryStart] = useState(initialRange.start);
  const [historyEnd, setHistoryEnd] = useState(initialRange.end);
  const [acquisition, setAcquisition] = useState<HistoricalAcquisitionJobDTO | null>(null);
  const [rangeStart, setRangeStart] = useState(0);
  const [rangeEnd, setRangeEnd] = useState(0);
  const [binSize, setBinSize] = useState('1');
  const [profile, setProfile] = useState<VolumeProfileResultDTO | null>(null);
  const [experiment, setExperiment] = useState<ResearchExperimentDTO | null>(null);
  const [hypothesis, setHypothesis] = useState('POC_PROXIMITY_FILTER_V1');
  const [lookback, setLookback] = useState(50);
  const [thresholds, setThresholds] = useState('0.25,0.50,1.00');
  const generation = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const selectionKey = workspaceSelectionKey(state);
  const selectedCache = markets.cached_datasets.find(
    (item) =>
      item.provider === instrument.provider &&
      item.canonical_symbol === instrument.canonical_symbol &&
      item.timeframe === timeframe
  );

  useEffect(() => {
    generation.current += 1;
    requestController.current?.abort();
    setPlaying(false);
    setSession(null);
    setView(null);
    setCursor(0);
    setError(null);
    setAcquisition(null);
    setRangeStart(0);
    setRangeEnd(0);
    setProfile(null);
    setExperiment(null);
    const range = defaultHistoryRange(timeframe);
    setHistoryStart(range.start);
    setHistoryEnd(range.end);
  }, [selectionKey]);

  useEffect(() => () => {
    generation.current += 1;
    requestController.current?.abort();
  }, []);

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    setView(null);
    read<ResearchReplayDTO>(`/api/v1/research/backtests/${session.id}/replay?cursor=${cursor}`, {
      signal: controller.signal,
    })
      .then((dto) => {
        if (!controller.signal.aborted) {
          setView(adaptReplay(dto));
          setError(null);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(String(reason));
          setPlaying(false);
        }
      });
    return () => controller.abort();
  }, [session, cursor]);

  useEffect(() => {
    if (!playing || !session || !view) return;
    if (cursor >= session.dataset.candle_count - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setCursor((value) => value + 1), 1000 / speed);
    return () => window.clearTimeout(timer);
  }, [playing, session, view, cursor, speed]);

  useEffect(() => {
    if (!acquisition || isTerminalAcquisition(acquisition)) return;
    let cancelled = false;
    const selectionAtStart = jobSelectionKey(acquisition);
    const poll = window.setInterval(async () => {
      try {
        const next = await read<HistoricalAcquisitionJobDTO>(
          `/api/v1/research/history/acquisitions/${acquisition.job_id}`
        );
        const current = acquisitionSelectionKey(
          instrument.provider,
          instrument.provider_symbol,
          instrument.canonical_symbol,
          timeframe
        );
        if (cancelled || current !== selectionAtStart) return;
        setAcquisition(next);
        if (isTerminalAcquisition(next)) {
          window.clearInterval(poll);
          if (next.state === 'COMPLETED') onMarketsChanged(await read('/api/v1/research/markets'));
        }
      } catch (reason) {
        if (!cancelled) setError(String(reason));
        window.clearInterval(poll);
      }
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [acquisition?.job_id, acquisition?.state, selectionKey]);

  async function start() {
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const request = ++generation.current;
    setBusy(true);
    setPlaying(false);
    setSession(null);
    setView(null);
    setError(null);
    try {
      const result = await read<ResearchSessionDTO>('/api/v1/research/backtests', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: instrument.provider,
          symbol: instrument.canonical_symbol,
          timeframe,
          count: 300,
          initial_capital: 1000,
        }),
        signal: controller.signal,
      });
      if (request === generation.current) {
        setCursor(0);
        setProfile(null);
        setExperiment(null);
        setSession(result);
      }
    } catch (reason) {
      if (request === generation.current) setError(String(reason));
    } finally {
      if (request === generation.current) setBusy(false);
    }
  }

  async function acquire() {
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const request = ++generation.current;
    setError(null);
    setSession(null);
    setView(null);
    setProfile(null);
    setExperiment(null);
    setAcquisition(null);
    try {
      const result = await read<HistoricalAcquisitionJobDTO>('/api/v1/research/history/acquisitions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_symbol: instrument.provider_symbol,
          timeframe,
          requested_start: historyStart,
          requested_end: historyEnd,
        }),
        signal: controller.signal,
      });
      if (request === generation.current) {
        setAcquisition(result);
        if (result.state === 'COMPLETED') onMarketsChanged(await read('/api/v1/research/markets'));
      }
    } catch (reason) {
      if (request === generation.current) setError(String(reason));
    }
  }

  async function calculateProfile() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      setProfile(
        await read(`/api/v1/research/backtests/${session.id}/volume-profile`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            range_start_index: rangeStart,
            range_end_index: rangeEnd,
            bin_size: binSize,
            value_area_fraction: '0.70',
            cursor,
          }),
        })
      );
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function runExperiment() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      setExperiment(
        await read(`/api/v1/research/backtests/${session.id}/experiments`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            hypothesis_id: hypothesis,
            profile_lookback: lookback,
            bin_size: binSize,
            threshold_candidates: thresholds.split(',').map((value) => value.trim()),
            train_fraction: '0.60',
            validation_fraction: '0.20',
            minimum_trade_count: 30,
          }),
        })
      );
    } catch (reason) {
      setError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  const indicators = indicatorVisibility(state);

  return (
    <section
      className={`research-chart-workspace ${active ? 'active' : ''}`}
      aria-label={`${workspaceId} research workspace`}
      onFocusCapture={onActivate}
      onClick={onActivate}
    >
      <header className="research-workspace-context">
        <div>
          <span className="research-workspace-label">{workspaceId} workspace</span>
          <strong>
            {instrument.display_name}
          </strong>
          <span className="font-mono">
            {instrument.canonical_symbol} · {timeframe}
          </span>
        </div>
        <div>
          <span className={`badge ${selectedCache ? 'badge-green' : 'badge-neutral'}`}>
            {selectedCache ? 'CACHED' : 'NOT CACHED'}
          </span>
          <span>{selectedCache?.candle_count ?? 0} candles</span>
          <span>Volume {selectedCache?.volume_type ?? '—'}</span>
          {session && (
            <span>
              Replay {cursor + 1}/{session.dataset.candle_count}
            </span>
          )}
        </div>
      </header>

      <div className="research-workspace-actions">
        <button
          disabled={
            busy ||
            !isCached(markets, instrument, timeframe) ||
            (!!acquisition && !isTerminalAcquisition(acquisition))
          }
          onClick={start}
          className="btn-quant btn-quant-primary"
        >
          {busy ? 'Computing…' : 'Run cached backtest'}
        </button>
        <span className={`research-active-state ${active ? 'active' : ''}`}>
          {active ? '● Active workspace' : 'Click or focus to activate'}
        </span>
      </div>

      <details className="quant-panel research-secondary-panel" open={!!acquisition}>
        <summary>
          Historical acquisition{' '}
          <span>{acquisition?.state ?? (selectedCache ? 'CACHE READY' : 'NOT CACHED')}</span>
        </summary>
        <div className="quant-panel-body" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <p className="research-acquisition-target">
            <strong>Manual public-data request</strong> · {instrument.display_name} ·{' '}
            {instrument.provider_symbol} · {timeframe}
            <br />
            Range: {historyStart} → {historyEnd}
          </p>
          <div className="research-inline-controls">
            <label>
              UTC start: <input value={historyStart} onChange={(event) => setHistoryStart(event.target.value)} />
            </label>
            <label>
              UTC end: <input value={historyEnd} onChange={(event) => setHistoryEnd(event.target.value)} />
            </label>
            <button
              className="research-acquisition-action"
              disabled={
                instrument.is_trading_suspended ||
                (!!acquisition && !isTerminalAcquisition(acquisition))
              }
              onClick={acquire}
            >
              {acquisition && !isTerminalAcquisition(acquisition)
                ? 'Acquisition running…'
                : acquisition?.state === 'FAILED'
                ? 'Retry Historical Data Acquisition'
                : 'Acquire Historical Data'}
            </button>
          </div>
        </div>
        {acquisition && (
          <div
            className="quant-panel-body font-mono"
            style={{ fontSize: '10.5px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-app)' }}
            role="status"
          >
            <strong style={{ color: acquisition.state === 'COMPLETED' ? 'var(--quant-green)' : 'var(--quant-amber)' }}>
              {acquisition.state}
            </strong>{' '}
            · {acquisition.spec.provider_symbol} → {acquisition.spec.canonical_symbol} ·{' '}
            {acquisition.spec.timeframe}
            {acquisition.outcome && (
              <>
                {' '}
                · Stored {acquisition.outcome.stored_after} · Gaps {acquisition.outcome.gap_count} ·{' '}
                Coverage {acquisition.outcome.coverage_complete ? 'complete' : 'incomplete'}
              </>
            )}
            {acquisition.error_message && <> · {acquisition.error_message}</>}
          </div>
        )}
      </details>

      {error && (
        <p role="alert" style={{ color: 'var(--quant-red)', fontFamily: 'var(--font-mono)', fontSize: '11px', padding: '6px 8px', background: 'var(--quant-red-subtle)', borderRadius: 'var(--radius-xs)', border: '1px solid var(--quant-red-border)' }}>
          {error}. Check that sufficient historical candles are cached.
        </p>
      )}

      {!session && !error && (
        <div className="research-empty-state" aria-label="Research chart preview">
          <EmptyStateIllustration />
          <div className="research-empty-content">
            <span className="research-empty-kicker">{instrument.canonical_symbol} · {timeframe}</span>
            <h2>Chart workspace ready</h2>
            <p>
              {selectedCache
                ? `${selectedCache.candle_count} cached candles are available. Run the research-only backtest to open the chart and replay controls.`
                : 'This dataset is not cached yet. Use Historical acquisition above to request public market data.'}
            </p>
          </div>
        </div>
      )}

      {session && (
        <>
          <p className="research-dataset-line font-mono" style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
            Dataset {session.dataset.content_hash} · {session.dataset.candle_count} candles · Volume{' '}
            {session.volume_metadata.type} / {session.volume_metadata.source} · Strategy{' '}
            {String(session.strategy.entrypoint ?? 'backend configuration')}
          </p>

          <div className="research-indicator-toolbar" aria-label={`${workspaceId} chart display controls`}>
            <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>OVERLAYS & PANES:</span>
            <button
              className={state.overlays.ema50 ? 'active' : ''}
              onClick={() => dispatch({ type: 'toggle-overlay', overlay: 'ema50' })}
            >
              EMA50
            </button>
            <button
              className={state.overlays.ema200 ? 'active' : ''}
              onClick={() => dispatch({ type: 'toggle-overlay', overlay: 'ema200' })}
            >
              EMA200
            </button>
            <button
              className={state.panes.rsi ? 'active' : ''}
              onClick={() => dispatch({ type: 'toggle-pane', pane: 'rsi' })}
            >
              RSI PANE
            </button>
            <button
              className={state.panes.volume ? 'active' : ''}
              onClick={() => dispatch({ type: 'toggle-pane', pane: 'volume' })}
            >
              VOLUME PANE
            </button>
          </div>

          <MarketChart
            symbol={session.dataset.symbol}
            timeframe={session.dataset.timeframe}
            candles={view?.candles ?? []}
            markers={view?.markers}
            volumeProfile={profile?.snapshot ?? null}
            indicators={indicators}
            height={440}
            loading={!view && !error}
            error={error}
          />

          <ReplayControls
            cursor={cursor}
            total={session.dataset.candle_count}
            playing={playing}
            speed={speed}
            setCursor={setCursor}
            setPlaying={setPlaying}
            setSpeed={setSpeed}
          />

          <details className="quant-panel research-secondary-panel">
            <summary>
              Fixed Range Volume Profile <span>{profile?.eligibility ?? 'RESEARCH ONLY'}</span>
            </summary>
            <div className="quant-panel-body research-inline-controls">
              <label>
                Start index{' '}
                <input
                  type="number"
                  min={0}
                  max={cursor}
                  value={rangeStart}
                  onChange={(event) => setRangeStart(Number(event.target.value))}
                />
              </label>
              <label>
                End index{' '}
                <input
                  type="number"
                  min={rangeStart}
                  max={cursor}
                  value={rangeEnd}
                  onChange={(event) => setRangeEnd(Number(event.target.value))}
                />
              </label>
              <label>
                Bin size{' '}
                <input value={binSize} onChange={(event) => setBinSize(event.target.value)} />
              </label>
              <button
                disabled={busy || !isValidProfileRange(rangeStart, rangeEnd, cursor)}
                onClick={calculateProfile}
              >
                Calculate profile
              </button>
            </div>
            {profile && (
              <div className="quant-panel-body font-mono" style={{ fontSize: '10.5px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-app)' }} role="status">
                {profile.snapshot
                  ? `${volumeProfileLabel(profile.snapshot.volume_type)} · POC ${profile.snapshot.point_of_control} · VAH ${profile.snapshot.value_area_high} · VAL ${profile.snapshot.value_area_low}`
                  : `Unavailable · ${profile.eligibility} · ${profile.reason}`}
              </div>
            )}
          </details>

          <details className="quant-panel research-secondary-panel">
            <summary>
              FRVP experiments <span>{experiment?.status ?? 'OFFLINE'}</span>
            </summary>
            <div className="quant-panel-body research-inline-controls">
              <label>
                Hypothesis{' '}
                <select value={hypothesis} onChange={(event) => setHypothesis(event.target.value)}>
                  <option>POC_PROXIMITY_FILTER_V1</option>
                  <option>VALUE_AREA_LOCATION_V1</option>
                </select>
              </label>
              <label>
                Lookback{' '}
                <input
                  type="number"
                  min={2}
                  max={200}
                  value={lookback}
                  onChange={(event) => setLookback(Number(event.target.value))}
                />
              </label>
              <label>
                ATR thresholds{' '}
                <input value={thresholds} onChange={(event) => setThresholds(event.target.value)} />
              </label>
              <button disabled={busy || lookback < 2 || lookback > 200} onClick={runExperiment}>
                Run experiment
              </button>
            </div>
            {experiment && (
              <div className="quant-panel-body font-mono" style={{ fontSize: '10.5px', borderTop: '1px solid var(--border-subtle)', background: 'var(--bg-app)' }} role="status">
                <strong style={{ color: experiment.status === 'COMPLETED' ? 'var(--quant-green)' : 'var(--quant-cyan)' }}>
                  {experiment.status}
                </strong>{' '}
                · {experiment.reason} ·{' '}
                {adaptExperiment(experiment)
                  .map((row) => `${row.partition}: ${row.variantTrades} trades`)
                  .join(' · ')}
              </div>
            )}
          </details>

          {view && (
            <div className="quant-panel">
              <div className="quant-panel-header">
                <div className="quant-panel-title">Current candle telemetry & regime</div>
              </div>
              <div className="quant-panel-body font-mono" style={{ fontSize: '11px', lineHeight: 1.6 }}>
                EMA50 {view.currentIndicators?.ema50?.toFixed(4) ?? '—'} · EMA200{' '}
                {view.currentIndicators?.ema200?.toFixed(4) ?? '—'} · RSI{' '}
                {view.currentIndicators?.rsi?.toFixed(2) ?? '—'} · ATR{' '}
                {view.currentIndicators?.atr?.toFixed(4) ?? '—'} · Regime{' '}
                <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>
                  {view.currentIndicators?.regime ?? 'warmup'}
                </span>
                <br />
                {view.currentDecision ? (
                  <span>
                    <strong
                      style={{
                        color:
                          view.currentDecision.signal === 'BUY'
                            ? 'var(--quant-green)'
                            : view.currentDecision.signal === 'SELL'
                            ? 'var(--quant-red)'
                            : 'var(--text-secondary)',
                      }}
                    >
                      {view.currentDecision.signal}
                    </strong>{' '}
                    · Confidence {view.currentDecision.confidence}% ·{' '}
                    {view.currentDecision.reasons.join('; ')}
                  </span>
                ) : (
                  <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    Indicator warmup — no strategy decision at this candle
                  </span>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
