import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from './components/Header';
import { NotificationCenter } from './components/NotificationCenter';
import { Sidebar, TabType } from './components/Sidebar';
import { DemoSupervisorBadge } from './components/DecisionJournal';
import { OverviewPage } from './pages/OverviewPage';
import { MarketsPage } from './pages/MarketsPage';
import { PositionsPage } from './pages/PositionsPage';
import { TradesPage } from './pages/TradesPage';
import { StrategyPage } from './pages/StrategyPage';
import { RiskPage } from './pages/RiskPage';
import { PerformancePage } from './pages/PerformancePage';
import { ResearchPage } from './pages/ResearchPage';
import { SystemPage } from './pages/SystemPage';
import { SettingsPage } from './pages/SettingsPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { WorkspacePage } from './pages/WorkspacePage';
import { SyntXMarketsPage } from './pages/SyntXMarketsPage';
import { jqeApi } from './services/api';
import {
  SystemStatusResponse,
  MarketSummaryResponse,
  CandlesResponse,
  SignalResponse,
  RiskStatusResponse,
  ExecutionStateResponse,
  ExecutionSafetyResponse,
  PerformanceSummaryResponse,
  RecoveryDiagnosticsResponse,
  PaperRuntimeStatusResponse,
  PaperDiagnosticsResponse,
  MarketSetup,
  ActiveMarketAnalysisResponse,
  ResourceState,
  OfflineMonitoringResponse,
  ObservationHealthResponse,
  BrokerStatusResponse,
  WatchlistResponse,
  WatchlistCapUsageResponse,
  AssistantStatusResponse,
  NotificationStatusResponse,
  LiveExecutionResponse,
  TerminalObservationResponse,
} from './types/api';
import { useInterval } from './hooks/useApi';
import { deriveTelemetryLifecycle, isOlderAssessment, validateOfflineTelemetry } from './services/telemetryLifecycle';
import { RefreshCw } from 'lucide-react';

const workspaceProfile = [
  'brokerStatus', 'safety', 'risk', 'monitoring', 'observationHealth',
  'watchlist', 'watchlistCapUsage', 'execution', 'activeAnalysis', 'assistantStatus', 'notificationStatus',
  'terminalObservation',
] as const;
const legacyProfile = [
  'system', 'market', 'candles', 'strategy', 'risk', 'execution', 'safety',
  'performance', 'recovery', 'paperRuntime', 'paperDiagnostics', 'monitoring',
  'observationHealth', 'brokerStatus', 'watchlist', 'watchlistCapUsage',
  'notificationStatus',
  'assistantStatus',
] as const;

export const App: React.FC<{ authenticated?: boolean; workstation?: boolean; onSignOut?: () => void; onAdmin?: () => void }> = ({ authenticated = false, workstation = false, onSignOut, onAdmin }) => {
  const [activeTab, setActiveTab] = useState<TabType>('workspace');
  const [siteTheme, setSiteTheme] = useState<'light' | 'dark'>(() => {
    try { return window.localStorage.getItem('jqe-site-theme') === 'dark' ? 'dark' : 'light'; }
    catch { return 'light'; }
  });
  const toggleSiteTheme = () => setSiteTheme(current => {
    const next = current === 'dark' ? 'light' : 'dark';
    try { window.localStorage.setItem('jqe-site-theme', next); } catch { /* storage unavailable */ }
    return next;
  });
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('');

  type Resources = {
    system: ResourceState<SystemStatusResponse>;
    market: ResourceState<MarketSummaryResponse>;
    candles: ResourceState<CandlesResponse>;
    strategy: ResourceState<SignalResponse>;
    risk: ResourceState<RiskStatusResponse>;
    execution: ResourceState<ExecutionStateResponse>;
    terminalObservation: ResourceState<TerminalObservationResponse>;
    safety: ResourceState<ExecutionSafetyResponse>;
    performance: ResourceState<PerformanceSummaryResponse>;
    recovery: ResourceState<RecoveryDiagnosticsResponse>;
    paperRuntime: ResourceState<PaperRuntimeStatusResponse>;
    paperDiagnostics: ResourceState<PaperDiagnosticsResponse>;
    setup: ResourceState<MarketSetup>;
    activeAnalysis: ResourceState<ActiveMarketAnalysisResponse>;
    monitoring: ResourceState<OfflineMonitoringResponse>;
    observationHealth: ResourceState<ObservationHealthResponse>;
    brokerStatus: ResourceState<BrokerStatusResponse>;
    watchlist: ResourceState<WatchlistResponse>;
    watchlistCapUsage: ResourceState<WatchlistCapUsageResponse>;
    assistantStatus: ResourceState<AssistantStatusResponse>;
    notificationStatus: ResourceState<NotificationStatusResponse>;
  };
  const emptyResource = <T,>(): ResourceState<T> => ({
    data: null, loading: true, error: null, lastUpdated: null, stale: false,
  });
  const [resources, setResources] = useState<Resources>({
    system: emptyResource(), market: emptyResource(), candles: emptyResource(),
    strategy: emptyResource(), risk: emptyResource(), execution: emptyResource(),
    terminalObservation: emptyResource(),
    safety: emptyResource(), performance: emptyResource(), recovery: emptyResource(),
    paperRuntime: emptyResource(), paperDiagnostics: emptyResource(),
    setup: emptyResource(),
    activeAnalysis: emptyResource(),
    monitoring: emptyResource(),
    observationHealth: emptyResource(),
    brokerStatus: emptyResource(),
    watchlist: emptyResource(),
    watchlistCapUsage: emptyResource(),
    assistantStatus: emptyResource(),
    notificationStatus: emptyResource(),
  });
  const [lastSuccessfulContact, setLastSuccessfulContact] = useState<Date | null>(null);
  const [lifecycleNow, setLifecycleNow] = useState(() => new Date());
  const [monitoringValidationError, setMonitoringValidationError] = useState<string | null>(null);
  const [liveExecution, setLiveExecution] = useState<{
    loading: boolean; result: LiveExecutionResponse | null; error: string | null;
  }>({ loading: false, result: null, error: null });
  const requestIdRef = useRef(0);
  const inFlightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchAllData = useCallback(async (replaceInFlight = false, resetData = false) => {
    if (inFlightRef.current && !replaceInFlight) return;
    if (replaceInFlight) abortRef.current?.abort();
    const requestId = ++requestIdRef.current;
    const controller = new AbortController();
    abortRef.current = controller;
    inFlightRef.current = true;
    const requestedSymbol = selectedSymbol;
    const requestedTimeframe = selectedTimeframe;
    const names: readonly (keyof Resources)[] = activeTab === 'workspace' ? workspaceProfile : legacyProfile;
    const requestFor = (name: keyof Resources): Promise<unknown> => {
      switch (name) {
        case 'system': return jqeApi.getSystemStatus(controller.signal);
        case 'market': return jqeApi.getMarketSummary(requestedSymbol, requestedTimeframe, undefined, controller.signal);
        case 'candles': return jqeApi.getMarketCandles(requestedSymbol, requestedTimeframe, 60, controller.signal);
        case 'strategy': return jqeApi.getStrategySignal(requestedSymbol, requestedTimeframe, undefined, controller.signal);
        case 'risk': return jqeApi.getRiskStatus(requestedSymbol, requestedTimeframe, controller.signal);
        case 'execution': return jqeApi.getExecutionState(controller.signal);
          case 'terminalObservation': return jqeApi.getTerminalObservation(requestedSymbol, requestedTimeframe, controller.signal);
        case 'safety': return jqeApi.getExecutionSafety(controller.signal);
        case 'performance': return jqeApi.getPerformanceSummary(controller.signal);
        case 'recovery': return jqeApi.getRecoveryDiagnostics(controller.signal);
        case 'paperRuntime': return jqeApi.getPaperRuntimeStatus(controller.signal);
        case 'paperDiagnostics': return jqeApi.getPaperDiagnostics(controller.signal);
        case 'monitoring': return jqeApi.getOfflineMonitoring(controller.signal);
        case 'observationHealth': return jqeApi.getObservationHealth(controller.signal);
        case 'brokerStatus': return jqeApi.getBrokerStatus(controller.signal);
        case 'watchlist': return jqeApi.getWatchlist(controller.signal);
        case 'watchlistCapUsage': return jqeApi.getWatchlistCapUsage(undefined, controller.signal);
        case 'activeAnalysis': return jqeApi.getActiveMarketAnalysis(requestedSymbol, requestedTimeframe, undefined, controller.signal);
        case 'assistantStatus': return jqeApi.getAssistantStatus(controller.signal);
        case 'notificationStatus': return jqeApi.getNotificationStatus(controller.signal);
        default: throw new Error(`No polling request for ${name}`);
      }
    };
    setResources(previous => {
      const next = { ...previous };
      names.forEach(name => {
        const resource = previous[name] as ResourceState<unknown>;
        const clear = resetData && ['market', 'candles', 'strategy', 'risk', 'setup'].includes(name);
        next[name] = {
          ...resource, data: clear ? null : resource.data, loading: true,
          stale: clear ? false : resource.stale,
        } as never;
      });
      return next;
    });

    try {
      const results = await Promise.allSettled(names.map(requestFor));
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;
      if (selectedSymbol !== requestedSymbol || selectedTimeframe !== requestedTimeframe) return;

      const updatedAt = new Date();
      setResources(previous => {
        const next = { ...previous };
        results.forEach((result, index) => {
          const name = names[index];
          const old = previous[name] as ResourceState<unknown>;
          if (result.status === 'rejected' && result.reason?.name === 'AbortError') {
            next[name] = { ...old, loading: false } as never;
            return;
          }
          if (name === 'monitoring' && result.status === 'fulfilled') {
            try {
              const validated = validateOfflineTelemetry(result.value);
              if (isOlderAssessment(previous.monitoring.data, validated)) {
                next.monitoring = { ...previous.monitoring, loading: false, error: null };
                return;
              }
              next.monitoring = { data: validated, loading: false, error: null, lastUpdated: updatedAt, stale: false };
              next.setup = { data: validated.assessment, loading: false, error: null, lastUpdated: updatedAt, stale: false };
              setLastSuccessfulContact(updatedAt);
              setMonitoringValidationError(null);
              return;
            } catch (error) {
              const message = error instanceof Error ? error.message : 'MALFORMED_TELEMETRY';
              next.monitoring = { data: null, loading: false, error: message, lastUpdated: previous.monitoring.lastUpdated, stale: false };
              next.setup = { data: null, loading: false, error: message, lastUpdated: previous.setup.lastUpdated, stale: false };
              setMonitoringValidationError(message);
              return;
            }
          }
          next[name] = (result.status === 'fulfilled'
            ? { data: result.value, loading: false, error: null, lastUpdated: updatedAt, stale: false }
            : {
                ...old,
                loading: false,
                error: result.reason instanceof Error ? result.reason.message : String(result.reason),
                stale: old.data !== null,
              }) as never;
        });
        return next;
      });
    } catch (err) {
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;
      if (err instanceof Error && err.name === 'AbortError') return;
      const message = err instanceof Error ? err.message : 'API connection error';
      setResources(previous => {
        const next = { ...previous };
        names.forEach(name => {
          const resource = previous[name] as ResourceState<unknown>;
          next[name] = { ...resource, loading: false, error: message, stale: resource.data !== null } as never;
        });
        return next;
      });
      } finally {
      if (requestId === requestIdRef.current) {
        inFlightRef.current = false;
      }
    }
  }, [activeTab, selectedSymbol, selectedTimeframe]);

  const handleExecuteLiveCycle = useCallback(async () => {
    if (liveExecution.loading) return;
    setLiveExecution({ loading: true, result: null, error: null });
    try {
      const result = await jqeApi.executeLiveCycle();
      setLiveExecution({ loading: false, result, error: null });
      await fetchAllData(true, false);
    } catch (error) {
      setLiveExecution({
        loading: false,
        result: null,
        error: error instanceof Error ? error.message : 'Demo execution failed',
      });
    }
  }, [fetchAllData, liveExecution.loading]);

  // Initial fetch and symbol/timeframe reaction
  useEffect(() => {
    fetchAllData(true, true);
    return () => abortRef.current?.abort();
  }, [fetchAllData]);

  // Auto-refresh telemetry every 4 seconds
  useInterval(() => {
    fetchAllData(false, false);
  }, 4000);
  useInterval(() => setLifecycleNow(new Date()), 1000);

  const systemStatus = resources.system.data;
  const displaySymbol = selectedSymbol || systemStatus?.default_symbol || 'FX Vol 20';
  const displayTimeframe = selectedTimeframe || systemStatus?.default_timeframe || 'M5';
  const marketSummary = resources.market.data;
  const candlesData = resources.candles.data;
  const signalData = resources.strategy.data;
  const riskData = resources.risk.data;
  const executionData = resources.execution.data;
  const safetyData = resources.safety.data;
  const performanceData = resources.performance.data;
  const recoveryData = resources.recovery.data;
  const paperRuntimeData = resources.paperRuntime.data;
  const paperDiagnosticsData = resources.paperDiagnostics.data;
  const setupData = resources.setup.data;
  const monitoringData = resources.monitoring.data;
  const derivedTelemetryLifecycle = deriveTelemetryLifecycle({
    snapshot: monitoringData,
    connected: resources.monitoring.error === null,
    loading: resources.monitoring.loading,
    lastSuccessfulContact,
    now: lifecycleNow,
    validationError: monitoringValidationError,
  });
  const telemetryLifecycle = resources.monitoring.loading && monitoringData && derivedTelemetryLifecycle.state === 'LIVE'
    ? { ...derivedTelemetryLifecycle, state: 'STALE' as const, reason: 'Refreshing retained telemetry' }
    : derivedTelemetryLifecycle;
  const activeProfile = activeTab === 'workspace' ? workspaceProfile : legacyProfile;
  const loading = activeProfile.some(name => resources[name].loading);
  const failedResources = activeProfile.filter(name => resources[name].error);
  const apiError = failedResources.length
    ? `Telemetry errors: ${failedResources.join(', ')}. Prior values, when available, are marked stale.`
    : null;
  const feedEntries = Object.entries(resources);
  const feedIssues = feedEntries.filter(([, resource]) => resource.error || (resource.stale && !resource.loading) || !resource.data).length;

  const renderWorkspace = (configurationOnly = false) => {
    return <WorkspacePage configurationOnly={configurationOnly} hosted={authenticated}
          broker={resources.brokerStatus}
          safety={resources.safety}
          risk={resources.risk}
          monitoring={resources.monitoring}
          observationHealth={resources.observationHealth}
          watchlist={resources.watchlist}
          caps={resources.watchlistCapUsage}
          execution={resources.execution}
                    terminalObservation={resources.terminalObservation}
          activeAnalysis={resources.activeAnalysis}
          assistantStatus={resources.assistantStatus}
          notificationStatus={resources.notificationStatus}
          liveExecution={liveExecution}
          onExecuteLiveCycle={handleExecuteLiveCycle}
          selectedSymbol={displaySymbol}
          selectedTimeframe={displayTimeframe}
          onMarketChange={(symbol, timeframe) => {
            setSelectedSymbol(symbol);
            setSelectedTimeframe(timeframe);
          }}
          lifecycle={telemetryLifecycle}
          onNavigate={setActiveTab}
        />;
  };

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'workspace':
        return renderWorkspace();
      case 'overview':
        return (
          <OverviewPage
            systemStatus={systemStatus}
            marketSummary={marketSummary}
            candlesData={candlesData}
            signalData={signalData}
            riskData={riskData}
            executionData={executionData}
            safetyData={safetyData}
            safetyUnavailable={resources.safety.error !== null}
            safetyStale={resources.safety.stale}
            performanceData={performanceData}
            recoveryData={recoveryData}
            recoveryUnavailable={resources.recovery.error !== null}
            recoveryStale={resources.recovery.stale}
            paperRuntimeData={paperRuntimeData}
            paperRuntimeUnavailable={resources.paperRuntime.error !== null}
            paperDiagnosticsData={paperDiagnosticsData}
            paperDiagnosticsUnavailable={resources.paperDiagnostics.error !== null}
            paperDiagnosticsStale={resources.paperDiagnostics.stale}
            setupData={setupData}
            setupLoading={resources.setup.loading}
            setupStale={resources.setup.stale}
            monitoringData={monitoringData}
            backendOffline={resources.monitoring.error !== null && monitoringData === null}
            telemetryLifecycle={telemetryLifecycle}
            onPaperRecorded={() => fetchAllData(true, false)}
            loading={loading}
            selectedSymbol={displaySymbol}
            selectedTimeframe={displayTimeframe}
            candleError={resources.candles.error}
            telemetryStale={{ system: resources.system.stale, strategy: resources.strategy.stale, risk: resources.risk.stale }}
            brokerStatus={resources.brokerStatus.data}
          />
        );
      case 'markets':
        return (
          <MarketsPage
            summary={marketSummary}
            candles={candlesData}
            symbol={displaySymbol}
            timeframe={displayTimeframe}
            loading={loading}
            signal={signalData}
            candleError={resources.candles.error}
          />
        );
      case 'syntx':
        return (
          <SyntXMarketsPage
            onSelectSymbol={(sym, tf) => {
              setSelectedSymbol(sym);
              if (tf) setSelectedTimeframe(tf);
            }}
          />
        );
      case 'positions':
        return <PositionsPage execution={executionData} loading={loading} currency={executionData?.currency} />;
      case 'trades':
        return <TradesPage execution={executionData} loading={loading} currency={executionData?.currency} />;
      case 'strategy':
        return <StrategyPage signal={signalData} loading={resources.strategy.loading} stale={resources.strategy.stale} />;
      case 'risk':
        return <RiskPage risk={riskData} loading={resources.risk.loading} brokerConnected={systemStatus?.broker_connected} stale={resources.risk.stale || resources.system.stale} />;
      case 'watchlist':
        return (
          <WatchlistPage
            watchlist={resources.watchlist.data?.items}
            capUsage={resources.watchlistCapUsage.data?.items}
            loading={resources.watchlist.loading || resources.watchlistCapUsage.loading}
            onRefresh={() => fetchAllData(true, false)}
          />
        );
      case 'performance':
        return <PerformancePage performance={performanceData} execution={executionData} loading={loading} currency={performanceData?.currency ?? undefined} />;
      case 'backtesting':
        return <ResearchPage />;
      case 'system':
        return <SystemPage systemStatus={systemStatus} loading={loading} />;
      case 'settings':
        return <div className="settings-composite-view"><SettingsPage assistant={resources.assistantStatus} notifications={resources.notificationStatus} broker={resources.brokerStatus} onNavigate={setActiveTab} />{renderWorkspace(true)}</div>;
      default:
        return null;
    }
  };

  const headerActions = <div className="compact-header-actions">          <button type="button" className="workspace-refresh" aria-label="Retry data refresh" onClick={() => fetchAllData(true, false)}><RefreshCw size={15} /></button>
          <NotificationCenter market={resources.activeAnalysis} notifications={resources.notificationStatus} safety={resources.safety} broker={resources.brokerStatus} apiError={apiError}
            resourceErrors={[...activeProfile.filter(name => resources[name].error).map(name => ({ title: name, detail: resources[name].error! })), ...(liveExecution.error ? [{ title: 'Demo cycle', detail: liveExecution.error }] : [])]}
            hosted={authenticated} /></div>;
  const menuContent = <div className="header-menu-content">          {(workstation || authenticated) && <DemoSupervisorBadge />}
          <span className="workspace-execution-status" role="status">Observation API · orders disabled</span>
              {onAdmin && <button type="button" className="workspace-account-action" onClick={onAdmin}>Admin</button>}
          {onSignOut && <button type="button" className="workspace-account-action" onClick={onSignOut}>Sign out</button>}</div>;

  return (
    <div className="app-container" data-theme={siteTheme}>
      {/* Navigation Sidebar */}
      <Sidebar
        authenticated={authenticated}
        headerActions={headerActions}
        menuContent={menuContent}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        openPositionsCount={activeTab === 'workspace' ? undefined : executionData?.open_positions_count ?? 0}
        riskAllowed={riskData?.risk_allowed}
        riskStale={resources.risk.stale}
        siteTheme={siteTheme}
        onToggleTheme={toggleSiteTheme}
      />

      {/* Main Content Area */}
      <div className="main-content-wrapper" key={siteTheme}>
        <div className="desktop-top-actions">
          {activeTab === 'workspace' && <strong>Workspace</strong>}
          {headerActions}
          <details className="header-account-menu"><summary>Menu</summary>{menuContent}</details>
        </div>
        {activeTab !== 'workspace' && <Header
          pageTitle={
            activeTab === 'backtesting'
              ? 'Research'
              : activeTab === 'trades'
              ? 'Journal'
              : activeTab === 'risk'
              ? 'Risk Control'
              : activeTab === 'watchlist'
              ? 'Watchlist & Caps'
              : activeTab === 'syntx'
              ? 'SyntX Markets'
              : activeTab.charAt(0).toUpperCase() + activeTab.slice(1)
          }
          systemStatus={systemStatus}
          loading={loading}
          telemetryStale={resources.system.stale && !resources.system.loading}
          onRefresh={() => fetchAllData(true, false)}
          selectedSymbol={displaySymbol}
          onSymbolChange={setSelectedSymbol}
          selectedTimeframe={displayTimeframe}
          onTimeframeChange={setSelectedTimeframe}
        />}



        {/* Telemetry Status Ribbon / System Health Rail */}
        {activeTab !== 'workspace' && <details className="telemetry-ribbon">
          <summary>Data feeds · {feedEntries.length - feedIssues} current · {feedIssues} need attention</summary>
          <div className="telemetry-ribbon-feeds">
          {feedEntries.map(([name, resource]) => {
            const state = resource.loading && !resource.data ? 'UNAVAILABLE'
              : resource.error && !resource.data ? 'OFFLINE'
              : resource.stale ? 'STALE'
              : resource.data ? 'FRESH'
              : 'UNAVAILABLE';
            const color = state === 'FRESH' ? 'var(--status-green)'
              : state === 'STALE' ? 'var(--quant-amber)'
              : state === 'OFFLINE' ? 'var(--quant-red)'
              : 'var(--text-dark-muted)';
            const dotClass = state === 'FRESH' ? 'status-dot-green'
              : state === 'STALE' ? 'status-dot-amber'
              : state === 'OFFLINE' ? 'status-dot-red'
              : '';
            return (
              <span
                key={name}
                title={resource.error || (resource.lastUpdated ? `Updated ${resource.lastUpdated.toLocaleString('en-GB')}` : 'Never updated')}
                style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}
              >
                <span className={`status-dot ${dotClass}`} style={{ width: '3.5px', height: '3.5px' }} />
                <span style={{ fontFamily: 'var(--font-sans)', fontSize: '10px', fontWeight: 600, color: 'var(--text-dark-secondary)' }}>
                  {name.toUpperCase()}
                </span>
                <span className="font-mono" style={{ fontSize: '9px', fontWeight: 600, color }}>
                  {state}
                </span>
                {resource.lastUpdated && (
                  <span style={{ color: 'var(--text-dark-dim)', fontFamily: 'var(--font-mono)', fontSize: '8.5px', opacity: 0.75 }}>
                    @{resource.lastUpdated.toLocaleTimeString('en-GB')}
                  </span>
                )}
              </span>
            );
          })}
          </div>
        </details>}

        {/* Dynamic Page View */}
        {renderActiveTab()}
      </div>
    </div>
  );
};
