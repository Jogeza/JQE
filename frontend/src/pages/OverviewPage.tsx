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
  ResourceState,
  TerminalObservationResponse,
} from '../types/api';
import { canonicalSignalFromAssessment, TelemetryLifecycle } from '../services/telemetryLifecycle';
import { formatMoney } from '../utils/format';

interface OverviewPageProps {
  systemStatus: SystemStatusResponse | null;
  marketSummary: MarketSummaryResponse | null;
  candlesData: CandlesResponse | null;
  signalData: SignalResponse | null;
  riskData: RiskStatusResponse | null;
  terminalObservation: ResourceState<TerminalObservationResponse>;
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
  terminalObservation,
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
  const terminal = terminalObservation.data;
  const accountCurrent = !terminalObservation.error && !terminalObservation.stale
    && terminal?.state === 'CONNECTED' && terminal.environment === 'DEMO';
  const balance = accountCurrent ? terminal.balance : null;
  const equity = accountCurrent ? terminal.equity : null;
  const accountNote = accountCurrent
    ? `Terminal · ${terminal.currency || '—'} · ${new Date(terminal.observed_at).toLocaleTimeString()}`
    : 'Current terminal account unavailable';
  const openPositions = executionData?.positions || [];
  const openPnL = openPositions.reduce((acc, p) => acc + (p.profit || 0), 0);
  const recentTrades = executionData?.recent_trades || [];
  const tradesToday = riskData?.daily_trades_count ?? 0;
  const dailyLoss = riskData?.daily_loss_percent ?? 0.0;
  const riskEvidenceCurrent = !telemetryStale.risk && riskData?.observation_status === 'FRESH';
  const compatibleWinRate = setupData?.historical_win_rate;

  return (
    <div className="dashboard-page-container overview-page">
      <div className="editorial-heading">
        <div><h1>Home</h1></div>
        <p>{selectedSymbol} <span aria-hidden="true">/</span> {selectedTimeframe}</p>
      </div>

      <div className="grid-metrics">
        <MetricCard
          label="Equity"
          value={equity == null ? null : formatMoney(equity, terminal?.currency ?? undefined)}
          subtext={accountNote}
          badge={systemStatus?.broker?.toUpperCase() || 'UNKNOWN'}
          badgeType="cyan"
          loading={terminalObservation.loading && !terminal}
        />

        <MetricCard
          label="Balance"
          value={balance == null ? null : formatMoney(balance, terminal?.currency ?? undefined)}
          loading={terminalObservation.loading && !terminal}
        />

        <MetricCard
          label="Daily Loss %"
          value={`${dailyLoss.toFixed(2)}%`}
          subtext={riskData ? `Max Cap: ${riskData.max_daily_loss.toFixed(1)}%` : 'Max Cap: —'}
          trend={dailyLoss > 0 ? 'down' : 'neutral'}
          badge={riskData ? (riskEvidenceCurrent ? (riskData.risk_allowed ? 'PERMITTED' : 'LOCKED') : 'STALE') : 'UNKNOWN'}
          badgeType={riskData ? (riskEvidenceCurrent ? (riskData.risk_allowed ? 'green' : 'red') : 'amber') : 'neutral'}
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
          badge={riskData ? (riskEvidenceCurrent ? (tradesToday >= riskData.max_trades_daily ? 'CAPPED' : 'AVAILABLE') : 'STALE') : 'UNKNOWN'}
          badgeType={riskData && (!riskEvidenceCurrent || tradesToday >= riskData.max_trades_daily) ? 'amber' : 'neutral'}
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
