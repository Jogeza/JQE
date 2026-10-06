import React, { useEffect, useRef, useState } from 'react';
import { ChevronDown, SlidersHorizontal } from 'lucide-react';
import type { IndicatorVisibility } from './chart/JQEChart';

const INDICATOR_OPTIONS: { key: keyof IndicatorVisibility; label: string }[] = [
  { key: 'ema50', label: 'EMA 50' },
  { key: 'ema200', label: 'EMA 200' },
  { key: 'rsi', label: 'RSI (14) pane' },
  { key: 'volume', label: 'Volume' },
];

interface ChartIndicatorPickerProps {
  indicators: IndicatorVisibility;
  onChange: (indicators: IndicatorVisibility) => void;
}

export const ChartIndicatorPicker: React.FC<ChartIndicatorPickerProps> = ({ indicators, onChange }) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  // Escape must close the picker without bubbling to document-level handlers
  // (the chart fullscreen listener would otherwise exit the overlay too).
  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && open) { event.stopPropagation(); setOpen(false); }
  };

  return <div className={`chart-indicator-picker${open ? ' is-open' : ''}`} ref={rootRef} onKeyDown={onKeyDown}>
    <button type="button" className="chart-indicator-toggle" aria-haspopup="true" aria-expanded={open}
      aria-label="Chart indicators" title="Choose which indicators are drawn on the synthetic index chart"
      onClick={() => setOpen(value => !value)}>
      <SlidersHorizontal size={12} aria-hidden="true" />
      <span>Indicators</span>
      <ChevronDown size={12} aria-hidden="true" />
    </button>
    {open && <fieldset className="chart-indicator-popover">
      <legend>Chart indicators</legend>
      {INDICATOR_OPTIONS.map(option => <label key={option.key} className="chart-indicator-option">
        <input type="checkbox" checked={indicators[option.key]}
          onChange={() => onChange({ ...indicators, [option.key]: !indicators[option.key] })} />
        <span>{option.label}</span>
      </label>)}
      <small>EMA overlays the price pane; RSI opens its own pane.</small>
    </fieldset>}
  </div>;
};
