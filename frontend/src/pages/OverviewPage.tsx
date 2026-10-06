import React from 'react';
import { MetricCard } from '../components/MetricCard';
import { EngineStatusPanel } from '../components/EngineStatusPanel';
import { RiskPanel } from '../components/RiskPanel';
import { PositionsTable } from '../components/PositionsTable';
import { RecentTradesTable } from '../components/RecentTradesTable';
import { MarketChart } from '../components/MarketChart';
import { StrategySignalPanel } from '../components/StrategySignalPanel';
import { PerformanceSection } from '../components/PerformanceSection';
import { RecoveryPanel } from '../components/RecoveryPanel';
import { ExecutionSafetyPanel } from '../components/ExecutionSafetyPanel';
import { PaperRuntimePanel } from '../components/PaperRuntimePanel';
import { PaperDiagnosticsPanel } from '../components/PaperDiagnosticsPanel';
import { MarketSetupPanel } from '../components/MarketSetupPanel';
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
} from '../types/api';
import { canonicalSignalFromAssessment, TelemetryLifecycle } from '../services/telemetryLifecycle';
import { formatMoney } from '../utils/format';

interface OverviewPageProps {
  systemStatus: SystemStatusResponse | null;
  marketSummary: MarketSummaryResponse | null;
  candlesData: CandlesResponse | null;
  signalData: SignalResponse | null;
  riskData: RiskStatusResponse | null;
  executionData: ExecutionStateResponse | null;
  safetyData: ExecutionSafetyResponse | null;
  safetyUnavailable: boolean;
  safetyStale: boolean;
  performanceData: PerformanceSummaryResponse | null;
  recoveryData: RecoveryDiagnosticsResponse | null;
  recoveryUnavailable: boolean;
  recoveryStale: boolean;
  paperRuntimeData: PaperRuntimeStatusResponse | null;
  paperRuntimeUnavailable: boolean;
  paperDiagnosticsData: PaperDiagnosticsResponse | null;
  paperDiagnosticsUnavailable: boolean;
  paperDiagnosticsStale: boolean;
  setupData: MarketSetup | null;
  setupLoading: boolean;
  setupStale: boolean;
  telemetryLifecycle: TelemetryLifecycle;
  onPaperRecorded: () => void;
  loading: boolean;
  selectedSymbol: string;
  selectedTimeframe: string;
  candleError: string | null;
  telemetryStale: { system: boolean; strategy: boolean; risk: boolean };
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  systemStatus,
  candlesData,
  signalData,
  riskData,
  executionData,
  safetyData,
  safetyUnavailable,
  safetyStale,
  performanceData,
  recoveryData,
  recoveryUnavailable,
  recoveryStale,
  paperRuntimeData,
  paperRuntimeUnavailable,
  paperDiagnosticsData,
  paperDiagnosticsUnavailable,
  paperDiagnosticsStale,
  setupData,
  setupLoading,
  setupStale,
  telemetryLifecycle,
  onPaperRecorded,
  loading,
  selectedSymbol,
  selectedTimeframe,
  candleError,
  telemetryStale,
}) => {
  const assessmentIsLive = telemetryLifecycle.state === 'LIVE';
  const assessmentIsStale = !assessmentIsLive;
  const canonicalSignal = canonicalSignalFromAssessment(telemetryLifecycle.assessment);
  const balance = riskData?.balance;
  const equity = riskData?.equity;
  const openPositions = executionData?.positions || [];
  const openPnL = openPositions.reduce((acc, p) => acc + (p.profit || 0), 0);
  const recentTrades = executionData?.recent_trades || [];
  const tradesToday = riskData?.daily_trades_count ?? 0;
  const dailyLoss = riskData?.daily_loss_percent ?? 0.0;
  const compatibleWinRate = setupData?.historical_win_rate;

  return (
    <div className="dashboard-page-container overview-page">
      <div className="editorial-heading">
        <div><span className="editorial-kicker">The market, in perspective</span><h1>Overview<span>.</span></h1></div>
        <p>{selectedSymbol} <span aria-hidden="true">/</span> {selectedTimeframe}<small>Account, market & system health</small></p>
      </div>

      <div className="grid-metrics">
        <MetricCard
          label="Account Equity"
          value={equity === undefined ? null : formatMoney(equity, riskData?.currency)}
          subtext={`Currency: ${riskData?.currency || '—'}`}
          badge={systemStatus?.broker?.toUpperCase() || 'UNKNOWN'}
          badgeType="cyan"
          loading={loading && !riskData}
        />

        <MetricCard
          label="Account Balance"
          value={balance === undefined ? null : formatMoney(balance, riskData?.currency)}
          subtext="Settled Capital Base"
          loading={loading && !riskData}
        />

        <MetricCard
          label="Daily Loss %"
          value={`${dailyLoss.toFixed(2)}%`}
          subtext={riskData ? `Max Cap: ${riskData.max_daily_loss.toFixed(1)}%` : 'Max Cap: —'}
          trend={dailyLoss > 0 ? 'down' : 'neutral'}
          badge={riskData ? (riskData.risk_allowed ? 'PERMITTED' : 'LOCKED') : 'UNKNOWN'}
          badgeType={riskData ? (riskData.risk_allowed ? 'green' : 'red') : 'neutral'}
          loading={loading && !riskData}
        />

        <MetricCard
          label="Open P&L"
          value={executionData ? formatMoney(openPnL, riskData?.currency, true) : null}
          subtext={executionData ? `${openPositions.length} Open Positions` : 'Positions unavailable'}
          trend={openPnL > 0 ? 'up' : openPnL < 0 ? 'down' : 'neutral'}
          loading={loading && !executionData}
        />

        <MetricCard
          label="Win Rate"
          value={compatibleWinRate?.status === 'AVAILABLE' && compatibleWinRate.win_rate_percent !== null ? `${compatibleWinRate.win_rate_percent}%` : 'Unavailable'}
          subtext={compatibleWinRate?.status === 'AVAILABLE' ? `${compatibleWinRate.sample_size} compatible OOS trades` : 'No compatible out-of-sample evidence'}
          loading={setupLoading && !setupData}
        />

        <MetricCard
          label="Trades Today"
          value={riskData ? tradesToday : null}
          subtext={riskData ? `Max Allowance: ${riskData.max_trades_daily}` : 'Max Allowance: —'}
          badge={riskData ? (tradesToday >= riskData.max_trades_daily ? 'CAPPED' : 'AVAILABLE') : 'UNKNOWN'}
          badgeType={riskData && tradesToday >= riskData.max_trades_daily ? 'amber' : 'neutral'}
          loading={loading && !riskData}
        />
      </div>

      {/* Dedicated Active Market Workstation: Chart and Analyst Panel side-by-side */}
      <div className="active-market-workstation">
        <MarketChart
          symbol={selectedSymbol}
          timeframe={selectedTimeframe}
          candles={candlesData?.candles || []}
          signal={signalData}
          setup={setupData}
          priceDecimals={candlesData?.price_decimals}
          loading={loading && !candlesData}
          error={candleError}
          dataStatus={candlesData?.market_data_status}
        />

        <MarketSetupPanel
          setup={setupData}
          loading={setupLoading}
          stale={setupStale || assessmentIsStale}
          onRecorded={onPaperRecorded}
        />
      </div>

      {/* Auxiliary & Diagnostic Workstation Grid: Left Strategy/Positions + Right Engine/Risk/Safety */}
      <details className="dashboard-details">
      <summary>Positions, execution safety and research diagnostics</summary>
      <div className="grid-two-col">
        {/* Left Column: Strategy Signals & Position Tables */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 0 }}>
          <StrategySignalPanel
            signal={canonicalSignal}
            loading={loading && !canonicalSignal}
            stale={assessmentIsStale}
          />

          <PositionsTable
            positions={openPositions}
            brokerName={systemStatus?.broker}
            loading={loading && !executionData}
            currency={executionData?.currency}
          />

          <RecentTradesTable
            trades={recentTrades}
            loading={loading && !executionData}
            currency={executionData?.currency}
            broker={executionData?.broker}
          />
        </div>

        {/* Right Column: Engine, Safety & Risk Telemetry */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 0 }}>
          <ExecutionSafetyPanel
            safety={safetyData}
            loading={loading && !safetyData}
            unavailable={safetyUnavailable}
            stale={safetyStale}
          />

          <PaperRuntimePanel
            runtime={paperRuntimeData}
            telegramStatus={systemStatus?.telegram_status}
            unavailable={paperRuntimeUnavailable}
          />

          <PaperDiagnosticsPanel
            diagnostics={paperDiagnosticsData}
            unavailable={paperDiagnosticsUnavailable}
            stale={paperDiagnosticsStale}
          />

          <RecoveryPanel
            recovery={recoveryData}
            loading={loading && !recoveryData}
            unavailable={recoveryUnavailable}
            stale={recoveryStale}
          />

          <EngineStatusPanel
            systemStatus={systemStatus}
            signal={signalData}
            risk={riskData}
            stale={telemetryStale}
          />

          <RiskPanel
            risk={riskData}
            loading={loading && !riskData}
            brokerConnected={systemStatus?.broker_connected}
            stale={telemetryStale.risk || telemetryStale.system}
          />

          <PerformanceSection
            performance={performanceData}
            trades={recentTrades}
            loading={loading && !performanceData}
            currency={performanceData?.currency ?? undefined}
          />
        </div>
      </div>
      </details>
    </div>
  );
};
