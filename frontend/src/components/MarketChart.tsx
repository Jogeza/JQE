import React, { useEffect, useState } from 'react';
import { EmptyStateIllustration } from './EmptyStateIllustration';
import { CandlestickChart as ChartIcon, Maximize2, Minimize2, ArrowLeftRight } from 'lucide-react';
import type { CandleItemDTO, MarketSetup, SignalResponse } from '../types/api';
import { JQEChart } from './chart/JQEChart';
import { ChartIndicatorPicker } from './ChartIndicatorPicker';
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
  compactPriceScale?: boolean;
  onToggleCompactPriceScale?: () => void;
  symbolControls?: React.ReactNode;
  sourceLabel?: React.ReactNode;
  emptyMessage?: React.ReactNode;
  overlay?: React.ReactNode;
}

export const MarketChart: React.FC<MarketChartProps> = ({
  symbol, timeframe, candles, signal = null, setup = null, priceDecimals, loading = false, error = null, dataStatus, markers = [], volumeProfile = null, indicators, height = 460, fibonacciLevels = [],
  compactPriceScale: controlledCompactPriceScale, onToggleCompactPriceScale, symbolControls, sourceLabel, emptyMessage, overlay,
}) => {
  const [internalCompactPriceScale, setInternalCompactPriceScale] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [internalIndicators, setInternalIndicators] = useState<IndicatorVisibility>({ ema50: true, ema200: true, rsi: false, volume: false });
  const compactPriceScale = controlledCompactPriceScale ?? internalCompactPriceScale;
  const toggleCompactPriceScale = onToggleCompactPriceScale ?? (() => setInternalCompactPriceScale(value => !value));
  const effectiveIndicators = indicators ?? internalIndicators;
  const statusState = error ? 'ERROR' : loading ? 'LOADING' : candles.length === 0 || dataStatus === 'UNAVAILABLE' ? 'UNAVAILABLE' : dataStatus === 'CURRENT' ? 'LIVE' : dataStatus === 'CACHED' ? 'STALE' : 'UNKNOWN';

  useEffect(() => {
    if (!fullscreen) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setFullscreen(false); };
    document.addEventListener('keydown', onKeyDown);
    document.body.classList.add('chart-fullscreen-lock');
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.classList.remove('chart-fullscreen-lock');
    };
  }, [fullscreen]);

  return (
  <div className={`quant-panel chart-panel${fullscreen ? ' is-fullscreen' : ''}`} data-state={statusState} style={{ minHeight: '360px' }}>
    <div className="quant-panel-header">
      <div className="quant-panel-title">
        <ChartIcon size={14} color="var(--chart-accent)" />
        {symbolControls ?? <span>{symbol} / {timeframe}</span>}
        <span className="chart-legend" style={{ fontSize: '10px', color: 'var(--text-dark-muted)', marginLeft: '6px' }}>
          <span>JQE DATA</span>
          {effectiveIndicators.ema50 && <span className="chart-legend-item ema50"><i className="chart-legend-dot" />EMA50</span>}
          {effectiveIndicators.ema200 && <span className="chart-legend-item ema200"><i className="chart-legend-dot" />EMA200</span>}
          {effectiveIndicators.rsi && <span className="chart-legend-item rsi"><i className="chart-legend-dot" />RSI(14)</span>}
          {effectiveIndicators.volume && <span className="chart-legend-item volume"><i className="chart-legend-dot" />VOL</span>}
        </span>
        {sourceLabel && <span className="chart-source-label" data-state={statusState} title={`${typeof sourceLabel === 'string' ? sourceLabel : 'Data source'} · ${statusState}`}><i className="chart-source-dot" role="img" aria-label={`Data state ${statusState}`} /><span className="chart-source-text">{sourceLabel}</span></span>}
      </div>
      {!indicators && <ChartIndicatorPicker indicators={internalIndicators} onChange={setInternalIndicators} />}
      <button type="button" className="chart-density-toggle" aria-pressed={compactPriceScale}
        aria-label={compactPriceScale ? 'Full prices' : 'Compact prices'}
        title="Use smaller price labels and a narrower right price axis"
        onClick={toggleCompactPriceScale}><ArrowLeftRight size={16} aria-hidden="true" /><span className="chart-control-label">{compactPriceScale ? 'Full prices' : 'Compact prices'}</span></button>
      <button type="button" className="chart-fullscreen-toggle" aria-pressed={fullscreen}
        aria-label={fullscreen ? 'Exit fullscreen chart' : 'Fullscreen chart'}
        title={fullscreen ? 'Exit fullscreen (Esc)' : 'Expand chart to fill the screen'}
        onClick={() => setFullscreen(value => !value)}>
        {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
      </button>
      {statusState === 'ERROR' && <span className="badge badge-neutral" role="status">ERROR · retained data</span>}
    </div>
    {fullscreen && overlay && <div className="chart-overlay">{overlay}</div>}
    {loading && candles.length === 0 ? (
      <ChartState>Loading JQE market telemetry…</ChartState>
    ) : error && candles.length === 0 ? (
      <ChartState>MARKET DATA UNAVAILABLE · {error}</ChartState>
    ) : candles.length === 0 ? (
      <ChartState>{emptyMessage ?? 'NO CANDLE DATA AVAILABLE'}</ChartState>
    ) : (
      <JQEChart symbol={symbol} timeframe={timeframe} drawingTools candles={candles} signal={signal} setup={setup} markers={markers} priceDecimals={priceDecimals} volumeProfile={volumeProfile} indicators={effectiveIndicators} height={height} fibonacciLevels={fibonacciLevels} compactPriceScale={compactPriceScale} fill={fullscreen} />
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
