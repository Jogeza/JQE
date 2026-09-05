import React from 'react';
import { CandlestickChart as ChartIcon } from 'lucide-react';
import type { CandleItemDTO, SignalResponse } from '../types/api';
import { JQEChart } from './chart/JQEChart';
import type { SeriesMarker, Time } from 'lightweight-charts';
import type { VolumeProfileSnapshotDTO } from '../types/research';
import type { IndicatorVisibility } from './chart/JQEChart';

interface MarketChartProps {
  symbol: string;
  timeframe: string;
  candles: CandleItemDTO[];
  signal?: SignalResponse | null;
  priceDecimals?: number;
  loading?: boolean;
  error?: string | null;
  markers?: SeriesMarker<Time>[];
  volumeProfile?: VolumeProfileSnapshotDTO | null;
  indicators?: IndicatorVisibility;
  height?: number;
}

export const MarketChart: React.FC<MarketChartProps> = ({
  symbol, timeframe, candles, signal = null, priceDecimals, loading = false, error = null, markers = [], volumeProfile = null, indicators, height = 460,
}) => (
  <div className="quant-panel chart-panel" style={{ minHeight: '360px' }}>
    <div className="quant-panel-header">
      <div className="quant-panel-title">
        <ChartIcon size={14} color="var(--quant-cyan)" />
        <span>{symbol} — {timeframe} Quantitative Telemetry</span>
        <span style={{ fontSize: '10px', color: 'var(--text-dark-muted)', marginLeft: '6px' }}>
          JQE DATA · EMA50 · EMA200 · RSI(14)
        </span>
      </div>
    </div>
    {loading && candles.length === 0 ? (
      <ChartState>Loading JQE market telemetry…</ChartState>
    ) : error && candles.length === 0 ? (
      <ChartState tone="error">MARKET DATA UNAVAILABLE · {error}</ChartState>
    ) : candles.length === 0 ? (
      <ChartState>NO CANDLE DATA AVAILABLE</ChartState>
    ) : (
      <JQEChart symbol={symbol} candles={candles} signal={signal} markers={markers} priceDecimals={priceDecimals} volumeProfile={volumeProfile} indicators={indicators} height={height} />
    )}
  </div>
);

const ChartState: React.FC<React.PropsWithChildren<{ tone?: 'error' }>> = ({ children, tone }) => (
  <div style={{ minHeight: '320px', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', textAlign: 'center', color: tone === 'error' ? 'var(--quant-red)' : 'var(--text-dark-muted)', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
    {children}
  </div>
);
