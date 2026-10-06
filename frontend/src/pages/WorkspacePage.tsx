import React, { useEffect, useRef, useState } from 'react';
import { Activity, Moon, Paperclip, SendHorizontal, Sun, X } from 'lucide-react';
import { jqeApi } from '../services/api';
import { MarketChart } from '../components/MarketChart';
import type { TabType } from '../components/Sidebar';
import type {
  BrokerStatusResponse, ExecutionSafetyResponse, ObservationHealthResponse,
  OfflineMonitoringResponse, ResourceState, RiskStatusResponse, WatchlistCapUsageResponse,
  WatchlistResponse, ExecutionStateResponse, ActiveMarketAnalysisResponse,
  AssistantStatusResponse, NotificationStatusResponse, LiveExecutionResponse,
  TerminalObservationResponse,
} from '../types/api';
import type { TelemetryLifecycle } from '../services/telemetryLifecycle';
import { formatAge, formatTime, observationState, panelState, reasonText, validAssessment, validBroker, validCaps, validHealth, validRisk, validSafety, validWatchlist, withinAge, WORKSPACE_FRESHNESS_THRESHOLDS_MS, type PanelState } from './workspaceEvidence';
import './WorkspacePage.css';
import { prepareAssistantImage, type AssistantImage } from '../services/assistantImage';

interface Props {
  hosted?: boolean;
  configurationOnly?: boolean;
  internalDetails?: boolean;
  broker: ResourceState<BrokerStatusResponse>;
  safety: ResourceState<ExecutionSafetyResponse>;
  risk: ResourceState<RiskStatusResponse>;
  monitoring: ResourceState<OfflineMonitoringResponse>;
  observationHealth: ResourceState<ObservationHealthResponse>;
  watchlist: ResourceState<WatchlistResponse>;
  caps: ResourceState<WatchlistCapUsageResponse>;
  execution?: ResourceState<ExecutionStateResponse>;
  terminalObservation?: ResourceState<TerminalObservationResponse>;
  activeAnalysis?: ResourceState<ActiveMarketAnalysisResponse>;
  assistantStatus?: ResourceState<AssistantStatusResponse>;
  notificationStatus?: ResourceState<NotificationStatusResponse>;
  liveExecution?: { loading: boolean; result: LiveExecutionResponse | null; error: string | null };
  onExecuteLiveCycle?: () => void;
  selectedSymbol: string;
  selectedTimeframe: string;
  onMarketChange?: (symbol: string, timeframe: string) => void;
  lifecycle: TelemetryLifecycle;
  onNavigate: (tab: TabType) => void;
}

const destinations: { tab: TabType; label: string }[] = [
  { tab: 'workspace', label: 'Workspace' }, { tab: 'overview', label: 'Overview' },
  { tab: 'markets', label: 'Markets' }, { tab: 'watchlist', label: 'Watchlist' },
  { tab: 'positions', label: 'Positions' },
  { tab: 'trades', label: 'Journal' }, { tab: 'strategy', label: 'Strategy' },
  { tab: 'risk', label: 'Risk Control' }, { tab: 'performance', label: 'Performance' },
  { tab: 'backtesting', label: 'Research' }, { tab: 'system', label: 'System Logs' },
  { tab: 'settings', label: 'Settings' },
];
const factors = ['trend', 'structure', 'liquidity', 'momentum', 'volatility', 'risk'] as const;
const value = (input: unknown) => typeof input === 'string' && input.length ? input : 'unavailable';

const InternalDetailsContext = React.createContext(false);

const Panel: React.FC<React.PropsWithChildren<{
  title: string; source: string; state: PanelState; observed?: unknown; className?: string;
}>> = ({ title, source, state, observed, className = '', children }) => {
  const internalDetails = React.useContext(InternalDetailsContext);
  return <section className={`workspace-card ${className}`} data-state={state} aria-label={title}>
    <div className="workspace-card-heading"><h2>{title}</h2><span className="workspace-state">{state === 'ERROR' ? 'UNAVAILABLE' : state}</span></div>
    {internalDetails && <details className="workspace-inline-details workspace-provenance"><summary>Source details</summary><p className="workspace-eyebrow">{source}</p>
      {observed !== undefined && <p className="workspace-source-time">Source observation: {formatTime(observed)} / age {formatAge(observed)}</p>}
    </details>}
    {children}
  </section>;
};

const ReadinessItem: React.FC<{ label: string; source: string; result: string; observed: unknown; age?: string; state?: PanelState }> =
  ({ label, source, result, observed, age, state }) => <li aria-label={label} data-state={state}><strong>{label}</strong><span>{result}</span><small>{source} · {formatTime(observed)} · age {age ?? formatAge(observed)}</small></li>;

export const WorkspacePage: React.FC<Props> = ({
  hosted = false,
  configurationOnly = false,
  internalDetails = false, broker, safety, risk, monitoring, observationHealth, watchlist, caps,
  execution, terminalObservation, activeAnalysis, assistantStatus, notificationStatus,
  liveExecution, onExecuteLiveCycle,
  selectedSymbol, selectedTimeframe, onMarketChange, lifecycle, onNavigate,
}) => {
  const [evidenceClock, setEvidenceClock] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setEvidenceClock(Date.now()), 5000);
    return () => window.clearInterval(timer);
  }, []);
  const [compactPriceScale, setCompactPriceScale] = useState(false);
  const toggleCompactPriceScale = () => setCompactPriceScale(value => !value);
  const [aiOpen, setAiOpen] = useState(false);
  const [wideWorkspace, setWideWorkspace] = useState(() => window.innerWidth >= 900);
  useEffect(() => {
    const resize = () => setWideWorkspace(window.innerWidth >= 900);
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const aiDocked = wideWorkspace && !aiOpen && !configurationOnly;
  interface AiThreadEntry { role: 'user' | 'assistant'; text: string; at: string; image?: AssistantImage; kind?: 'error' | 'warning' | 'pending' }
  const [aiThread, setAiThread] = useState<AiThreadEntry[]>([]);
  const [aiDraft, setAiDraft] = useState('');
  const [aiImage, setAiImage] = useState<AssistantImage | null>(null);
  const [aiImageError, setAiImageError] = useState('');
  const [aiImageLoading, setAiImageLoading] = useState(false);
  const aiFileInput = useRef<HTMLInputElement>(null);
  const selectImage = async (file?: File) => {
    if (!file) return;
    setAiImageLoading(true); setAiImageError('');
    try { setAiImage(await prepareAssistantImage(file)); }
    catch (error) { setAiImageError(error instanceof Error ? error.message : 'Unable to read this image.'); }
    finally { setAiImageLoading(false); if (aiFileInput.current) aiFileInput.current.value = ''; }
  };
  const [aiDark, setAiDark] = useState(() => { try { return window.localStorage.getItem('jqe-ai-dark') === '1'; } catch { return false; } });
  const toggleAiDark = () => setAiDark(value => {
    try { window.localStorage.setItem('jqe-ai-dark', value ? '0' : '1'); } catch { /* storage unavailable */ }
    return !value;
  });
  const [aiSending, setAiSending] = useState(false);
  const aiThreadEnd = useRef<HTMLDivElement | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [query, setQuery] = useState('');
  const aiLauncher = useRef<HTMLButtonElement>(null);
  const aiClose = useRef<HTMLButtonElement>(null);
  const paletteTrigger = useRef<HTMLButtonElement>(null);
  const paletteInput = useRef<HTMLInputElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const brokerValid = validBroker(broker.data);
  const brokerState = broker.data && !brokerValid ? 'UNAVAILABLE'
    : observationState(broker, broker.data?.observed_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.brokerStatus);
  const brokerData = brokerValid && ['LIVE', 'STALE'].includes(brokerState) ? broker.data : null;
  const brokerObservedAt = brokerData?.observed_at;
  const brokerAge = formatAge(brokerObservedAt);
  const identity = brokerData?.active_broker_identity;
  const identityMatches = identity?.broker === brokerData?.active_broker;
  const guardPassed = identity?.demo_guard_passed === true;
  const verifiedAt = identity?.verified_at && Number.isFinite(Date.parse(identity.verified_at)) ? identity.verified_at : null;
  const verificationAge = formatAge(verifiedAt);
  const verificationFresh = !!verifiedAt && withinAge(verifiedAt, WORKSPACE_FRESHNESS_THRESHOLDS_MS.demoVerification);
  const liveConnected = brokerData?.live_connection_state === 'CONNECTED'
    || (!brokerData?.live_connection_state && brokerData?.observation_state === 'OBSERVED' && brokerData.connected);
  const demoResult = !guardPassed
    ? { verified: false, text: 'unverified · demo guard not passed', tone: 'danger' }
    : !identityMatches
      ? { verified: false, text: 'unverified · identity mismatch', tone: 'danger' }
      : !verifiedAt
        ? { verified: false, text: 'unverified · no verification time', tone: 'neutral' }
        : !verificationFresh
          ? { verified: false, text: `unverified · evidence expired (age ${verificationAge})`, tone: 'neutral' }
          : !liveConnected
            ? { verified: false, text: `unverified · live connection unavailable (status age ${brokerAge})`, tone: 'neutral' }
            : { verified: true, text: `Yes · age ${verificationAge}`, tone: 'verified' };
  const demoVerified = demoResult.verified;
  const maskedAccount = identityMatches && identity?.account_id_masked?.includes('*')
    ? identity.account_id_masked : 'unavailable';
  const liveConnection = brokerData?.live_connection_state === 'CONNECTED'
    ? 'Yes · live'
    : brokerData?.live_connection_state === 'DISCONNECTED'
      ? 'No · live'
      : 'unavailable';
  const brokerConnectionLabel = brokerData?.active_broker === 'weltrade'
    ? 'Weltrade'
    : brokerData?.active_broker === 'mt5'
      ? 'MT5'
      : 'Broker';
  const brokerConnectionAvailable = brokerData?.active_broker === 'weltrade' || brokerData?.active_broker === 'mt5';

  const activeSetup = activeAnalysis?.data && validAssessment(activeAnalysis.data.setup)
    ? activeAnalysis.data.setup : null;
  const activeCandles = activeAnalysis?.data && Array.isArray(activeAnalysis.data.candles?.candles)
    ? activeAnalysis.data.candles : null;
  const marketContext = activeAnalysis?.data?.context;
  const initialMarketLoading = activeAnalysis?.loading === true && activeAnalysis.data === null;
  const initialTerminalLoading = terminalObservation?.loading === true && terminalObservation.data === null;
  const marketFreshness = initialMarketLoading ? 'loading closed candles' : activeAnalysis?.error || activeAnalysis?.stale
    ? 'unavailable · last request failed'
    : marketContext?.freshness_state === 'FRESH' ? 'fresh · closed candles'
    : marketContext?.freshness_state
      ? `${marketContext.freshness_state.toLowerCase()} · ${reasonText(marketContext.freshness_reason_codes)}`
      : 'unavailable';
  const chartDataStatus = marketContext?.freshness_state === 'FRESH' && !activeAnalysis?.stale
    ? activeCandles?.market_data_status
    : marketContext?.freshness_state === 'UNKNOWN' ? 'UNKNOWN'
    : activeCandles ? 'CACHED' : 'UNAVAILABLE';
  const activeSignal = activeAnalysis?.data?.signal ?? null;
  const activeAnalysisState = activeAnalysis ? panelState(activeAnalysis) : 'UNAVAILABLE';
  const assessmentValid = validAssessment(monitoring.data?.assessment);
  const lifecycleMonitoringState: PanelState = monitoring.data?.assessment && !assessmentValid ? 'UNAVAILABLE'
    : monitoring.data && monitoring.data.assessment === null && !monitoring.error ? 'STALE'
    : lifecycle.state === 'UNAVAILABLE' ? 'UNAVAILABLE'
    : monitoring.error ? panelState(monitoring)
    : lifecycle.state;
  const monitoringState = activeSetup
    ? activeAnalysisState
    : lifecycleMonitoringState === 'LIVE'
    ? observationState(monitoring, monitoring.data?.observed_at ?? monitoring.data?.assessment?.observed_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.monitoring)
    : lifecycleMonitoringState;
  const assessment = activeSetup ?? (assessmentValid && monitoringState === 'LIVE' ? monitoring.data?.assessment : null);
  const safetyTransportState = observationState(safety, safety.data?.observed_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.executionSafety);
  const safetyState = safety.data && !validSafety(safety.data) ? 'UNAVAILABLE'
    : safetyTransportState === 'LIVE' && safety.data?.observation_state === 'STALE' ? 'STALE' : safetyTransportState;
  const riskObservedAt = risk.data?.observation_age_seconds === null || risk.data?.observation_age_seconds === undefined
    ? null : new Date(Date.now() - risk.data.observation_age_seconds * 1000).toISOString();
  const riskState = risk.data && !validRisk(risk.data) ? 'UNAVAILABLE'
    : observationState(risk, riskObservedAt, WORKSPACE_FRESHNESS_THRESHOLDS_MS.risk);
  const healthValid = validHealth(observationHealth.data);
  const healthState = observationHealth.data && !healthValid ? 'UNAVAILABLE'
    : observationState(observationHealth, observationHealth.data?.updated_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.observationHealth);
  const executionSupervisor = observationHealth.data?.execution_supervisor;
  const supervisorAge = executionSupervisor?.updated_at ? (evidenceClock - Date.parse(executionSupervisor.updated_at)) / 1000 : null;
  const supervisorFresh = !observationHealth.error && !observationHealth.stale && executionSupervisor?.stale === false && supervisorAge !== null && supervisorAge >= 0 && supervisorAge <= executionSupervisor.max_age_seconds;
  const supervisorState = !executionSupervisor ? 'UNAVAILABLE' : !supervisorFresh ? 'STALE' : executionSupervisor.state;
  const health = healthValid && healthState === 'LIVE' ? observationHealth.data : null;
  const watchlistState = watchlist.data && !validWatchlist(watchlist.data) ? 'UNAVAILABLE' : panelState(watchlist);
  const capState = caps.data && !validCaps(caps.data) ? 'UNAVAILABLE'
    : observationState(caps, caps.data?.observed_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.watchlistCapUsage);
  const executionData = execution?.data ?? null;
  const executionState = execution ? panelState(execution) : 'UNAVAILABLE';
  const terminal = terminalObservation?.data ?? null;
  const tradingPermissions: [string, boolean | null][] = terminal ? [
    ['Account', terminal.account_trading_allowed],
    ['Expert', terminal.expert_trading_allowed],
    ['Terminal', terminal.terminal_trading_allowed],
    ['API', terminal.trade_api_disabled == null ? null : !terminal.trade_api_disabled],
  ] : [];
  const terminalState = initialTerminalLoading ? 'LOADING' : terminalObservation?.error ? 'UNAVAILABLE'
    : terminal?.state === 'CONNECTED' ? 'LIVE'
    : terminal?.state === 'DISCONNECTED' ? 'OFFLINE'
    : 'UNAVAILABLE';
  const assistantState = assistantStatus?.data?.state ?? 'UNAVAILABLE';
  const assistantLabel = assistantState === 'READY' ? 'CONFIGURED' : assistantState;
  const notificationCandidate = notificationStatus?.data ?? null;
  const notificationData = notificationCandidate &&
    Array.isArray(notificationCandidate.channels) &&
    notificationCandidate.channels.every(channel => Array.isArray(channel.reason_codes)) &&
    notificationCandidate.daily_digest &&
    Array.isArray(notificationCandidate.daily_digest.reason_codes)
    ? notificationCandidate : null;
  const notificationState = notificationData && notificationStatus
    ? panelState(notificationStatus) : 'UNAVAILABLE';
  const notificationSummary = notificationData?.channels.map(channel => `${channel.channel} ${channel.state}`).join(' · ');
  const liveSetup = activeSetup ?? (assessment?.setup_state === 'READY' ? assessment : null);
  const canExecuteLiveCycle = Boolean(
    !hosted &&
    brokerData?.broker_execution_enabled === true &&
    brokerData.active_broker !== 'simulation' &&
    brokerData.connected === true &&
    demoVerified &&
    liveSetup?.setup_state === 'READY' &&
    liveSetup.direction !== 'NO_TRADE'
  );
  const filteredDestinations = destinations.filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase()));

  const closeAi = () => { setAiOpen(false); aiLauncher.current?.focus(); };
  const closePalette = () => { setPaletteOpen(false); setQuery(''); returnFocus.current?.focus(); };
  const navigate = (tab: TabType) => { closePalette(); onNavigate(tab); };
  const sendAssistantMessage = async () => {
    const image = aiImage;
    const message = aiDraft.trim() || (image ? 'Analyze this screenshot for research.' : '');
    if (!message || aiSending || aiImageLoading || assistantState !== 'READY') return;
    const askedAt = new Date().toISOString();
    setAiDraft('');
    setAiSending(true);
    setAiImage(null);
    setAiThread(thread => [...thread, { role: 'user', text: message, at: askedAt, image: image ?? undefined }, { role: 'assistant', text: 'Thinking…', at: askedAt, kind: 'pending' }]);
    try {
      const response = await jqeApi.chatWithAssistant(message, undefined,
        { symbol: selectedSymbol, timeframe: selectedTimeframe }, image?.url);
      const answer = response.answer ?? response.message ?? 'No answer was returned.';
      setAiThread(thread => [...thread.slice(0, -1), { role: 'assistant', text: answer, at: new Date().toISOString(), kind: response.warning ? 'warning' : undefined }]);
    } catch (error) {
      setAiImage(image); setAiDraft(message);
      const text = error instanceof Error ? error.message : 'JQE AI is unavailable.';
      window.dispatchEvent(new CustomEvent('jqe:notification', { detail: { title: 'JQE AI', detail: text } }));
      setAiThread(thread => [...thread.slice(0, -1), { role: 'assistant', text: 'Question failed. See Notifications.', at: new Date().toISOString(), kind: 'error' }]);
    } finally {
      setAiSending(false);
    }
  };
  useEffect(() => {
    if (configurationOnly) return;
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : paletteTrigger.current;
        setPaletteOpen(true);
      } else if (event.key === 'Escape') {
        if (paletteOpen) closePalette();
        else if (aiOpen) closeAi();
      } else if (event.key === 'Tab' && (paletteOpen || aiOpen)) {
        const dialog = document.querySelector(paletteOpen ? '.workspace-palette' : '.workspace-ai-panel');
        const focusable = Array.from(dialog?.querySelectorAll<HTMLElement>('button, input, textarea') ?? []);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [paletteOpen, aiOpen, configurationOnly]);
  useEffect(() => { if (paletteOpen) paletteInput.current?.focus(); }, [paletteOpen]);
  useEffect(() => { if (aiOpen) aiClose.current?.focus(); }, [aiOpen]);
  useEffect(() => { aiThreadEnd.current?.scrollIntoView({ block: 'end' }); }, [aiThread, aiOpen]);

  const PageRoot = configurationOnly ? 'section' : 'main';
  return <InternalDetailsContext.Provider value={internalDetails}><PageRoot className={`workspace-page${aiDocked ? ' workspace-studio' : ''}`}>
    {configurationOnly && <>
      <div className="workspace-topbar-facts" aria-label="Broker and execution status">
        <div><span>Live broker connection</span><strong>{liveConnection}</strong></div>
        <div className={`workspace-demo-result workspace-demo-result-${demoResult.tone}`}><span>Demo verified</span><strong>{demoResult.text}</strong></div>
        <div><span>Market data freshness</span><strong>{marketFreshness}</strong></div>
        <div><span>Broker execution</span><strong>{brokerData ? brokerData.broker_execution_enabled ? 'enabled · guarded demo only' : 'disabled' : 'unavailable'}</strong></div>
      </div>
    {internalDetails && <details className="workspace-details workspace-operational-details">
      <summary>Connection and operational checks</summary>
      <div className="workspace-operational-facts">
        <span>Reported active broker<strong>{brokerData?.active_broker ?? 'unavailable'}</strong></span>
        <span>Masked account<strong>{maskedAccount}</strong></span>
        <span>Verified <strong>{formatTime(verifiedAt)}</strong></span>
        <span>Broker-status observation age<strong>{brokerAge}</strong></span>
        <span>Execution<strong>{executionData ? `${executionData.connected ? 'connected' : 'disconnected'} · ${executionData.open_positions_count} open` : 'unavailable'}</strong></span>
        <span>Execution snapshot<strong>{safetyState === 'LIVE' ? value(safety.data?.execution_authorization) : `${safetyState.toLowerCase()} · fail closed`}</strong></span>
        <span>Research batch job<strong>unknown · no live job telemetry</strong></span>
      </div>
      <p className="workspace-switch-note">Broker selection is fixed to Weltrade for this installation.</p>

    <Panel title="Readiness" source="Evidence checklist" state={brokerState} className="workspace-readiness">
      <ul className="workspace-readiness-list">
        <ReadinessItem label={`${brokerConnectionLabel} connection`} source="GET /brokers/status · live execution session" result={brokerConnectionAvailable ? liveConnection : 'unavailable'} observed={brokerConnectionAvailable ? brokerData?.live_checked_at ?? null : null} age={brokerConnectionAvailable ? formatAge(brokerData?.live_checked_at) : 'unavailable'} />
        <ReadinessItem label="Demo verification" source="GET /brokers/status · DemoOnlyGuard" result={demoVerified ? 'Verified' : 'unverified'} observed={verifiedAt} />
        <ReadinessItem label="Execution status" source="GET /execution · broker state" state={executionState} result={executionData ? `${executionData.connected ? 'Connected' : 'Disconnected'} · ${executionData.open_positions_count} open positions` : executionState.toLowerCase()} observed={null} />
        <ReadinessItem label="Weltrade supervisor heartbeat" source="GET /observation/health · supervisor + PainX" state={healthState} result={health ? health.running && health.healthy ? 'Healthy' : 'Not healthy' : healthState.toLowerCase()} observed={health?.updated_at} />
        <ReadinessItem label="Notification channel" source="GET /notifications/status · configuration" state={notificationState} result={notificationSummary ?? notificationState.toLowerCase()} observed={notificationData?.observed_at ?? null} />
      </ul>
      {brokerData?.broker_execution_enabled === true && <div className="workspace-live-action">
        <div>
          <strong>Demo execution</strong>
          <small>{hosted ? 'Monitor guarded demo execution from this dashboard.' : canExecuteLiveCycle ? 'Ready to run one guarded cycle.' : 'Waiting for a fresh verified demo setup.'}</small>
        </div>
        <button
          type="button"
          disabled={!canExecuteLiveCycle || liveExecution?.loading === true}
          onClick={() => {
            if (window.confirm('Run one JQE cycle and allow a demo broker order if every guard passes?')) {
              onExecuteLiveCycle?.();
            }
          }}
        >
          {liveExecution?.loading ? 'Executing…' : 'Execute demo cycle'}
        </button>
        {liveExecution?.result && <p role="status">{liveExecution.result.status} · {liveExecution.result.reason || liveExecution.result.order_id || 'No additional detail'}</p>}
        {liveExecution?.error && <p role="alert">Cycle failed. See Notifications.</p>}
      </div>}
    </Panel>
    </details>}</>}

    {!configurationOnly && <div className="workspace-grid workspace-primary">
      <Panel title="Market chart" source="GET /market/active-analysis · canonical snapshot" state={initialMarketLoading ? 'LOADING' : activeCandles ? activeAnalysisState : 'UNAVAILABLE'} className={`workspace-chart${activeCandles ? '' : ' workspace-chart-unavailable'}`}>
        <div className="workspace-chart-controls" aria-label="Chart market controls">
          <strong>{selectedSymbol}</strong>
          {['M1', 'M5', 'M15', 'H1'].map(tf => <button key={tf} type="button" aria-pressed={selectedTimeframe === tf}
            onClick={() => onMarketChange?.(selectedSymbol, tf)}>{tf}</button>)}
          <button type="button" className="chart-density-toggle" aria-pressed={compactPriceScale}
            title="Use smaller price labels and a narrower right price axis"
            onClick={toggleCompactPriceScale}>{compactPriceScale ? 'Full prices' : 'Compact prices'}</button>
          <span>Weltrade · {marketFreshness}</span>
        </div>
        {activeCandles ? <MarketChart
          symbol={activeCandles.symbol}
          timeframe={activeCandles.timeframe}
          candles={activeCandles.candles}
          signal={activeSignal}
          setup={activeSetup}
          priceDecimals={activeCandles.price_decimals}
          loading={activeAnalysis?.loading}
          error={activeAnalysis?.error ? 'Market data unavailable. See Notifications.' : null}
          dataStatus={chartDataStatus}
          height={aiDocked ? 560 : 460}
          compactPriceScale={compactPriceScale}
          onToggleCompactPriceScale={toggleCompactPriceScale}
        /> : <div className="workspace-chart-frame">
          {!initialMarketLoading && <p className="workspace-empty">Active market analysis is unavailable.</p>}
          <div className="workspace-chart-overlay" role="status">{initialMarketLoading ? 'Fetching closed candles from Weltrade...' : 'No market snapshot - see Notifications'}</div>
        </div>}
        {internalDetails && <details className="workspace-inline-details"><summary>Snapshot details</summary><p className="workspace-source-time">Canonical snapshot: {activeCandles ? `${activeCandles.symbol} / ${activeCandles.timeframe}` : `${selectedSymbol} / ${selectedTimeframe}`} · freshness {marketFreshness} · latest closed candle {formatTime(marketContext?.latest_closed_candle_at)}. The strategy, setup, and candles share one observation.</p></details>}
      </Panel>      <Panel title="Decision trail" source="GET /monitoring/offline · offline assessment" state={monitoringState} observed={assessment?.observed_at} className="workspace-decision">
        {!assessment ? <div className="workspace-no-assessment"><p className="workspace-empty">No current assessment</p><details className="workspace-inline-details"><summary>Factor availability</summary><div className="workspace-factors">{factors.map(name => <span key={name}>{name}: unavailable</span>)}</div></details></div> : <>
        {internalDetails && <details className="workspace-inline-details"><summary>Observation details</summary>        <p className="workspace-note">Shared assessment-level timestamps: observed {formatTime(assessment.observed_at)} · candle close {formatTime(assessment.candle_close_time)} · expires {formatTime(assessment.expires_at)}. No per-stage timestamps are supplied.</p>
</details>}
        <ol className="workspace-stages">
          <li><strong>Data freshness</strong><span>{value(assessment.data_freshness.status)}</span><small>{reasonText(assessment.data_freshness.reason_codes)}</small></li>
          <li><strong>Analysis</strong><span>{value(assessment.setup_state)}</span><small>{reasonText(assessment.reason_codes)}</small></li>
          <li><strong>Strategy score</strong><span>{assessment.confidence_score ?? 'unavailable'}</span>
            <details className="workspace-inline-details"><summary>Six-factor breakdown</summary>            <div className="workspace-factors">{factors.map(name => {
              const factor = assessment.evidence.find(item => item.factor === name);
              return <span key={name}>{name}: {factor ? `${factor.score} / ${factor.maximum_score} · ${factor.assessment}` : 'unavailable'}</span>;
            })}</div></details>
          </li>
          <li><strong>Risk</strong><span>{value(assessment.risk_authorization.status)}</span><small>{reasonText(assessment.risk_authorization.reason_codes)}</small></li>
          <li><strong>Execution policy</strong><span>{value(assessment.execution_authorization.status)}</span><small>{reasonText(assessment.execution_authorization.reason_codes)}</small></li>
          <li><strong>Daily cap</strong><span>{capState === 'LIVE' ? `${caps.data!.items.length} instrument rows` : 'unavailable'}</span><small>{internalDetails ? 'GET /watchlist/cap-usage · observed ' : 'Observed '}{capState === 'LIVE' ? formatTime(caps.data?.observed_at) : 'unavailable'}</small></li>
          <li><strong>Broker</strong><span>{brokerData ? brokerData.active_broker : 'unavailable'}</span><small>{internalDetails && 'GET /brokers/status · '}{brokerData ? brokerData.observation_state : 'unavailable'}</small></li>
        </ol></>}
        {internalDetails && <details className="workspace-inline-details"><summary>Safety evidence</summary>        <div className="workspace-context"><strong>Separate broker context</strong><span>GET /brokers/status: {brokerState}</span><span>GET /execution/safety: {safetyState} · {safetyState === 'LIVE' ? value(safety.data?.execution_authorization) : 'unavailable'}</span><span>GET /risk: {riskState} · {riskState === 'LIVE' ? value(risk.data?.observation_status) : 'unavailable'}</span></div></details>}
      </Panel>
      <Panel title="Weltrade terminal" source="Direct MT5 observation · execution disabled" state={terminalState} observed={terminal?.observed_at} className="workspace-terminal">
        <div className="workspace-supervisor" role="status" aria-label="Execution supervisor evidence" data-state={supervisorFresh && executionSupervisor?.process_alive && ['RUNNING', 'STARTING', 'BLOCKED'].includes(supervisorState) ? 'LIVE' : supervisorState}>
          <strong>Guarded demo supervisor · {supervisorState}</strong>
          <span>Heartbeat {formatTime(executionSupervisor?.updated_at)} · age {formatAge(executionSupervisor?.updated_at)} · cycle {executionSupervisor?.cycle_number ?? 'unknown'}</span>
          <span>Process {executionSupervisor ? executionSupervisor.process_alive ? 'alive' : 'not alive / unverified' : 'unknown'} · stale {supervisorFresh ? 'No' : 'Yes'}</span>
          <small>Read-only evidence; does not authorize orders.</small>
        </div>
        {!terminal || terminal.state !== 'CONNECTED' ? <p className="workspace-terminal-disconnected">
          {initialTerminalLoading ? 'Checking Weltrade terminal...' : terminalObservation?.error || terminal?.error ? 'Terminal unavailable - see Notifications' : 'Terminal disconnected - no current account or market values'}
        </p> : <>
          <div className="workspace-terminal-metrics">
            <span>Environment<strong>{terminal.environment} · {terminal.server ?? 'server unavailable'} · {terminal.account_id_masked ?? 'account unavailable'}</strong></span>
            <span>Balance<strong>{terminal.balance == null ? '—' : `${terminal.balance.toLocaleString()} ${terminal.currency ?? ''}`}</strong></span>
            <span>Equity<strong>{terminal.equity == null ? '—' : `${terminal.equity.toLocaleString()} ${terminal.currency ?? ''}`}</strong></span>
            <span>Margin / free<strong>{terminal.margin == null ? '—' : `${terminal.margin.toLocaleString()} / ${(terminal.free_margin ?? 0).toLocaleString()} ${terminal.currency ?? ''}`}</strong></span>
            <span>Trading permissions<strong className="workspace-permissions">{tradingPermissions.map(([label, allowed]) => <em key={label} data-allowed={allowed == null ? 'unknown' : allowed ? 'yes' : 'no'}>{`${allowed == null ? '·' : allowed ? '✓' : '✗'} ${label}`}</em>)}</strong></span>
            <span>Observation API orders<strong>{terminal.execution_enabled ? 'Enabled' : 'Disabled'}</strong><small>Observation API only</small></span>
            <span>Daily research target · 20%<strong>{terminal.daily_accounting ? `${terminal.daily_accounting.advisory_target_amount.toFixed(2)} ${terminal.daily_accounting.currency}` : 'Awaiting complete daily broker history'}</strong><small>Existing risk limits apply · no forced trades</small></span>
            <span>Starting balance · 00:00 UTC<strong>{terminal.daily_accounting ? `${terminal.daily_accounting.starting_balance.toFixed(2)} ${terminal.daily_accounting.currency}` : 'Unavailable'}</strong><small>Reconstructed from broker history</small></span>
            <span>Realized net P&amp;L · UTC<strong>{terminal.daily_accounting ? `${terminal.daily_accounting.realized_net_pnl.toFixed(2)} ${terminal.daily_accounting.currency}` : 'Unavailable'}</strong><small>Excludes deposits &amp; floating P&amp;L</small></span>
          </div>
          <div className="workspace-terminal-observations">
            <div><span>Current tick · {terminal.tick?.symbol ?? selectedSymbol}</span><strong>{terminal.tick ? `${terminal.tick.bid} / ${terminal.tick.ask}` : 'Unavailable'}</strong><small>{terminal.tick ? `Terminal tick · ${formatTime(terminal.tick.time)}` : 'No current terminal tick'}</small></div>
            <div><span>Latest closed candle · {terminal.candle?.symbol ?? selectedSymbol} {terminal.candle?.timeframe ?? selectedTimeframe}</span><strong>{terminal.candle?.close ?? 'Unavailable'}</strong><small>{terminal.candle ? `Direct terminal read · closed ${formatTime(terminal.candle.closed_at)}` : 'No closed candle returned'}</small></div>
            <div><span>Contract economics · {terminal.symbol_specification?.name ?? selectedSymbol}</span><strong>{terminal.symbol_specification ? `Tick ${terminal.symbol_specification.trade_tick_size ?? '—'} · value ${terminal.symbol_specification.trade_tick_value ?? '—'}` : 'Unavailable'}</strong><small>{terminal.symbol_specification ? `Volume ${terminal.symbol_specification.volume_min ?? '—'}–${terminal.symbol_specification.volume_max ?? '—'} · step ${terminal.symbol_specification.volume_step ?? '—'}` : 'No terminal symbol specification'}</small></div>
          </div>
          <details className="workspace-inline-details">
            <summary>Terminal positions ({terminal.positions.length}) and recent history ({terminal.recent_trades.length})</summary>
            <div className="workspace-terminal-records">
              <div><strong>Open positions</strong>{terminal.positions.length ? terminal.positions.map(position => <span key={position.id}>{position.symbol} {position.side} {position.volume} · P/L {position.profit}</span>) : <span>None reported</span>}</div>
              <div><strong>Recent closed trades</strong>{terminal.recent_trades.length ? terminal.recent_trades.slice(-5).reverse().map(trade => <span key={trade.id}>{trade.symbol} {trade.side} {trade.volume} · P/L {trade.profit} · {formatTime(trade.close_time)}</span>) : <span>None in returned history window</span>}</div>
            </div>
          </details>
        </>}
      </Panel>

    </div>}

    {!configurationOnly && <details className="workspace-details workspace-notes">
      <summary>Metric definitions and platform notes</summary>
      <ul className="workspace-notes-list">
        <li><strong>Advisory target</strong> 20% of the reconstructed 00:00 UTC starting balance. Existing risk limits apply and no trades are forced.</li>
        <li><strong>Starting balance</strong> reconstructed from complete broker balance movements for the current UTC day.</li>
        <li><strong>Realized net P&amp;L</strong> includes trading fees; excludes deposits, withdrawals and floating P&amp;L.</li>
        <li><strong>Observation API orders</strong> is a separate permission from broker execution; read-only monitoring does not authorize orders.</li>
        <li><strong>PainX research</strong> validates with timestamp and partition audits; batch job activity is not reported by this API.</li>
      </ul>
    </details>}

    {configurationOnly && <details className="workspace-details workspace-more-details">
      <summary>Watchlist, research and operational details</summary>
    <div className="workspace-grid workspace-secondary">
      <Panel title="Watchlist" source="GET /watchlist" state={watchlistState}>
        {watchlistState === 'LIVE' && watchlist.data?.items.length === 0 ? <p className="workspace-empty">Watchlist is empty.</p>
          : watchlistState === 'LIVE' ? <ul className="workspace-list">{watchlist.data?.items.map((item, index) => <li key={`${item.scope}-${item.symbol}-${item.timeframe}-${index}`}>
            <button type="button" className="workspace-market-select" aria-label={`Analyze ${item.symbol} ${item.timeframe}`}
              aria-current={selectedSymbol === item.symbol && selectedTimeframe === item.timeframe ? 'true' : undefined}
              onClick={() => onMarketChange?.(item.symbol, item.timeframe)}>
              <strong>{item.symbol} · {item.timeframe}</strong><span>{item.scope}</span><small>Row freshness unavailable</small>
            </button>
          </li>)}</ul>
            : <p className="workspace-empty">{watchlistState === 'ERROR' ? 'Watchlist unavailable. See Notifications.' : `Watchlist ${watchlistState.toLowerCase()}`}</p>}
      </Panel>
      <Panel title="Instrument caps" source="GET /watchlist/cap-usage · DailyInstrumentTradeGuard" state={capState} observed={capState === 'LIVE' ? caps.data?.observed_at : null}>
        {capState === 'LIVE' && caps.data?.items.length === 0 ? <p className="workspace-empty">No cap rows returned.</p>
          : capState === 'LIVE' ? <ul className="workspace-list">{caps.data?.items.map((item, index) => <li key={`${item.scope}-${item.symbol}-${item.timeframe}-${index}`}><strong>{item.symbol} · {item.timeframe}</strong><span>{item.daily_count} / {item.daily_limit} today · {item.available ? 'available' : 'cap reached'}</span><small>Reset {formatTime(item.reset_at)}</small></li>)}</ul>
            : <p className="workspace-empty">{capState === 'ERROR' ? 'Cap data unavailable. See Notifications.' : `Cap data ${capState.toLowerCase()}`}</p>}
      </Panel>
      <Panel title="Quick actions" source="Frontend navigation only" state="LIVE">
        <div className="workspace-actions">{(['markets', 'watchlist', 'risk', 'backtesting'] as TabType[]).map(tab => <button type="button" key={tab} onClick={() => onNavigate(tab)}>Open {destinations.find(item => item.tab === tab)?.label}</button>)}</div>
      </Panel>
    </div>

    <div className="workspace-grid workspace-unavailable">
      <Panel title="Latest signal" source="GET /market/active-analysis · canonical snapshot" state={activeSignal ? activeAnalysisState : 'UNAVAILABLE'}>
        {activeSignal ? <><p><strong>{activeSignal.signal}</strong> · confidence {activeSignal.confidence} · {activeSignal.quality}</p><p>{Array.isArray(activeSignal.reasons) && activeSignal.reasons.length ? activeSignal.reasons.join(' · ') : 'No reason code supplied'}</p></> : <p>Active market analysis is unavailable.</p>}
      </Panel>
      <Panel title="Paper simulation" source="GET /monitoring/offline · durable simulated outcome" state={monitoringState} observed={monitoring.data?.latest_paper_outcome?.recorded_at}>
        <p><strong>SIMULATED ONLY</strong> · broker execution {monitoring.data?.broker_execution_enabled ? 'ENABLED' : 'DISABLED'}</p>
        <p>{monitoring.data?.open_paper_positions ?? 0} open paper positions</p>
        {monitoring.data?.latest_paper_outcome
          ? <><p>{monitoring.data.latest_paper_outcome.status} · {monitoring.data.latest_paper_outcome.message}</p>
            <small>Order {monitoring.data.latest_paper_outcome.order_id ?? 'none'} · close {monitoring.data.latest_paper_outcome.close_reason ?? 'open'} · realized {monitoring.data.latest_paper_outcome.realized_pnl ?? 'pending'}</small></>
          : <p>No persisted paper outcome.</p>}
      </Panel>
      <Panel title="PainX research" source="GET /monitoring/offline · separate research status" state={monitoring.data?.research_status ? 'LIVE' : 'UNAVAILABLE'}>
        {monitoring.data?.research_status
          ? <><p><strong>{monitoring.data.research_status.status.replace(/_/g, ' ')}</strong></p><p>{monitoring.data.research_status.presentation_rule}</p><small>Execution authority: {monitoring.data.research_status.execution_authority ?? 'NONE_RESEARCH_ONLY'}</small></>
          : <p>Research status unavailable.</p>}
      </Panel>
      <Panel title="Daily digest" source="GET /notifications/status · digest telemetry" state={notificationData ? notificationState : 'UNAVAILABLE'} observed={notificationData?.observed_at}>
        {notificationData ? <p><strong>{notificationData.daily_digest.state}</strong> · {notificationData.daily_digest.reason_codes.join(' · ')}{notificationData.daily_digest.last_sent_at ? ` · sent ${formatTime(notificationData.daily_digest.last_sent_at)}` : ''}</p> : <p>Notification status is unavailable.</p>}
      </Panel>
      <Panel title="Notification channels" source="GET /notifications/status · config check" state={notificationData ? notificationState : 'UNAVAILABLE'}>
        {notificationData ? <ul className="workspace-list">{notificationData.channels.map(channel => <li key={channel.channel}><strong>{channel.channel}</strong><span>{channel.state} · {channel.reachability}</span><small>{channel.reason_codes.join(' · ')} · checked {formatTime(channel.checked_at)}</small></li>)}</ul> : <p>Notification status is unavailable.</p>}
      </Panel>
    </div>
    </details>}

    {!configurationOnly && <button ref={aiLauncher} type="button" className="workspace-ai-launcher" aria-label="Open JQE AI" onClick={() => setAiOpen(true)}><span className="workspace-ai-mark" aria-hidden="true"><Activity size={19} /></span><span><strong>JQE AI</strong><small>{assistantLabel}</small></span></button>}
    {(aiOpen || aiDocked) && <div className={aiDocked ? 'workspace-ai-dock' : 'workspace-dialog-backdrop'} onMouseDown={event => { if (!aiDocked && event.target === event.currentTarget) closeAi(); }}>
      <aside className={`workspace-ai-panel${aiDark ? ' workspace-ai-dark' : ''}`} role={aiDocked ? 'complementary' : 'dialog'} aria-modal={aiDocked ? undefined : true} aria-labelledby="workspace-ai-title">
        <header className="workspace-ai-header">
          <div className="workspace-ai-heading">
            <span className="workspace-ai-mark" aria-hidden="true"><Activity size={17} /></span>
            <div>
              <p className="workspace-eyebrow">JQE AI · {assistantState}</p>
              <h2 id="workspace-ai-title">{assistantStatus?.data?.context_mode === 'generic' ? 'General knowledge assistant' : 'Evidence assistant'}</h2>
            </div>
          </div>
          <div className="workspace-ai-header-actions">
            <button type="button" className="workspace-ai-mode" aria-label={aiDark ? 'Switch to light appearance' : 'Switch to dark appearance'} aria-pressed={aiDark} onClick={toggleAiDark}>{aiDark ? <Sun size={15} /> : <Moon size={15} />}</button>
            {!aiDocked && <button ref={aiClose} type="button" className="workspace-ai-close" aria-label="Close assistant" onClick={closeAi}><X size={16} /></button>}
          </div>
        </header>
        <p className="workspace-ai-desc">{assistantStatus?.data?.context_mode === 'generic' ? 'Generic prompts only. Workspace, account and market evidence stays local. Each question is independent.' : 'Explains supplied evidence. Cannot approve risk, broker status or execution.'}</p>
        {assistantState === 'READY'
          ? <div className="workspace-ai-meta">
              <span className="workspace-ai-chip"><span className="workspace-ai-chip-dot" aria-hidden="true" />{assistantStatus?.data?.provider ?? 'unknown'}</span>
              <span className="workspace-ai-chip workspace-ai-chip-model">{assistantStatus?.data?.model}</span>
            </div>
          : <p role="status">Assistant unavailable. See Notifications.</p>}
        <div className="workspace-ai-thread" aria-live="polite">
          {aiThread.length === 0 && assistantState === 'READY' && <div className="workspace-ai-prompts" aria-label="Research prompts">
            {['Explain the trend', 'Why is this NO_TRADE?', 'Show the key levels', 'What evidence is missing?', 'How should I test this idea?'].map(prompt =>
              <button key={prompt} type="button" onClick={() => setAiDraft(prompt)} disabled={aiSending}>{prompt} ↗</button>)}
          </div>}
          {aiThread.length === 0 && <div className="workspace-ai-empty">
            <span className="workspace-ai-empty-mark" aria-hidden="true"><Activity size={22} /></span>
            <strong>No messages yet</strong>
            <span>Ask a question to start the conversation.</span>
          </div>}
          {aiThread.map((entry, index) => (
            <div key={index} className={`workspace-ai-msg workspace-ai-msg-${entry.role}${entry.kind ? ` workspace-ai-msg-${entry.kind}` : ''}`}>
              {entry.image && <img className="workspace-ai-uploaded" src={entry.image.url} alt={`Attached screenshot: ${entry.image.name}`} />}
              <span className="workspace-ai-avatar" aria-hidden="true">{entry.role === 'user' ? 'YOU' : <Activity size={13} />}</span>
              <div className="workspace-ai-bubble">
                <span className="workspace-ai-msg-role">{entry.role === 'user' ? 'You' : 'JQE AI'} · {formatTime(entry.at)}</span>
                {entry.kind === 'pending'
                  ? <span className="workspace-ai-dots" aria-label="JQE AI is thinking"><i /><i /><i /></span>
                  : <p>{entry.text}</p>}
              </div>
            </div>
          ))}
          <div ref={aiThreadEnd} />
        </div>
        {assistantState === 'READY' && <form className="workspace-ai-composer" onSubmit={event => { event.preventDefault(); void sendAssistantMessage(); }}>
          {aiImage && <div className="workspace-ai-attachment"><img src={aiImage.url} alt="Screenshot preview" /><span>{aiImage.name}</span><button type="button" aria-label="Remove screenshot" onClick={() => setAiImage(null)} disabled={aiSending}><X size={14} /></button></div>}
          {aiImageError && <p role="alert" className="workspace-ai-upload-error">{aiImageError}</p>}
          {assistantStatus?.data?.supports_images && <div className="workspace-ai-upload-row">
            <input ref={aiFileInput} type="file" accept="image/png,image/jpeg,image/webp" aria-label="Upload screenshot" hidden onChange={event => void selectImage(event.target.files?.[0])} />
            <button type="button" aria-label="Attach screenshot" disabled={aiSending || aiImageLoading} onClick={() => aiFileInput.current?.click()}><Paperclip size={15} />{aiImageLoading ? 'Preparing…' : 'Screenshot'}</button>
            <small>PNG, JPG, WebP · up to 8 MB</small>
          </div>}
          <div className="workspace-ai-composer-box">
            <textarea aria-label="Ask JQE AI" value={aiDraft} rows={2} onChange={event => setAiDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendAssistantMessage(); } }} disabled={aiSending} placeholder={assistantStatus?.data?.context_mode === 'generic' ? 'Ask about platform or research concepts' : 'Ask about the current evidence'} />
            <button type="submit" aria-label={aiSending ? 'Asking…' : 'Send question'} disabled={aiSending || aiImageLoading || (!aiDraft.trim() && !aiImage)}>{aiSending ? '…' : <SendHorizontal size={16} />}</button>
          </div>
          <small className="workspace-ai-composer-hint">Enter to send · Shift+Enter for a new line</small>
          {aiImage && <small className="workspace-ai-composer-hint">Sending shares this screenshot with JQE’s AI provider through OpenRouter. Remove private account details first. Uploaded images are unverified evidence.</small>}
        </form>}
      </aside></div>}
    {paletteOpen && <div className="workspace-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closePalette(); }}>
      <div className="workspace-palette" role="dialog" aria-modal="true" aria-labelledby="workspace-palette-title">
        <h2 id="workspace-palette-title">Navigate JQE</h2><input ref={paletteInput} aria-label="Find page" value={query} onChange={event => setQuery(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter' && filteredDestinations[0]) navigate(filteredDestinations[0].tab); }} />
        <nav aria-label="Pages">{filteredDestinations.map(item => <button type="button" key={item.tab} onClick={() => navigate(item.tab)}>{item.label}</button>)}</nav>
        <button type="button" onClick={closePalette}>Close navigation</button>
      </div></div>}
  </PageRoot></InternalDetailsContext.Provider>;
};
