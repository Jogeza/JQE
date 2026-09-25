import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Header } from './components/Header';
import { Sidebar, TabType } from './components/Sidebar';
import { OverviewPage } from './pages/OverviewPage';
import { MarketsPage } from './pages/MarketsPage';
import { PositionsPage } from './pages/PositionsPage';
import { TradesPage } from './pages/TradesPage';
import { StrategyPage } from './pages/StrategyPage';
import { RiskPage } from './pages/RiskPage';
import { PerformancePage } from './pages/PerformancePage';
import { ResearchPage } from './pages/ResearchPage';
import { SystemPage } from './pages/SystemPage';
import { BrokersPage } from './pages/BrokersPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { WorkspacePage } from './pages/WorkspacePage';
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
} from './types/api';
import { useInterval } from './hooks/useApi';
import { deriveTelemetryLifecycle, isOlderAssessment, validateOfflineTelemetry } from './services/telemetryLifecycle';
import { AlertTriangle, RefreshCw } from 'lucide-react';

const workspaceProfile = [
  'brokerStatus', 'safety', 'risk', 'monitoring', 'observationHealth',
  'watchlist', 'watchlistCapUsage', 'execution', 'activeAnalysis', 'assistantStatus', 'notificationStatus',
] as const;
const legacyProfile = [
  'system', 'market', 'candles', 'strategy', 'risk', 'execution', 'safety',
  'performance', 'recovery', 'paperRuntime', 'paperDiagnostics', 'monitoring',
  'observationHealth', 'brokerStatus', 'watchlist', 'watchlistCapUsage',
] as const;

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('workspace');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('');
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('');

  type Resources = {
    system: ResourceState<SystemStatusResponse>;
    market: ResourceState<MarketSummaryResponse>;
    candles: ResourceState<CandlesResponse>;
    strategy: ResourceState<SignalResponse>;
    risk: ResourceState<RiskStatusResponse>;
    execution: ResourceState<ExecutionStateResponse>;
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
  const [lastRefreshAttempt, setLastRefreshAttempt] = useState<Date | null>(null);
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
          stale: clear ? false : resource.data !== null || resource.stale,
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
      setLastRefreshAttempt(updatedAt);
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
      setLastRefreshAttempt(new Date());
    } finally {
      if (requestId === requestIdRef.current) {
        inFlightRef.current = false;
      }
    }
  }, [activeTab, selectedSymbol, selectedTimeframe]);

  const handleSelectBroker = useCallback(async (broker: string) => {
    await jqeApi.selectBroker(broker, 'dashboard');
    await fetchAllData(true, false);
  }, [fetchAllData]);

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
  const displaySymbol = selectedSymbol || systemStatus?.default_symbol || 'R_75';
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

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'workspace':
        return <WorkspacePage
          broker={resources.brokerStatus}
          safety={resources.safety}
          risk={resources.risk}
          monitoring={resources.monitoring}
          observationHealth={resources.observationHealth}
          watchlist={resources.watchlist}
          caps={resources.watchlistCapUsage}
          execution={resources.execution}
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
      case 'brokers':
        return (
          <BrokersPage
            brokerStatus={resources.brokerStatus.data}
            loading={resources.brokerStatus.loading}
            onRefresh={() => fetchAllData(true, false)}
            onSelectBroker={handleSelectBroker}
          />
        );
      case 'performance':
        return <PerformancePage performance={performanceData} execution={executionData} loading={loading} currency={performanceData?.currency ?? undefined} />;
      case 'backtesting':
        return <ResearchPage />;
      case 'system':
      case 'settings':
        return <SystemPage systemStatus={systemStatus} loading={loading} />;
      default:
        return null;
    }
  };

  return (
    <div className="app-container">
      {/* Navigation Sidebar */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={setActiveTab}
        openPositionsCount={activeTab === 'workspace' ? undefined : executionData?.open_positions_count ?? 0}
        riskAllowed={riskData?.risk_allowed}
        riskStale={resources.risk.stale}
      />

      {/* Main Content Area */}
      <div className="main-content-wrapper">
        {activeTab !== 'workspace' && <Header
          pageTitle={
            activeTab === 'backtesting'
              ? 'Research'
              : activeTab === 'risk'
              ? 'Risk Control'
              : activeTab === 'brokers'
              ? 'Brokers & Gateways'
              : activeTab === 'watchlist'
              ? 'Watchlist & Caps'
              : activeTab.charAt(0).toUpperCase() + activeTab.slice(1)
          }
          systemStatus={systemStatus}
          loading={loading}
          telemetryStale={resources.system.stale}
          onRefresh={() => fetchAllData(true, false)}
          selectedSymbol={displaySymbol}
          onSymbolChange={setSelectedSymbol}
          selectedTimeframe={displayTimeframe}
          onTimeframeChange={setSelectedTimeframe}
          brokerStatus={resources.brokerStatus.data}
          onSelectBroker={handleSelectBroker}
        />}

        <div className="offline-simulation-banner" role="status">
          {resources.brokerStatus.data?.broker_execution_enabled === true && resources.brokerStatus.data.active_broker !== 'simulation'
            ? 'DEMO EXECUTION — BROKER ORDERS ENABLED'
            : 'OFFLINE SIMULATION — NO BROKER ORDERS'}
          <span>{resources.brokerStatus.data?.active_broker && resources.brokerStatus.data.active_broker !== 'simulation'
            ? ` ${resources.brokerStatus.data.active_broker} · ${resources.brokerStatus.data.observation_state}`
            : telemetryLifecycle.snapshot ? ` ${telemetryLifecycle.snapshot.environment} · ${telemetryLifecycle.snapshot.simulation_submissions.account_scope}` : ` ${telemetryLifecycle.state}`}</span>
        </div>

        {/* API Error Notification Banner */}
        {apiError && (
          <div
            style={{
              backgroundColor: 'var(--quant-amber-subtle)',
              borderBottom: '1px solid var(--quant-amber-border)',
              padding: '5px 14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              color: 'var(--quant-amber)',
              flexShrink: 0,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={13} />
              <span>{apiError}{lastRefreshAttempt ? ` Last refresh attempt: ${lastRefreshAttempt.toLocaleTimeString('en-GB')}.` : ''}</span>
            </div>
            <button
              onClick={() => fetchAllData(true, false)}
              className="btn-quant"
              style={{ fontSize: '9.5px', padding: '1px 6px', height: '18px' }}
            >
              <RefreshCw size={9} /> RETRY
            </button>
          </div>
        )}

        {/* Telemetry Status Ribbon / System Health Rail */}
        {activeTab !== 'workspace' && <div className="telemetry-ribbon"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
            flexWrap: 'wrap',
            padding: '3px 16px',
            borderBottom: '1px solid var(--border-dark)',
            backgroundColor: 'var(--bg-dark-status)',
            fontSize: '9.5px',
            flexShrink: 0,
            minHeight: '24px',
          }}
        >
          {Object.entries(resources).map(([name, resource]) => {
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
        </div>}

        {/* Dynamic Page View */}
        {renderActiveTab()}
      </div>
    </div>
  );
};
