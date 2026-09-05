import React, { useState, useEffect } from 'react';
import {
  Wifi,
  WifiOff,
  RefreshCw,
  Clock,
  Layers,
} from 'lucide-react';
import { SystemStatusResponse } from '../types/api';

interface HeaderProps {
  systemStatus: SystemStatusResponse | null;
  loading: boolean;
  onRefresh: () => void;
  selectedSymbol: string;
  onSymbolChange: (symbol: string) => void;
  selectedTimeframe: string;
  onTimeframeChange: (tf: string) => void;
  telemetryStale?: boolean;
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
}) => {
  const [time, setTime] = useState<string>('');
  const [utcTime, setUtcTime] = useState<string>('');

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

  const env = systemStatus?.environment?.toUpperCase() || 'UNKNOWN';
  const broker = systemStatus?.broker?.toUpperCase() || 'UNKNOWN';
  const isConnected = systemStatus?.broker_connected;

  const getEnvBadgeClass = () => {
    if (env.includes('PROD') || env === 'LIVE') return 'badge-live';
    if (env.includes('DEMO')) return 'badge-demo';
    return 'badge-simulation';
  };

  return (
    <header
      style={{
        height: 'var(--header-height)',
        backgroundColor: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 14px',
        userSelect: 'none',
        flexShrink: 0,
      }}
    >
      {/* Left: Environment & Instrument / Timeframe controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* Environment Badge */}
        <div className={`badge ${getEnvBadgeClass()}`} style={{ height: '22px', fontSize: '9.5px' }}>
          <span style={{ width: '5px', height: '5px', borderRadius: '50%', backgroundColor: 'currentColor' }} />
          <span>{env}</span>
          <span style={{ opacity: 0.65, fontSize: '8.5px', marginLeft: '2px' }}>[{broker}]</span>
        </div>

        {/* Quick Instrument & Timeframe Selectors */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-xs)',
              padding: '1px 6px',
              height: '24px',
            }}
          >
            <Layers size={11} style={{ marginRight: '4px', color: 'var(--text-muted)' }} />
            <select
              value={selectedSymbol}
              onChange={(e) => onSymbolChange(e.target.value)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
                padding: '0',
                height: '100%',
              }}
            >
              <option value="XAUUSD">XAUUSD (Gold)</option>
              <option value="EURUSD">EURUSD</option>
              <option value="GBPUSD">GBPUSD</option>
              <option value="USDJPY">USDJPY</option>
              <option value="BTCUSD">BTCUSD</option>
            </select>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-input)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-xs)',
              padding: '1px 6px',
              height: '24px',
            }}
          >
            <select
              value={selectedTimeframe}
              onChange={(e) => onTimeframeChange(e.target.value)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '10.5px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
                padding: '0',
                height: '100%',
              }}
            >
              <option value="M1">M1</option>
              <option value="M5">M5</option>
              <option value="M15">M15</option>
              <option value="M30">M30</option>
              <option value="H1">H1</option>
              <option value="H4">H4</option>
              <option value="D1">D1</option>
            </select>
          </div>
        </div>
      </div>

      {/* Right: Connection, Clocks, Refresh */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Connection Indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '10.5px', fontFamily: 'var(--font-mono)' }}>
          {telemetryStale ? (
            <>
              <WifiOff size={12} color="var(--quant-amber)" />
              <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>STALE</span>
            </>
          ) : isConnected === undefined ? (
            <>
              <WifiOff size={12} color="var(--text-muted)" />
              <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>UNKNOWN</span>
            </>
          ) : isConnected ? (
            <>
              <Wifi size={12} color="var(--quant-green)" />
              <span style={{ color: 'var(--quant-green)', fontWeight: 600 }}>ONLINE</span>
            </>
          ) : (
            <>
              <WifiOff size={12} color="var(--quant-amber)" />
              <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>DISCONNECTED</span>
            </>
          )}
        </div>

        {/* Clocks (Local & UTC) */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontFamily: 'var(--font-mono)',
            fontSize: '10.5px',
            color: 'var(--text-secondary)',
            backgroundColor: 'var(--bg-input)',
            padding: '2px 7px',
            borderRadius: 'var(--radius-xs)',
            border: '1px solid var(--border-subtle)',
            height: '24px',
          }}
        >
          <Clock size={11} color="var(--text-muted)" />
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{time}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: '9.5px' }}>({utcTime})</span>
        </div>

        {/* Refresh button */}
        <button
          onClick={onRefresh}
          className="btn-quant"
          title="Refresh All Engine Feeds"
          style={{ height: '24px', padding: '0 8px', fontSize: '10px' }}
        >
          <RefreshCw size={10} className={loading ? 'spin' : ''} />
          <span>SYNC</span>
        </button>
      </div>
    </header>
  );
};
