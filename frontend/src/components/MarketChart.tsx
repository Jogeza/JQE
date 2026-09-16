import React from 'react';
import { EmptyStateIllustration } from './EmptyStateIllustration';
import { CandlestickChart as ChartIcon } from 'lucide-react';
import type { CandleItemDTO, MarketSetup, SignalResponse } from '../types/api';
import { JQEChart } from './chart/JQEChart';
import type { SeriesMarker, Time } from 'lightweight-charts';
import type { VolumeProfileSnapshotDTO } from '../types/research';
import type { IndicatorVisibility } from './chart/JQEChart';

interface MarketChartProps {
  symbol: string;
  timeframe: string;
  candles: CandleItemDTO[];
  signal?: SignalResponse | null;
  setup?: MarketSetup | null;
  priceDecimals?: number;
  loading?: boolean;
  error?: string | null;
  dataStatus?: 'CURRENT' | 'CACHED' | 'UNAVAILABLE';
  markers?: SeriesMarker<Time>[];
  volumeProfile?: VolumeProfileSnapshotDTO | null;
  indicators?: IndicatorVisibility;
  height?: number;
}

export const MarketChart: React.FC<MarketChartProps> = ({
  symbol, timeframe, candles, signal = null, setup = null, priceDecimals, loading = false, error = null, dataStatus, markers = [], volumeProfile = null, indicators, height = 460,
}) => (
  <div className="quant-panel chart-panel" style={{ minHeight: '360px' }}>
    <div className="quant-panel-header">
      <div className="quant-panel-title">
        <ChartIcon size={14} color="var(--chart-accent)" />
        <span>{symbol} / {timeframe}</span>
        <span className="chart-legend" style={{ fontSize: '10px', color: 'var(--text-dark-muted)', marginLeft: '6px' }}>
          <span>JQE DATA</span><span className="chart-legend-item ema50"><i className="chart-legend-dot" />EMA50</span>
          <span className="chart-legend-item ema200"><i className="chart-legend-dot" />EMA200</span>
          <span className="chart-legend-item rsi"><i className="chart-legend-dot" />RSI(14)</span>
        </span>
      </div>
      {dataStatus === 'CACHED' && <span className="badge badge-neutral">CACHED · STALE · DEGRADED</span>}
      {dataStatus === 'UNAVAILABLE' && <span className="badge badge-neutral">UNAVAILABLE</span>}
    </div>
    {loading && candles.length === 0 ? (
      <ChartState>Loading JQE market telemetry…</ChartState>
    ) : error && candles.length === 0 ? (
      <ChartState>MARKET DATA UNAVAILABLE · {error}</ChartState>
    ) : candles.length === 0 ? (
      <ChartState>NO CANDLE DATA AVAILABLE</ChartState>
    ) : (
      <JQEChart symbol={symbol} candles={candles} signal={signal} setup={setup} markers={markers} priceDecimals={priceDecimals} volumeProfile={volumeProfile} indicators={indicators} height={height} />
    )}
  </div>
);

const ChartState: React.FC<React.PropsWithChildren<{ tone?: 'error' }>> = ({ children, tone }) => (
  <div className="chart-empty-state" role={tone === 'error' ? 'alert' : 'status'}>
    <EmptyStateIllustration />
    {children}
  </div>
);
