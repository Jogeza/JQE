import React, { useEffect, useRef, useState } from 'react';
import { jqeApi } from '../services/api';
import { MarketChart } from '../components/MarketChart';
import type { TabType } from '../components/Sidebar';
import type {
  BrokerStatusResponse, ExecutionSafetyResponse, ObservationHealthResponse,
  OfflineMonitoringResponse, ResourceState, RiskStatusResponse, WatchlistCapUsageResponse,
  WatchlistResponse, ExecutionStateResponse, ActiveMarketAnalysisResponse,
  AssistantStatusResponse, NotificationStatusResponse, LiveExecutionResponse,
} from '../types/api';
import type { TelemetryLifecycle } from '../services/telemetryLifecycle';
import { formatAge, formatTime, observationState, panelState, reasonText, validAssessment, validBroker, validCaps, validHealth, validRisk, validSafety, validWatchlist, withinAge, WORKSPACE_FRESHNESS_THRESHOLDS_MS, type PanelState } from './workspaceEvidence';
import './WorkspacePage.css';

interface Props {
  broker: ResourceState<BrokerStatusResponse>;
  safety: ResourceState<ExecutionSafetyResponse>;
  risk: ResourceState<RiskStatusResponse>;
  monitoring: ResourceState<OfflineMonitoringResponse>;
  observationHealth: ResourceState<ObservationHealthResponse>;
  watchlist: ResourceState<WatchlistResponse>;
  caps: ResourceState<WatchlistCapUsageResponse>;
  execution?: ResourceState<ExecutionStateResponse>;
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
  { tab: 'brokers', label: 'Brokers' }, { tab: 'positions', label: 'Positions' },
  { tab: 'trades', label: 'Trades' }, { tab: 'strategy', label: 'Strategy' },
  { tab: 'risk', label: 'Risk Control' }, { tab: 'performance', label: 'Performance' },
  { tab: 'backtesting', label: 'Research' }, { tab: 'system', label: 'System Logs' },
  { tab: 'settings', label: 'Settings' },
];
const factors = ['trend', 'structure', 'liquidity', 'momentum', 'volatility', 'risk'] as const;
const value = (input: unknown) => typeof input === 'string' && input.length ? input : 'unavailable';

const Panel: React.FC<React.PropsWithChildren<{
  title: string; source: string; state: PanelState; observed?: unknown; className?: string;
}>> = ({ title, source, state, observed, className = '', children }) =>
  <section className={`workspace-card ${className}`} data-state={state} aria-label={title}>
    <div className="workspace-card-heading"><div><p className="workspace-eyebrow">{source}</p><h2>{title}</h2></div><span className="workspace-state">{state}</span></div>
    {observed !== undefined && <p className="workspace-source-time">Source observation: {formatTime(observed)} · age {formatAge(observed)}</p>}
    {children}
  </section>;

const ReadinessItem: React.FC<{ label: string; source: string; result: string; observed: unknown; age?: string; state?: PanelState }> =
  ({ label, source, result, observed, age, state }) => <li aria-label={label} data-state={state}><strong>{label}</strong><span>{result}</span><small>{source} · {formatTime(observed)} · age {age ?? formatAge(observed)}</small></li>;

export const WorkspacePage: React.FC<Props> = ({
  broker, safety, risk, monitoring, observationHealth, watchlist, caps,
  execution, activeAnalysis, assistantStatus, notificationStatus,
  liveExecution, onExecuteLiveCycle,
  selectedSymbol, selectedTimeframe, onMarketChange, lifecycle, onNavigate,
}) => {
  const [aiOpen, setAiOpen] = useState(false);
  const [aiMessage, setAiMessage] = useState('');
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiSending, setAiSending] = useState(false);
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
  const demoResult = !guardPassed
    ? { verified: false, text: 'unverified · demo guard not passed', tone: 'danger' }
    : !identityMatches
      ? { verified: false, text: 'unverified · identity mismatch', tone: 'danger' }
      : !verifiedAt
        ? { verified: false, text: 'unverified · no verification time', tone: 'neutral' }
        : !verificationFresh
          ? { verified: false, text: `unverified · evidence expired (age ${verificationAge})`, tone: 'neutral' }
          : brokerState !== 'LIVE'
            ? { verified: false, text: `unverified · snapshot stale (snapshot age ${brokerAge})`, tone: 'neutral' }
            : { verified: true, text: `Yes · age ${verificationAge}`, tone: 'verified' };
  const demoVerified = demoResult.verified;
  const maskedAccount = identityMatches && identity?.account_id_masked?.includes('*')
    ? identity.account_id_masked : 'unavailable';
  const snapshotConnected = brokerData?.observation_state === 'OBSERVED'
    ? (brokerData.connected ? 'Yes · snapshot reported' : 'No · snapshot reported') : 'unavailable';
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
  const safetyState = safety.data && !validSafety(safety.data) ? 'UNAVAILABLE'
    : observationState(safety, safety.data?.observed_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.executionSafety);
  const riskObservedAt = risk.data?.observation_age_seconds === null || risk.data?.observation_age_seconds === undefined
    ? null : new Date(Date.now() - risk.data.observation_age_seconds * 1000).toISOString();
  const riskState = risk.data && !validRisk(risk.data) ? 'UNAVAILABLE'
    : observationState(risk, riskObservedAt, WORKSPACE_FRESHNESS_THRESHOLDS_MS.risk);
  const healthValid = validHealth(observationHealth.data);
  const healthState = observationHealth.data && !healthValid ? 'UNAVAILABLE'
    : observationState(observationHealth, observationHealth.data?.updated_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.observationHealth);
  const health = healthValid && healthState === 'LIVE' ? observationHealth.data : null;
  const watchlistState = watchlist.data && !validWatchlist(watchlist.data) ? 'UNAVAILABLE' : panelState(watchlist);
  const capState = caps.data && !validCaps(caps.data) ? 'UNAVAILABLE'
    : observationState(caps, caps.data?.observed_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.watchlistCapUsage);
  const executionData = execution?.data ?? null;
  const executionState = execution ? panelState(execution) : 'UNAVAILABLE';
  const assistantState = assistantStatus?.data?.state ?? 'UNAVAILABLE';
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
    const message = aiMessage.trim();
    if (!message || aiSending || assistantState !== 'READY') return;
    setAiSending(true);
    setAiAnswer(null);
    setAiError(null);
    try {
      const response = await jqeApi.chatWithAssistant(message);
      setAiAnswer(response.answer ?? response.message ?? 'No answer was returned.');
      if (response.warning) setAiError(response.warning);
    } catch (error) {
      setAiError(error instanceof Error ? error.message : 'JQE AI is unavailable.');
    } finally {
      setAiSending(false);
    }
  };
  useEffect(() => {
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
        const focusable = Array.from(dialog?.querySelectorAll<HTMLElement>('button, input') ?? []);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [paletteOpen, aiOpen]);
  useEffect(() => { if (paletteOpen) paletteInput.current?.focus(); }, [paletteOpen]);
  useEffect(() => { if (aiOpen) aiClose.current?.focus(); }, [aiOpen]);

  return <main className="workspace-page">
    <header className="workspace-topbar">
      <div className="workspace-title"><p className="workspace-eyebrow">JQE / decision workspace · broker status {brokerState}</p><h1>Research, with the evidence in view.</h1></div>
      <div className="workspace-topbar-facts" aria-label="Broker and execution status">
        <div><span>Reported active broker</span><strong>{brokerData ? brokerData.active_broker : 'unavailable'}</strong></div>
        <div><span>Snapshot-reported connection</span><strong>{snapshotConnected}</strong></div>
        <div className={`workspace-demo-result workspace-demo-result-${demoResult.tone}`}><span>Demo verified</span><strong>{demoResult.text}</strong></div>
        <div><span>Masked account</span><strong>{maskedAccount}</strong></div>
        <div><span>Verified at</span><strong>{formatTime(verifiedAt)}</strong></div>
        <div><span>Broker-status observation age</span><strong>{brokerAge}</strong></div>
        <div><span>Execution</span><strong>{executionData ? `${executionData.connected ? 'connected' : 'disconnected'} · ${executionData.open_positions_count} open` : 'unavailable'}</strong></div>
      </div>
      <button ref={paletteTrigger} type="button" className="workspace-command" onClick={() => {
        returnFocus.current = paletteTrigger.current; setPaletteOpen(true);
      }}>Navigate <kbd>Ctrl/⌘ K</kbd></button>
    </header>
    <p className="workspace-switch-note">Switching not available yet. The workspace does not change the active broker.</p>

    <Panel title="Readiness" source="Evidence checklist" state={brokerState} className="workspace-readiness">
      <ul className="workspace-readiness-list">
        <ReadinessItem label={`${brokerConnectionLabel} connection`} source="GET /brokers/status · snapshot-reported" result={brokerConnectionAvailable ? snapshotConnected : 'unavailable'} observed={brokerConnectionAvailable ? brokerObservedAt : null} age={brokerConnectionAvailable ? brokerAge : 'unavailable'} />
        <ReadinessItem label="Demo verification" source="GET /brokers/status · DemoOnlyGuard" result={demoVerified ? 'Verified' : 'unverified'} observed={verifiedAt} />
        <ReadinessItem label="Execution status" source="GET /execution · broker state" state={executionState} result={executionData ? `${executionData.connected ? 'Connected' : 'Disconnected'} · ${executionData.open_positions_count} open positions` : executionState.toLowerCase()} observed={null} />
        <ReadinessItem label="Observation-daemon heartbeat" source="GET /observation/health" state={healthState} result={health ? health.running && health.healthy ? 'Healthy' : 'Not healthy' : healthState.toLowerCase()} observed={health?.updated_at} />
        <ReadinessItem label="Notification channel" source="GET /notifications/status · configuration" state={notificationState} result={notificationSummary ?? notificationState.toLowerCase()} observed={notificationData?.observed_at ?? null} />
      </ul>
      {brokerData?.broker_execution_enabled === true && <div className="workspace-live-action">
        <div>
          <strong>Demo execution</strong>
          <small>{canExecuteLiveCycle ? 'Ready to run one guarded cycle.' : 'Waiting for a fresh verified demo setup.'}</small>
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
        {liveExecution?.error && <p role="alert">{liveExecution.error}</p>}
      </div>}
    </Panel>

    <div className="workspace-grid workspace-primary">
      <Panel title="Decision trail" source="GET /monitoring/offline · offline assessment" state={monitoringState} observed={assessment?.observed_at} className="workspace-decision">
        {!assessment ? <div className="workspace-no-assessment"><p className="workspace-empty">No current assessment</p><div className="workspace-factors">{factors.map(name => <span key={name}>{name}: unavailable</span>)}</div></div> : <>
        <p className="workspace-note">Shared assessment-level timestamps: observed {formatTime(assessment.observed_at)} · candle close {formatTime(assessment.candle_close_time)} · expires {formatTime(assessment.expires_at)}. No per-stage timestamps are supplied.</p>
        <ol className="workspace-stages">
          <li><strong>Data freshness</strong><span>{value(assessment.data_freshness.status)}</span><small>{reasonText(assessment.data_freshness.reason_codes)}</small></li>
          <li><strong>Analysis</strong><span>{value(assessment.setup_state)}</span><small>{reasonText(assessment.reason_codes)}</small></li>
          <li><strong>Strategy score</strong><span>{assessment.confidence_score ?? 'unavailable'}</span><small>{reasonText(assessment.reason_codes)}</small>
            <div className="workspace-factors">{factors.map(name => {
              const factor = assessment.evidence.find(item => item.factor === name);
              return <span key={name}>{name}: {factor ? `${factor.score} / ${factor.maximum_score} · ${factor.assessment}` : 'unavailable'}</span>;
            })}</div>
          </li>
          <li><strong>Risk</strong><span>{value(assessment.risk_authorization.status)}</span><small>{reasonText(assessment.risk_authorization.reason_codes)}</small></li>
          <li><strong>Execution policy</strong><span>{value(assessment.execution_authorization.status)}</span><small>{reasonText(assessment.execution_authorization.reason_codes)}</small></li>
          <li><strong>Daily cap</strong><span>{capState === 'LIVE' ? `${caps.data!.items.length} instrument rows` : 'unavailable'}</span><small>GET /watchlist/cap-usage · observed {capState === 'LIVE' ? formatTime(caps.data?.observed_at) : 'unavailable'}</small></li>
          <li><strong>Broker</strong><span>{brokerData ? brokerData.active_broker : 'unavailable'}</span><small>GET /brokers/status · {brokerData ? brokerData.observation_state : 'unavailable'}</small></li>
        </ol></>}
        <div className="workspace-context"><strong>Separate broker context</strong><span>GET /brokers/status: {brokerState}</span><span>GET /execution/safety: {safetyState} · {safetyState === 'LIVE' ? value(safety.data?.execution_authorization) : 'unavailable'}</span><span>GET /risk: {riskState} · {riskState === 'LIVE' ? value(risk.data?.observation_status) : 'unavailable'}</span></div>
      </Panel>
      <Panel title="Market chart" source="GET /market/active-analysis · canonical snapshot" state={activeCandles ? activeAnalysisState : 'UNAVAILABLE'} className={`workspace-chart${activeCandles ? '' : ' workspace-chart-unavailable'}`}>
        {activeCandles ? <MarketChart
          symbol={activeCandles.symbol}
          timeframe={activeCandles.timeframe}
          candles={activeCandles.candles}
          signal={activeSignal}
          setup={activeSetup}
          priceDecimals={activeCandles.price_decimals}
          loading={activeAnalysis?.loading}
          error={activeAnalysis?.error}
          dataStatus={activeCandles.market_data_status}
        /> : <div className="workspace-chart-frame">
          <p className="workspace-empty">Active market analysis is unavailable.</p>
          <div className="workspace-chart-overlay" role="status">{activeAnalysis?.error ?? 'NO_MARKET_SNAPSHOT'}</div>
        </div>}
        <p className="workspace-source-time">Canonical snapshot: {activeCandles ? `${activeCandles.symbol} / ${activeCandles.timeframe}` : `${selectedSymbol} / ${selectedTimeframe}`} · strategy, setup, and candles share one observation.</p>
      </Panel>
    </div>

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
            : <p className="workspace-empty">{watchlistState === 'ERROR' ? `Watchlist error: ${value(watchlist.error)}` : `Watchlist ${watchlistState.toLowerCase()}`}</p>}
      </Panel>
      <Panel title="Instrument caps" source="GET /watchlist/cap-usage · DailyInstrumentTradeGuard" state={capState} observed={capState === 'LIVE' ? caps.data?.observed_at : null}>
        {capState === 'LIVE' && caps.data?.items.length === 0 ? <p className="workspace-empty">No cap rows returned.</p>
          : capState === 'LIVE' ? <ul className="workspace-list">{caps.data?.items.map((item, index) => <li key={`${item.scope}-${item.symbol}-${item.timeframe}-${index}`}><strong>{item.symbol} · {item.timeframe}</strong><span>{item.daily_count} / {item.daily_limit} today · {item.available ? 'available' : 'cap reached'}</span><small>Reset {formatTime(item.reset_at)}</small></li>)}</ul>
            : <p className="workspace-empty">{capState === 'ERROR' ? `Cap error: ${value(caps.error)}` : `Cap data ${capState.toLowerCase()}`}</p>}
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
      <Panel title="Notification channels" source="GET /notifications/status · configuration" state={notificationData ? notificationState : 'UNAVAILABLE'}>
        {notificationData ? <ul className="workspace-list">{notificationData.channels.map(channel => <li key={channel.channel}><strong>{channel.channel}</strong><span>{channel.state}</span><small>{channel.reason_codes.join(' · ')}</small></li>)}</ul> : <p>Notification status is unavailable.</p>}
      </Panel>
    </div>

    <button ref={aiLauncher} type="button" className="workspace-ai-launcher" onClick={() => setAiOpen(true)}>JQE AI <small>{assistantState}</small></button>
    {aiOpen && <div className="workspace-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closeAi(); }}>
      <aside className="workspace-ai-panel" role="dialog" aria-modal="true" aria-labelledby="workspace-ai-title">
        <button ref={aiClose} type="button" onClick={closeAi}>Close</button><p className="workspace-eyebrow">JQE AI · {assistantState}</p><h2 id="workspace-ai-title">Read-only evidence assistant</h2>
        <p>Explains the supplied Workspace evidence. It cannot approve risk, broker status or execution.</p>
        {assistantState !== 'READY' && <p role="status">{assistantStatus?.data?.reason_codes?.join(' · ') || assistantStatus?.error || 'Assistant unavailable.'}</p>}
        {aiAnswer && <p role="status">{aiAnswer}</p>}
        {aiError && <p role="alert">{aiError}</p>}
        {assistantState === 'READY' && <form onSubmit={event => { event.preventDefault(); void sendAssistantMessage(); }}>
          <input aria-label="Ask JQE AI" value={aiMessage} onChange={event => setAiMessage(event.target.value)} disabled={aiSending} placeholder="Ask about the current evidence" />
          <button type="submit" disabled={aiSending || !aiMessage.trim()}>{aiSending ? 'Asking…' : 'Ask'}</button>
        </form>}
      </aside></div>}
    {paletteOpen && <div className="workspace-dialog-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) closePalette(); }}>
      <div className="workspace-palette" role="dialog" aria-modal="true" aria-labelledby="workspace-palette-title">
        <h2 id="workspace-palette-title">Navigate JQE</h2><input ref={paletteInput} aria-label="Find page" value={query} onChange={event => setQuery(event.target.value)}
          onKeyDown={event => { if (event.key === 'Enter' && filteredDestinations[0]) navigate(filteredDestinations[0].tab); }} />
        <nav aria-label="Pages">{filteredDestinations.map(item => <button type="button" key={item.tab} onClick={() => navigate(item.tab)}>{item.label}</button>)}</nav>
        <button type="button" onClick={closePalette}>Close navigation</button>
      </div></div>}
  </main>;
};
