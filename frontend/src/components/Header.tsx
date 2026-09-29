import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Wifi,
  WifiOff,
  RefreshCw,
  Clock,
  Layers,
  Search,
} from 'lucide-react';
import { SystemStatusResponse } from '../types/api';

// Native Weltrade symbol catalogue
const SYMBOL_OPTIONS = [
  'FX Vol 20', 'FX Vol 40', 'FX Vol 60', 'FX Vol 80', 'FX Vol 99',
  'SFX Vol 20', 'SFX Vol 40', 'SFX Vol 60', 'SFX Vol 80', 'SFX Vol 99',
  'PainX 400', 'PainX 600', 'PainX 800', 'PainX 999', 'PainX 1200',
  'MAX PainX 1000', 'MAX PainX 2000',
].map(value => ({ value, label: value, search: `${value.toLowerCase()} weltrade synthetic` }));

interface HeaderProps {
  systemStatus: SystemStatusResponse | null;
  loading: boolean;
  onRefresh: () => void;
  selectedSymbol: string;
  onSymbolChange: (symbol: string) => void;
  selectedTimeframe: string;
  onTimeframeChange: (tf: string) => void;
  telemetryStale?: boolean;
  pageTitle: string;
}

export const Header: React.FC<HeaderProps> = ({
  systemStatus,
  loading,
  onRefresh,
  selectedSymbol,
  onSymbolChange,
  selectedTimeframe,
  onTimeframeChange,
  telemetryStale,
  pageTitle,
}) => {
  const [time, setTime] = useState<string>('');
  const [utcTime, setUtcTime] = useState<string>('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [highlighted, setHighlighted] = useState(0);
  const searchInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const update = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString('en-GB', { hour12: false }));
      setUtcTime(now.toISOString().slice(11, 19) + ' UTC');
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, []);

  const searchResults = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return SYMBOL_OPTIONS.filter(o => !query || o.search.includes(query));
  }, [searchQuery]);

  useEffect(() => {
    if (!searchOpen) return;
    searchInput.current?.focus();
    setHighlighted(0);
  }, [searchOpen]);

  const selectSymbol = (symbol: string) => {
    onSymbolChange(symbol);
    setSearchOpen(false);
    setSearchQuery('');
  };

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') { e.preventDefault(); setSearchOpen(false); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHighlighted(i => Math.min(i + 1, searchResults.length - 1)); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setHighlighted(i => Math.max(i - 1, 0)); return; }
    if (e.key === 'Enter' && searchResults[highlighted]) { e.preventDefault(); selectSymbol(searchResults[highlighted].value); }
  };

  const env = systemStatus?.environment?.toUpperCase() || 'UNKNOWN';
  const isConnected = systemStatus?.broker_connected;

  const connectionColor = telemetryStale
    ? 'var(--quant-amber)'
    : isConnected === undefined
      ? 'var(--text-dark-muted)'
      : isConnected
        ? 'var(--quant-green)'
        : 'var(--quant-amber)';

  const connectionLabel = telemetryStale
    ? 'STALE'
    : isConnected === undefined
      ? 'UNKNOWN'
      : isConnected
        ? 'ONLINE'
        : 'OFFLINE';

  return (
    <header className="application-header" aria-label="Application header">
      {/* ── Left: Page title + environment ─────────────────── */}
      <div className="header-left">
        <strong className="header-page-title">{pageTitle}</strong>
        <div className="header-env-badge">
          <span
            className="header-env-dot"
            style={{ backgroundColor: env.includes('PROD') || env === 'LIVE' ? 'var(--quant-red)' : env.includes('DEMO') ? 'var(--quant-green)' : 'var(--quant-amber)' }}
          />
          <span className="header-env-text">{env}</span>
        </div>
      </div>

      {/* ── Centre: Symbol + Timeframe selector ────────────── */}
      <div className="header-centre">
        <div className="header-instrument-bar">
          <Layers size={11} color="var(--brand-cyan)" />

          {/* Symbol search trigger */}
          <button
            className="symbol-search-button"
            type="button"
            aria-label="Search symbols"
            aria-expanded={searchOpen}
            aria-controls="symbol-search-popover"
            onClick={() => setSearchOpen(o => !o)}
            title="Search symbols"
          >
            <Search size={13} />
          </button>

          {/* Symbol dropdown */}
          <select
            value={selectedSymbol}
            onChange={e => onSymbolChange(e.target.value)}
            aria-label="Active symbol"
            className="header-select header-symbol-select"
          >
            {SYMBOL_OPTIONS.map(o => (
              <option key={o.value} value={o.value} style={{ background: '#0f1117', color: '#f0f2f5' }}>
                {o.label}
              </option>
            ))}
          </select>

          {/* Symbol search popover */}
          {searchOpen && (
            <div id="symbol-search-popover" className="symbol-search-popover" role="dialog" aria-label="Search symbols">
              <label htmlFor="symbol-search-input">Find a symbol</label>
              <input
                id="symbol-search-input"
                ref={searchInput}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={handleSearchKeyDown}
                placeholder="Search symbol or name"
                autoComplete="off"
              />
              <div role="listbox" aria-label="Symbol results">
                {searchResults.map((o, i) => (
                  <button
                    type="button"
                    role="option"
                    aria-selected={o.value === selectedSymbol}
                    key={o.value}
                    className={`symbol-search-result${i === highlighted ? ' highlighted' : ''}`}
                    onMouseEnter={() => setHighlighted(i)}
                    onClick={() => selectSymbol(o.value)}
                  >
                    <strong>{o.value}</strong>
                  </button>
                ))}
                {!searchResults.length && <p className="symbol-search-empty">No matching symbols.</p>}
              </div>
              <small>↑↓ navigate · Enter select · Esc close</small>
            </div>
          )}

          <div className="header-divider" />

          {/* Timeframe selector */}
          <select
            value={selectedTimeframe}
            onChange={e => onTimeframeChange(e.target.value)}
            aria-label="Active timeframe"
            className="header-select header-tf-select"
          >
            {['M1','M5','M15','M30','H1','H4','D1'].map(tf => (
              <option key={tf} value={tf} style={{ background: '#0f1117', color: '#f0f2f5' }}>{tf}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ── Right: Broker selector, connection, clocks, sync ── */}
      <div className="header-right">
        {/* Connection pill */}
        <div className="header-connection-pill" style={{ color: connectionColor }}>
          {telemetryStale || !isConnected
            ? <WifiOff size={12} />
            : <Wifi size={12} />}
          <span className="header-connection-label">{connectionLabel}</span>
        </div>

        {/* Clock */}
        <div className="header-clock">
          <Clock size={11} color="var(--text-dark-muted)" />
          <span className="header-clock-local">{time}</span>
          <span className="header-clock-utc">{utcTime}</span>
        </div>

        {/* Sync button */}
        <button
          onClick={onRefresh}
          className="header-sync-btn"
          title="Refresh all engine feeds"
          aria-label="Sync all data"
        >
          <RefreshCw size={12} className={loading ? 'spin' : ''} />
          <span>SYNC</span>
        </button>
      </div>
    </header>
  );
};
