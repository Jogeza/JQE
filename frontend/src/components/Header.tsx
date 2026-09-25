import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
  Wifi,
  WifiOff,
  RefreshCw,
  Clock,
  Layers,
  Search,
} from 'lucide-react';

const SYMBOL_OPTIONS = [
  { value: 'R_75', label: 'R_75 (Volatility 75 Index)', search: 'r_75 r75 volatility 75 index synthetic' },
  { value: 'FX Vol 10', label: 'FX Vol 10 (Weltrade)', search: 'fx vol 10 volatility 10 weltrade synthetic' },
  { value: 'FX Vol 20', label: 'FX Vol 20 (Weltrade)', search: 'fx vol 20 volatility 20 weltrade synthetic' },
  { value: 'FX Vol 25', label: 'FX Vol 25 (Weltrade)', search: 'fx vol 25 volatility 25 weltrade synthetic' },
  { value: 'FX Vol 50', label: 'FX Vol 50 (Weltrade)', search: 'fx vol 50 volatility 50 weltrade synthetic' },
  { value: 'FX Vol 75', label: 'FX Vol 75 (Weltrade)', search: 'fx vol 75 volatility 75 weltrade synthetic' },
  { value: 'FX Vol 100', label: 'FX Vol 100 (Weltrade)', search: 'fx vol 100 volatility 100 weltrade synthetic' },
  { value: 'XAUUSD', label: 'XAUUSD (Gold)', search: 'xauusd gold' },
  { value: 'EURUSD', label: 'EURUSD', search: 'eurusd euro dollar' },
  { value: 'GBPUSD', label: 'GBPUSD', search: 'gbpusd pound dollar' },
  { value: 'USDJPY', label: 'USDJPY', search: 'usdjpy dollar yen' },
  { value: 'BTCUSD', label: 'BTCUSD', search: 'btcusd bitcoin dollar' },
];
import { SystemStatusResponse, BrokerStatusResponse } from '../types/api';
import { BrokerSelector } from './BrokerSelector';

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
  brokerStatus?: BrokerStatusResponse | null;
  onSelectBroker?: (broker: string) => Promise<void>;
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
  brokerStatus,
  onSelectBroker,
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
    return SYMBOL_OPTIONS.filter(option => !query || option.search.includes(query));
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

  const handleSearchKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') { event.preventDefault(); setSearchOpen(false); return; }
    if (event.key === 'ArrowDown') { event.preventDefault(); setHighlighted(index => Math.min(index + 1, Math.max(searchResults.length - 1, 0))); return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); setHighlighted(index => Math.max(index - 1, 0)); return; }
    if (event.key === 'Enter' && searchResults[highlighted]) { event.preventDefault(); selectSymbol(searchResults[highlighted].value); }
  };

  const env = systemStatus?.environment?.toUpperCase() || 'UNKNOWN';
  const broker = systemStatus?.broker?.toUpperCase() || 'UNKNOWN';
  const isConnected = systemStatus?.broker_connected;

  const getEnvBadgeClass = () => {
    if (env.includes('PROD') || env === 'LIVE') return 'badge-live';
    if (env.includes('DEMO')) return 'badge-demo';
    return 'badge-simulation';
  };

  return (
    <header className="application-header"
      style={{
        height: 'var(--header-height)',
        backgroundColor: 'var(--bg-dark-header)',
        borderBottom: '1px solid var(--border-dark)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        userSelect: 'none',
        flexShrink: 0,
      }}
    >
      <strong className="header-page-title">{pageTitle}</strong>
      {/* Left Group: Environment & Market / Timeframe Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* Environment Badge */}
        <div className={`header-environment badge ${getEnvBadgeClass()}`} style={{ height: '24px', fontSize: '10px' }}>
          <span style={{ width: '5px', height: '5px', borderRadius: '50%', backgroundColor: 'currentColor' }} />
          <span>{env}</span>
          <span style={{ opacity: 0.65, fontSize: '9px', marginLeft: '2px' }}>[{broker}]</span>
        </div>

        {/* Grouped Instrument & Timeframe Selector Bar */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'var(--bg-dark-input)',
            border: '1px solid var(--border-dark-medium)',
            borderRadius: 'var(--radius-sm)',
            padding: '2px 8px',
            height: '28px',
            gap: '8px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <Layers size={12} color="var(--quant-cyan)" />
            <button className="symbol-search-button" type="button" aria-label="Search symbols" aria-expanded={searchOpen}
              aria-controls="symbol-search-popover" onClick={() => setSearchOpen(open => !open)} title="Search symbols">
              <Search size={14} />
            </button>
            <select
              value={selectedSymbol}
              onChange={(e) => onSymbolChange(e.target.value)}
              aria-label="Active symbol"
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-dark-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11.5px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
                padding: '0 4px',
                height: '100%',
              }}
            >
              {SYMBOL_OPTIONS.map(option => <option key={option.value} value={option.value} style={{ background: '#1c1c1c', color: '#fafafa' }}>{option.label}</option>)}
            </select>
            {searchOpen && <div id="symbol-search-popover" className="symbol-search-popover" role="dialog" aria-label="Search symbols">
              <label htmlFor="symbol-search-input">Find a symbol</label>
              <input id="symbol-search-input" ref={searchInput} value={searchQuery} onChange={event => setSearchQuery(event.target.value)} onKeyDown={handleSearchKeyDown} placeholder="Search symbol or name" autoComplete="off" />
              <div role="listbox" aria-label="Symbol results">
                {searchResults.map((option, index) => <button type="button" role="option" aria-selected={option.value === selectedSymbol} key={option.value} className={index === highlighted ? 'symbol-search-result highlighted' : 'symbol-search-result'} onMouseEnter={() => setHighlighted(index)} onClick={() => selectSymbol(option.value)}><strong>{option.value}</strong><span>{option.label.replace(`${option.value} `, '').replace(/[()]/g, '') || 'Currency pair'}</span></button>)}
                {!searchResults.length && <p className="symbol-search-empty">No matching symbols.</p>}
              </div>
              <small>↑ ↓ navigate · Enter select · Esc close</small>
            </div>}
          </div>

          <div style={{ width: '1px', height: '14px', backgroundColor: 'var(--border-dark-medium)' }} />

          <select
            value={selectedTimeframe}
            onChange={(e) => onTimeframeChange(e.target.value)}
            aria-label="Active timeframe"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--quant-cyan)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              fontWeight: 700,
              outline: 'none',
              cursor: 'pointer',
              padding: '0 2px',
              height: '100%',
            }}
          >
            <option value="M1" style={{ background: '#1c1c1c', color: '#fafafa' }}>M1</option>
            <option value="M5" style={{ background: '#1c1c1c', color: '#fafafa' }}>M5</option>
            <option value="M15" style={{ background: '#1c1c1c', color: '#fafafa' }}>M15</option>
            <option value="M30" style={{ background: '#1c1c1c', color: '#fafafa' }}>M30</option>
            <option value="H1" style={{ background: '#1c1c1c', color: '#fafafa' }}>H1</option>
            <option value="H4" style={{ background: '#1c1c1c', color: '#fafafa' }}>H4</option>
            <option value="D1" style={{ background: '#1c1c1c', color: '#fafafa' }}>D1</option>
          </select>
        </div>
      </div>

      {/* Right Group: Broker Selector, Connection, Clocks, Refresh */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {onSelectBroker && (
          <BrokerSelector brokerStatus={brokerStatus ?? null} onSelectBroker={onSelectBroker} />
        )}
        {/* Connection Indicator */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
            padding: '2px 8px',
            borderRadius: 'var(--radius-xs)',
            backgroundColor: 'rgba(0,0,0, 0.2)',
          }}
        >
          {telemetryStale ? (
            <>
              <WifiOff size={12} color="var(--quant-amber)" />
              <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>STALE</span>
            </>
          ) : isConnected === undefined ? (
            <>
              <WifiOff size={12} color="var(--text-dark-muted)" />
              <span style={{ color: 'var(--text-dark-muted)', fontWeight: 600 }}>UNKNOWN</span>
            </>
          ) : isConnected ? (
            <>
              <Wifi size={12} color="var(--quant-green)" />
              <span style={{ color: 'var(--status-green)', fontWeight: 600 }}>ONLINE</span>
            </>
          ) : (
            <>
              <WifiOff size={12} color="var(--quant-amber)" />
              <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>DISCONNECTED</span>
            </>
          )}
        </div>

        {/* Grouped Clocks (Local & UTC) */}
        <div className="header-clocks"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontFamily: 'var(--font-mono)',
            fontSize: '11px',
            color: 'var(--text-dark-secondary)',
            backgroundColor: 'var(--bg-dark-input)',
            padding: '2px 8px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-dark-medium)',
            height: '28px',
          }}
        >
          <Clock size={12} color="var(--text-dark-muted)" />
          <span style={{ fontWeight: 600, color: 'var(--text-dark-primary)' }}>{time}</span>
          <span style={{ color: 'var(--text-dark-muted)', fontSize: '10px' }}>({utcTime})</span>
        </div>

        {/* Refresh / Sync Button */}
        <button
          onClick={onRefresh}
          className="btn-quant header-refresh"
          title="Refresh All Engine Feeds"
          style={{
            height: '28px',
            padding: '0 10px',
            fontSize: '11px',
            backgroundColor: '#282828',
            borderColor: 'var(--border-dark-strong)',
            color: '#ffffff',
          }}
        >
          <RefreshCw size={11} className={loading ? 'spin' : ''} />
          <span>SYNC</span>
        </button>
      </div>
    </header>
  );
};
