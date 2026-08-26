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
import { BacktestPage } from './pages/BacktestPage';
import { SystemPage } from './pages/SystemPage';
import { jqeApi } from './services/api';
import {
  SystemStatusResponse,
  MarketSummaryResponse,
  CandlesResponse,
  SignalResponse,
  RiskStatusResponse,
  ExecutionStateResponse,
  PerformanceSummaryResponse,
  ResourceState,
} from './types/api';
import { useInterval } from './hooks/useApi';
import { AlertTriangle, RefreshCw } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('XAUUSD');
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>('H1');

  type Resources = {
    system: ResourceState<SystemStatusResponse>;
    market: ResourceState<MarketSummaryResponse>;
    candles: ResourceState<CandlesResponse>;
    strategy: ResourceState<SignalResponse>;
    risk: ResourceState<RiskStatusResponse>;
    execution: ResourceState<ExecutionStateResponse>;
    performance: ResourceState<PerformanceSummaryResponse>;
  };
  const emptyResource = <T,>(): ResourceState<T> => ({
    data: null, loading: true, error: null, lastUpdated: null, stale: false,
  });
  const [resources, setResources] = useState<Resources>({
    system: emptyResource(), market: emptyResource(), candles: emptyResource(),
    strategy: emptyResource(), risk: emptyResource(), execution: emptyResource(),
    performance: emptyResource(),
  });
  const [lastRefreshAttempt, setLastRefreshAttempt] = useState<Date | null>(null);
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
    setResources(previous => Object.fromEntries(
      Object.entries(previous).map(([name, resource]) => [name, {
        ...resource,
        data: resetData && ['market', 'candles', 'strategy', 'risk'].includes(name) ? null : resource.data,
        loading: true,
        error: null,
        stale: resetData && ['market', 'candles', 'strategy', 'risk'].includes(name) ? false : resource.stale,
      }])
    ) as Resources);

    try {
      const results = await Promise.allSettled([
        jqeApi.getSystemStatus(controller.signal),
        jqeApi.getMarketSummary(selectedSymbol, selectedTimeframe, undefined, controller.signal),
        jqeApi.getMarketCandles(selectedSymbol, selectedTimeframe, 60, controller.signal),
        jqeApi.getStrategySignal(selectedSymbol, selectedTimeframe, undefined, controller.signal),
        jqeApi.getRiskStatus(selectedSymbol, selectedTimeframe, controller.signal),
        jqeApi.getExecutionState(controller.signal),
        jqeApi.getPerformanceSummary(controller.signal),
      ]);
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;

      const names: (keyof Resources)[] = ['system', 'market', 'candles', 'strategy', 'risk', 'execution', 'performance'];
      const updatedAt = new Date();
      setResources(previous => {
        const next = { ...previous };
        results.forEach((result, index) => {
          const name = names[index];
          const old = previous[name] as ResourceState<unknown>;
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
      const message = err instanceof Error ? err.message : 'API connection error';
      setResources(previous => Object.fromEntries(
        Object.entries(previous).map(([name, resource]) => [name, {
          ...resource, loading: false, error: message, stale: resource.data !== null,
        }])
      ) as Resources);
      setLastRefreshAttempt(new Date());
    } finally {
      if (requestId === requestIdRef.current) {
        inFlightRef.current = false;
      }
    }
  }, [selectedSymbol, selectedTimeframe]);

  // Initial fetch and symbol/timeframe reaction
  useEffect(() => {
    fetchAllData(true, true);
    return () => abortRef.current?.abort();
  }, [fetchAllData]);

  // Auto-refresh telemetry every 4 seconds
  useInterval(() => {
    fetchAllData(false, false);
  }, 4000);

  const systemStatus = resources.system.data;
  const marketSummary = resources.market.data;
  const candlesData = resources.candles.data;
  const signalData = resources.strategy.data;
  const riskData = resources.risk.data;
  const executionData = resources.execution.data;
  const performanceData = resources.performance.data;
  const loading = Object.values(resources).some(resource => resource.loading);
  const failedResources = Object.entries(resources).filter(([, resource]) => resource.error);
  const apiError = failedResources.length
    ? `Telemetry errors: ${failedResources.map(([name]) => name).join(', ')}. Prior values, when available, are marked stale.`
    : null;

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'overview':
        return (
          <OverviewPage
            systemStatus={systemStatus}
            marketSummary={marketSummary}
            candlesData={candlesData}
            signalData={signalData}
            riskData={riskData}
            executionData={executionData}
            performanceData={performanceData}
            loading={loading}
            selectedSymbol={selectedSymbol}
            selectedTimeframe={selectedTimeframe}
            telemetryStale={{ system: resources.system.stale, strategy: resources.strategy.stale, risk: resources.risk.stale }}
          />
        );
      case 'markets':
        return (
          <MarketsPage
            summary={marketSummary}
            candles={candlesData}
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            loading={loading}
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
      case 'performance':
        return <PerformancePage performance={performanceData} execution={executionData} loading={loading} currency={performanceData?.currency ?? undefined} />;
      case 'backtesting':
        return <BacktestPage />;
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
        openPositionsCount={executionData?.open_positions_count ?? 0}
        riskAllowed={riskData?.risk_allowed}
        riskStale={resources.risk.stale}
      />

      {/* Main Content Area */}
      <div className="main-content-wrapper">
        <Header
          systemStatus={systemStatus}
          loading={loading}
          telemetryStale={resources.system.stale}
          onRefresh={() => fetchAllData(true, false)}
          selectedSymbol={selectedSymbol}
          onSymbolChange={setSelectedSymbol}
          selectedTimeframe={selectedTimeframe}
          onTimeframeChange={setSelectedTimeframe}
        />

        {/* API Error Notification Banner */}
        {apiError && (
          <div
            style={{
              backgroundColor: 'var(--quant-amber-subtle)',
              borderBottom: '1px solid rgba(255, 171, 0, 0.3)',
              padding: '6px 16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              fontSize: '11.5px',
              fontFamily: 'var(--font-mono)',
              color: 'var(--quant-amber)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={14} />
              <span>{apiError}{lastRefreshAttempt ? ` Last refresh attempt: ${lastRefreshAttempt.toLocaleTimeString('en-GB')}.` : ''}</span>
            </div>
            <button
              onClick={() => fetchAllData(true, false)}
              className="btn-quant"
              style={{ fontSize: '10px', padding: '2px 6px', height: '20px' }}
            >
              <RefreshCw size={10} /> RETRY
            </button>
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', padding: '5px 16px', borderBottom: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-subtle)', fontFamily: 'var(--font-mono)', fontSize: '9.5px' }}>
          {Object.entries(resources).map(([name, resource]) => {
            const state = resource.loading && !resource.data ? 'LOADING'
              : resource.error && !resource.data ? 'ERROR'
              : resource.stale ? 'STALE'
              : resource.data ? 'FRESH'
              : 'UNAVAILABLE';
            const color = state === 'FRESH' ? 'var(--quant-green)'
              : state === 'STALE' ? 'var(--quant-amber)'
              : state === 'ERROR' ? 'var(--quant-red)'
              : 'var(--text-muted)';
            return (
              <span key={name} title={resource.error || (resource.lastUpdated ? `Updated ${resource.lastUpdated.toLocaleString('en-GB')}` : 'Never updated')} style={{ color }}>
                {name.toUpperCase()}: {state}{resource.lastUpdated ? ` @ ${resource.lastUpdated.toLocaleTimeString('en-GB')}` : ''}
              </span>
            );
          })}
        </div>

        {/* Dynamic Page View */}
        {renderActiveTab()}
      </div>
    </div>
  );
};
