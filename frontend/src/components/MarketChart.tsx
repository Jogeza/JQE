import React, { useState, useRef } from 'react';
import { CandlestickChart as ChartIcon } from 'lucide-react';
import { CandleItemDTO } from '../types/api';
import { formatInstrumentPrice } from '../utils/format';

interface MarketChartProps {
  symbol: string;
  timeframe: string;
  candles: CandleItemDTO[];
  priceDecimals?: number;
  loading?: boolean;
}

export const MarketChart: React.FC<MarketChartProps> = ({
  symbol,
  timeframe,
  candles,
  priceDecimals,
  loading,
}) => {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  if (loading || candles.length === 0) {
    return (
      <div className="quant-panel" style={{ height: '360px' }}>
        <div className="quant-panel-header">
          <div className="quant-panel-title">
            <ChartIcon size={14} color="var(--quant-cyan)" />
            <span>Market Chart — {symbol} ({timeframe})</span>
          </div>
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
          {loading ? 'Loading market candles and indicators...' : 'NO CANDLE DATA AVAILABLE'}
        </div>
      </div>
    );
  }

  // Chart Dimensions
  const svgWidth = 850;
  const priceHeight = 240;
  const rsiHeight = 70;
  const gap = 15;
  const totalHeight = priceHeight + gap + rsiHeight;
  const paddingLeft = 10;
  const paddingRight = 65;
  const chartWidth = svgWidth - paddingLeft - paddingRight;

  // Price Extents
  const highs = candles.map((c) => c.high);
  const lows = candles.map((c) => c.low);
  const minPrice = Math.min(...lows);
  const maxPrice = Math.max(...highs);
  const priceRange = maxPrice - minPrice || 1;

  // Volume Extents
  const volumes = candles.map((c) => c.volume);
  const maxVol = Math.max(...volumes, 1);

  // Coordinate scales
  const candleCount = candles.length;
  const candleSlotWidth = chartWidth / candleCount;
  const candleBodyWidth = Math.max(2, Math.min(10, candleSlotWidth * 0.7));

  const getYPrice = (price: number) => {
    return priceHeight - ((price - minPrice) / priceRange) * (priceHeight - 20) - 10;
  };

  const getYRsi = (rsi: number) => {
    // RSI from 0 to 100
    const clamped = Math.max(0, Math.min(100, rsi));
    return priceHeight + gap + (rsiHeight - (clamped / 100) * rsiHeight);
  };

  const activeCandle = hoverIndex !== null && hoverIndex >= 0 && hoverIndex < candleCount
    ? candles[hoverIndex]
    : candles[candles.length - 1];

  // Build EMA50 and EMA200 polyline paths
  const ema50Points = candles
    .map((c, i) => {
      if (c.EMA50 === null || isNaN(c.EMA50)) return null;
      const x = paddingLeft + i * candleSlotWidth + candleSlotWidth / 2;
      const y = getYPrice(c.EMA50);
      return `${x},${y}`;
    })
    .filter(Boolean)
    .join(' ');

  const ema200Points = candles
    .map((c, i) => {
      if (c.EMA200 === null || isNaN(c.EMA200)) return null;
      const x = paddingLeft + i * candleSlotWidth + candleSlotWidth / 2;
      const y = getYPrice(c.EMA200);
      return `${x},${y}`;
    })
    .filter(Boolean)
    .join(' ');

  // Build RSI Polyline path
  const rsiPoints = candles
    .map((c, i) => {
      if (c.RSI === null || isNaN(c.RSI)) return null;
      const x = paddingLeft + i * candleSlotWidth + candleSlotWidth / 2;
      const y = getYRsi(c.RSI);
      return `${x},${y}`;
    })
    .filter(Boolean)
    .join(' ');

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const xPos = e.clientX - rect.left;
    const chartX = (xPos / rect.width) * svgWidth - paddingLeft;
    const idx = Math.floor(chartX / candleSlotWidth);
    if (idx >= 0 && idx < candleCount) {
      setHoverIndex(idx);
    }
  };

  return (
    <div className="quant-panel" ref={containerRef}>
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <ChartIcon size={14} color="var(--quant-cyan)" />
          <span>{symbol} — {timeframe} Quantitative Telemetry</span>
          <span style={{ fontSize: '10px', color: 'var(--quant-cyan)', marginLeft: '6px' }}>
            [EMA50: cyan] [EMA200: purple] [RSI(14)]
          </span>
        </div>

        {/* Live Candle Details */}
        {activeCandle && (
          <div style={{ display: 'flex', gap: '10px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
            <span>O: <strong style={{ color: 'var(--text-primary)' }}>{formatInstrumentPrice(activeCandle.open, priceDecimals)}</strong></span>
            <span>H: <strong style={{ color: 'var(--text-primary)' }}>{formatInstrumentPrice(activeCandle.high, priceDecimals)}</strong></span>
            <span>L: <strong style={{ color: 'var(--text-primary)' }}>{formatInstrumentPrice(activeCandle.low, priceDecimals)}</strong></span>
            <span>C: <strong style={{ color: activeCandle.close >= activeCandle.open ? 'var(--quant-green)' : 'var(--quant-red)' }}>{formatInstrumentPrice(activeCandle.close, priceDecimals)}</strong></span>
            {activeCandle.RSI !== null && (
              <span>RSI: <strong style={{ color: 'var(--quant-amber)' }}>{activeCandle.RSI.toFixed(1)}</strong></span>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: '8px', overflowX: 'auto', backgroundColor: '#07080a' }}>
        <svg
          viewBox={`0 0 ${svgWidth} ${totalHeight}`}
          style={{ width: '100%', height: '320px', display: 'block', userSelect: 'none' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoverIndex(null)}
        >
          {/* Grid lines (horizontal price lines) */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const p = minPrice + ratio * priceRange;
            const y = getYPrice(p);
            return (
              <g key={`grid-${ratio}`}>
                <line x1={paddingLeft} y1={y} x2={svgWidth - paddingRight} y2={y} stroke="rgba(255,255,255,0.05)" strokeDasharray="3 3" />
                <text x={svgWidth - paddingRight + 5} y={y + 3} fill="var(--text-muted)" fontSize="9" fontFamily="var(--font-mono)">
                  {formatInstrumentPrice(p, priceDecimals)}
                </text>
              </g>
            );
          })}

          {/* Volume bars */}
          {candles.map((c, i) => {
            const x = paddingLeft + i * candleSlotWidth + (candleSlotWidth - candleBodyWidth) / 2;
            const barH = ((c.volume || 1) / maxVol) * 40;
            const y = priceHeight - barH;
            const isBull = c.close >= c.open;
            return (
              <rect
                key={`vol-${i}`}
                x={x}
                y={y}
                width={candleBodyWidth}
                height={barH}
                fill={isBull ? 'rgba(0, 230, 118, 0.15)' : 'rgba(255, 82, 82, 0.15)'}
              />
            );
          })}

          {/* Candlesticks */}
          {candles.map((c, i) => {
            const centerX = paddingLeft + i * candleSlotWidth + candleSlotWidth / 2;
            const isBull = c.close >= c.open;
            const color = isBull ? 'var(--quant-green)' : 'var(--quant-red)';
            const yOpen = getYPrice(c.open);
            const yClose = getYPrice(c.close);
            const yHigh = getYPrice(c.high);
            const yLow = getYPrice(c.low);
            const topY = Math.min(yOpen, yClose);
            const bodyH = Math.max(1.5, Math.abs(yClose - yOpen));

            return (
              <g key={`candle-${i}`}>
                {/* Wick */}
                <line x1={centerX} y1={yHigh} x2={centerX} y2={yLow} stroke={color} strokeWidth="1" />
                {/* Body */}
                <rect
                  x={centerX - candleBodyWidth / 2}
                  y={topY}
                  width={candleBodyWidth}
                  height={bodyH}
                  fill={isBull ? 'var(--quant-green)' : 'var(--quant-red)'}
                />
              </g>
            );
          })}

          {/* Overlays: EMA50 & EMA200 */}
          {ema50Points && <polyline fill="none" stroke="var(--quant-cyan)" strokeWidth="1.2" points={ema50Points} opacity="0.85" />}
          {ema200Points && <polyline fill="none" stroke="var(--quant-purple)" strokeWidth="1.2" points={ema200Points} opacity="0.85" />}

          {/* RSI Pane Divider */}
          <line x1={paddingLeft} y1={priceHeight + gap / 2} x2={svgWidth - paddingRight} y2={priceHeight + gap / 2} stroke="var(--border-medium)" />

          {/* RSI Reference Lines (70 and 30) */}
          <line x1={paddingLeft} y1={getYRsi(70)} x2={svgWidth - paddingRight} y2={getYRsi(70)} stroke="rgba(255, 171, 0, 0.25)" strokeDasharray="2 2" />
          <text x={svgWidth - paddingRight + 5} y={getYRsi(70) + 3} fill="var(--quant-amber)" fontSize="8" fontFamily="var(--font-mono)">70</text>
          <line x1={paddingLeft} y1={getYRsi(30)} x2={svgWidth - paddingRight} y2={getYRsi(30)} stroke="rgba(255, 171, 0, 0.25)" strokeDasharray="2 2" />
          <text x={svgWidth - paddingRight + 5} y={getYRsi(30) + 3} fill="var(--quant-amber)" fontSize="8" fontFamily="var(--font-mono)">30</text>

          {/* RSI Line */}
          {rsiPoints && <polyline fill="none" stroke="var(--quant-amber)" strokeWidth="1.2" points={rsiPoints} />}

          {/* Hover Crosshair */}
          {hoverIndex !== null && hoverIndex >= 0 && hoverIndex < candleCount && (
            <g>
              <line
                x1={paddingLeft + hoverIndex * candleSlotWidth + candleSlotWidth / 2}
                y1={0}
                x2={paddingLeft + hoverIndex * candleSlotWidth + candleSlotWidth / 2}
                y2={totalHeight}
                stroke="rgba(255, 255, 255, 0.3)"
                strokeDasharray="2 2"
              />
            </g>
          )}
        </svg>
      </div>
    </div>
  );
};
