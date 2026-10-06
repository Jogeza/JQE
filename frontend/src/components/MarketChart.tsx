import React, { useState } from 'react';
import { EmptyStateIllustration } from './EmptyStateIllustration';
import { CandlestickChart as ChartIcon } from 'lucide-react';
import type { CandleItemDTO, MarketSetup, SignalResponse } from '../types/api';
import { JQEChart } from './chart/JQEChart';
import type { SeriesMarker, Time } from 'lightweight-charts';
import type { VolumeProfileSnapshotDTO } from '../types/research';
import type { IndicatorVisibility } from './chart/JQEChart';
import type { FibonacciLevel } from './chart/fibonacci';

interface MarketChartProps {
  symbol: string;
  timeframe: string;
  candles: CandleItemDTO[];
  signal?: SignalResponse | null;
  setup?: MarketSetup | null;
  priceDecimals?: number;
  loading?: boolean;
  error?: string | null;
  dataStatus?: 'CURRENT' | 'CACHED' | 'UNAVAILABLE' | 'UNKNOWN';
  markers?: SeriesMarker<Time>[];
  volumeProfile?: VolumeProfileSnapshotDTO | null;
  indicators?: IndicatorVisibility;
  height?: number;
  fibonacciLevels?: FibonacciLevel[];
}

export const MarketChart: React.FC<MarketChartProps> = ({
  symbol, timeframe, candles, signal = null, setup = null, priceDecimals, loading = false, error = null, dataStatus, markers = [], volumeProfile = null, indicators, height = 460, fibonacciLevels = [],
}) => {
  const [compactPriceScale, setCompactPriceScale] = useState(false);
  const [priceScaleSide, setPriceScaleSide] = useState<'left' | 'right'>('left');
  return (
  <div className="quant-panel chart-panel" data-state={error ? 'ERROR' : loading ? 'LOADING' : candles.length === 0 || dataStatus === 'UNAVAILABLE' ? 'UNAVAILABLE' : dataStatus === 'CURRENT' ? 'LIVE' : dataStatus === 'CACHED' ? 'STALE' : 'UNKNOWN'} style={{ minHeight: '360px' }}>
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
      {dataStatus === 'UNKNOWN' && <span className="badge badge-neutral">FRESHNESS UNKNOWN</span>}
      {dataStatus === 'UNAVAILABLE' && <span className="badge badge-neutral">UNAVAILABLE</span>}
      <button type="button" className="chart-density-toggle" aria-pressed={compactPriceScale}
        title="Use smaller price labels and a narrower price axis"
        onClick={() => setCompactPriceScale(value => !value)}>{compactPriceScale ? 'Full prices' : 'Compact prices'}</button>
      <button type="button" className="chart-density-toggle" aria-pressed={priceScaleSide === 'left'} onClick={() => setPriceScaleSide(side => side === 'left' ? 'right' : 'left')}>Prices: {priceScaleSide}</button>
      <span className="badge badge-neutral" role="status">{error ? 'ERROR · retained data' : loading ? 'LOADING' : dataStatus === 'CURRENT' ? 'LIVE' : dataStatus === 'CACHED' ? 'STALE' : dataStatus ?? 'UNKNOWN'}</span>
    </div>
    {loading && candles.length === 0 ? (
      <ChartState>Loading JQE market telemetry…</ChartState>
    ) : error && candles.length === 0 ? (
      <ChartState>MARKET DATA UNAVAILABLE · {error}</ChartState>
    ) : candles.length === 0 ? (
      <ChartState>NO CANDLE DATA AVAILABLE</ChartState>
    ) : (
      <JQEChart symbol={symbol} timeframe={timeframe} drawingTools candles={candles} signal={signal} setup={setup} markers={markers} priceDecimals={priceDecimals} volumeProfile={volumeProfile} indicators={indicators} height={height} fibonacciLevels={fibonacciLevels} compactPriceScale={compactPriceScale} priceScaleSide={priceScaleSide} />
    )}
  </div>
  );
};

const ChartState: React.FC<React.PropsWithChildren<{ tone?: 'error' }>> = ({ children, tone }) => (
  <div className="chart-empty-state" role={tone === 'error' ? 'alert' : 'status'}>
    <EmptyStateIllustration />
    {children}
  </div>
);
