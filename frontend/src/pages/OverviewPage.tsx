import React from 'react';
import { MetricCard } from '../components/MetricCard';
import { EngineStatusPanel } from '../components/EngineStatusPanel';
import { RiskPanel } from '../components/RiskPanel';
import { PositionsTable } from '../components/PositionsTable';
import { RecentTradesTable } from '../components/RecentTradesTable';
import { MarketChart } from '../components/MarketChart';
import { StrategySignalPanel } from '../components/StrategySignalPanel';
import { PerformanceSection } from '../components/PerformanceSection';
import {
  SystemStatusResponse,
  MarketSummaryResponse,
  CandlesResponse,
  SignalResponse,
  RiskStatusResponse,
  ExecutionStateResponse,
  PerformanceSummaryResponse,
} from '../types/api';
import { formatMoney } from '../utils/format';

interface OverviewPageProps {
  systemStatus: SystemStatusResponse | null;
  marketSummary: MarketSummaryResponse | null;
  candlesData: CandlesResponse | null;
  signalData: SignalResponse | null;
  riskData: RiskStatusResponse | null;
  executionData: ExecutionStateResponse | null;
  performanceData: PerformanceSummaryResponse | null;
  loading: boolean;
  selectedSymbol: string;
  selectedTimeframe: string;
  telemetryStale: { system: boolean; strategy: boolean; risk: boolean };
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  systemStatus,
  candlesData,
  signalData,
  riskData,
  executionData,
  performanceData,
  loading,
  selectedSymbol,
  selectedTimeframe,
  telemetryStale,
}) => {
  const balance = riskData?.balance;
  const equity = riskData?.equity;
  const openPositions = executionData?.positions || [];
  const openPnL = openPositions.reduce((acc, p) => acc + (p.profit || 0), 0);
  const recentTrades = executionData?.recent_trades || [];
  const tradesToday = riskData?.daily_trades_count ?? 0;
  const dailyLoss = riskData?.daily_loss_percent ?? 0.0;
  const winRate = performanceData?.win_rate_percent ?? 0.0;

  return (
    <div className="dashboard-page-container">
      {/* Top Metric Row */}
      <div className="grid-metrics">
        <MetricCard
          label="Account Equity"
          value={equity === undefined ? null : formatMoney(equity, riskData?.currency)}
          subtext={`Currency: ${riskData?.currency || '—'}`}
          trend={equity !== undefined && balance !== undefined ? (equity >= balance ? 'up' : 'down') : 'neutral'}
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
          value={performanceData ? `${winRate.toFixed(1)}%` : null}
          subtext={performanceData ? `${performanceData.total_trades} Total Trades` : 'Performance unavailable'}
          loading={loading && !performanceData}
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

      {/* Main Quantitative Workstation Grid: Left Chart/Strategy (2fr) + Right Engine/Risk (1fr) */}
      <div className="grid-two-col">
        {/* Left Column: Market Telemetry & Execution Data */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <MarketChart
            symbol={selectedSymbol}
            timeframe={selectedTimeframe}
            candles={candlesData?.candles || []}
            priceDecimals={candlesData?.price_decimals}
            loading={loading && !candlesData}
          />

          <StrategySignalPanel signal={signalData} loading={loading && !signalData} stale={telemetryStale.strategy} />

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
          />
        </div>

        {/* Right Column: Engine & Risk Telemetry */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
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
    </div>
  );
};
