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
      {/* Left Group: Environment & Market / Timeframe Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* Environment Badge */}
        <div className={`badge ${getEnvBadgeClass()}`} style={{ height: '24px', fontSize: '10px' }}>
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
              <option value="XAUUSD" style={{ background: '#171a22', color: '#f8fafc' }}>XAUUSD (Gold)</option>
              <option value="EURUSD" style={{ background: '#171a22', color: '#f8fafc' }}>EURUSD</option>
              <option value="GBPUSD" style={{ background: '#171a22', color: '#f8fafc' }}>GBPUSD</option>
              <option value="USDJPY" style={{ background: '#171a22', color: '#f8fafc' }}>USDJPY</option>
              <option value="BTCUSD" style={{ background: '#171a22', color: '#f8fafc' }}>BTCUSD</option>
            </select>
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
            <option value="M1" style={{ background: '#171a22', color: '#f8fafc' }}>M1</option>
            <option value="M5" style={{ background: '#171a22', color: '#f8fafc' }}>M5</option>
            <option value="M15" style={{ background: '#171a22', color: '#f8fafc' }}>M15</option>
            <option value="M30" style={{ background: '#171a22', color: '#f8fafc' }}>M30</option>
            <option value="H1" style={{ background: '#171a22', color: '#f8fafc' }}>H1</option>
            <option value="H4" style={{ background: '#171a22', color: '#f8fafc' }}>H4</option>
            <option value="D1" style={{ background: '#171a22', color: '#f8fafc' }}>D1</option>
          </select>
        </div>
      </div>

      {/* Right Group: Connection, Clocks, Refresh */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
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
            backgroundColor: 'rgba(0, 0, 0, 0.2)',
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
              <span style={{ color: 'var(--quant-green)', fontWeight: 600 }}>ONLINE</span>
            </>
          ) : (
            <>
              <WifiOff size={12} color="var(--quant-amber)" />
              <span style={{ color: 'var(--quant-amber)', fontWeight: 600 }}>DISCONNECTED</span>
            </>
          )}
        </div>

        {/* Grouped Clocks (Local & UTC) */}
        <div
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
          className="btn-quant"
          title="Refresh All Engine Feeds"
          style={{
            height: '28px',
            padding: '0 10px',
            fontSize: '11px',
            backgroundColor: '#202532',
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
