import React, { useState, useEffect } from 'react';
import {
  Activity,
  Wifi,
  WifiOff,
  RefreshCw,
  Clock,
  Layers
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
        padding: '0 16px',
        userSelect: 'none',
      }}
    >
      {/* Brand & Wordmark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div
            style={{
              width: '26px',
              height: '26px',
              backgroundColor: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-sm)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Activity size={16} color="var(--quant-green)" />
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '13px', letterSpacing: '0.08em', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span>JQE</span>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 500 }}>QUANT CORE</span>
            </div>
          </div>
        </div>

        {/* Environment Badge */}
        <div className={`badge ${getEnvBadgeClass()}`} style={{ height: '22px' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: 'currentColor' }} />
          <span>{env}</span>
          <span style={{ opacity: 0.6, fontSize: '9px' }}>[{broker}]</span>
        </div>

        {/* Quick Instrument Selectors */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '2px 4px' }}>
            <Layers size={13} style={{ marginRight: '4px', color: 'var(--text-muted)' }} />
            <select
              value={selectedSymbol}
              onChange={(e) => onSymbolChange(e.target.value)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11.5px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              <option value="XAUUSD">XAUUSD (Gold)</option>
              <option value="EURUSD">EURUSD</option>
              <option value="GBPUSD">GBPUSD</option>
              <option value="USDJPY">USDJPY</option>
              <option value="BTCUSD">BTCUSD</option>
            </select>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', backgroundColor: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', padding: '2px 4px' }}>
            <select
              value={selectedTimeframe}
              onChange={(e) => onTimeframeChange(e.target.value)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                fontWeight: 600,
                outline: 'none',
                cursor: 'pointer',
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

      {/* Header Right: Status, Clock, Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Connection Indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
          {telemetryStale ? (
            <><WifiOff size={13} color="var(--quant-amber)" /><span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>STALE</span></>
          ) : isConnected === undefined ? (
            <><WifiOff size={13} color="var(--text-muted)" /><span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>UNKNOWN</span></>
          ) : isConnected ? (
            <>
              <Wifi size={13} color="var(--quant-green)" />
              <span style={{ color: 'var(--quant-green)', fontWeight: 600 }}>ONLINE</span>
            </>
          ) : (
            <>
              <WifiOff size={13} color="var(--quant-amber)" />
              <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>DISCONNECTED</span>
            </>
          )}
        </div>

        {/* Clocks (Local & UTC) */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '11.5px',
            color: 'var(--text-secondary)',
            backgroundColor: 'var(--bg-app)',
            padding: '3px 8px',
            borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border-subtle)'
          }}
        >
          <Clock size={12} color="var(--text-muted)" />
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{time}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>({utcTime})</span>
        </div>

        {/* Refresh button */}
        <button
          onClick={onRefresh}
          className="btn-quant"
          title="Refresh All Engine Feeds"
          style={{ height: '28px', padding: '0 8px' }}
        >
          <RefreshCw size={12} className={loading ? 'spin' : ''} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          <span>SYNC</span>
        </button>
      </div>
    </header>
  );
};
