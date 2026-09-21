import React, { useState } from 'react';
import { ListChecks, Plus, Trash2, ShieldAlert, CheckCircle2, Clock, AlertCircle, RefreshCw } from 'lucide-react';
import type { WatchlistItemDTO, WatchlistCapUsageDTO } from '../types/api';
import { jqeApi } from '../services/api';

interface WatchlistPageProps {
  watchlist?: WatchlistItemDTO[] | null;
  capUsage?: WatchlistCapUsageDTO[] | null;
  loading: boolean;
  onRefresh: () => void;
}

export const WatchlistPage: React.FC<WatchlistPageProps> = ({
  watchlist,
  capUsage,
  loading,
  onRefresh,
}) => {
  const [newSymbol, setNewSymbol] = useState('');
  const [newTimeframe, setNewTimeframe] = useState('H1');
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const items = watchlist ?? [];
  const caps = capUsage ?? [];

  // Map cap usage by symbol
  const capMap = new Map<string, WatchlistCapUsageDTO>();
  for (const c of caps) {
    capMap.set(c.symbol.toUpperCase(), c);
  }

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanSymbol = newSymbol.trim().toUpperCase();
    if (!cleanSymbol) return;

    setSubmitting(true);
    setActionError(null);
    try {
      await jqeApi.addToWatchlist(cleanSymbol, newTimeframe);
      setNewSymbol('');
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to add instrument');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (symbol: string, timeframe?: string) => {
    if (!window.confirm(`Remove ${symbol} (${timeframe || 'H1'}) from watchlist?`)) return;

    setSubmitting(true);
    setActionError(null);
    try {
      await jqeApi.deleteFromWatchlist(symbol, timeframe);
      onRefresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to delete instrument');
    } finally {
      setSubmitting(false);
    }
  };

  const formatUtcTime = (isoString: string | undefined): string => {
    if (!isoString) return '—';
    try {
      const d = new Date(isoString);
      if (Number.isNaN(d.getTime())) return isoString;
      return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
    } catch {
      return isoString;
    }
  };

  return (
    <div className="dashboard-page-container watchlist-page">
      <div className="editorial-heading">
        <div>
          <span className="editorial-kicker">Multi-Instrument Universe & Risk Guard</span>
          <h1>Durable Watchlist<span>.</span></h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={onRefresh}
            disabled={loading || submitting}
            className="btn-quant"
            style={{ fontSize: '11px', padding: '4px 10px', height: '26px' }}
          >
            <RefreshCw size={11} className={loading ? 'spin' : ''} />
            REFRESH
          </button>
        </div>
      </div>

      {actionError && (
        <div
          style={{
            backgroundColor: 'var(--quant-red-subtle)',
            border: '1px solid var(--quant-red-border)',
            borderRadius: 'var(--radius-sm)',
            padding: '8px 12px',
            marginBottom: '14px',
            color: 'var(--quant-red)',
            fontSize: '11px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <AlertCircle size={14} />
          <span>{actionError}</span>
        </div>
      )}

      {/* Inline Add Instrument Form */}
      <div className="quant-panel" style={{ marginBottom: '16px' }}>
        <div className="quant-panel-header">
          <div className="quant-panel-title">
            <Plus size={14} color="var(--quant-cyan)" />
            <span>Add Instrument to Universe</span>
          </div>
          <span className="badge badge-neutral">TELEGRAM SYNCED</span>
        </div>
        <div className="quant-panel-body" style={{ padding: '14px' }}>
          <form onSubmit={handleAdd} style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="text"
              placeholder="e.g. R_75, FX VOL 20, PAINX 400"
              value={newSymbol}
              onChange={e => setNewSymbol(e.target.value)}
              disabled={submitting}
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-medium)',
                borderRadius: 'var(--radius-sm)',
                padding: '6px 12px',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                minWidth: '220px',
                flex: 1,
              }}
            />
            <select
              value={newTimeframe}
              onChange={e => setNewTimeframe(e.target.value)}
              disabled={submitting}
              style={{
                backgroundColor: 'var(--bg-surface)',
                border: '1px solid var(--border-medium)',
                borderRadius: 'var(--radius-sm)',
                padding: '6px 10px',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
              }}
            >
              <option value="H1">H1</option>
              <option value="M15">M15</option>
              <option value="M5">M5</option>
              <option value="M1">M1</option>
              <option value="H4">H4</option>
              <option value="D1">D1</option>
            </select>
            <button
              type="submit"
              disabled={submitting || !newSymbol.trim()}
              className="btn-quant"
              style={{ fontSize: '11px', padding: '6px 14px', height: '32px' }}
            >
              <Plus size={12} /> ADD INSTRUMENT
            </button>
          </form>
        </div>
      </div>

      {/* Instruments Grid & Cap Usage */}
      <div className="quant-panel">
        <div className="quant-panel-header">
          <div className="quant-panel-title">
            <ListChecks size={14} color="var(--quant-cyan)" />
            <span>Watched Instruments & Daily Instrument Caps</span>
          </div>
          <span className="badge badge-cyan">{items.length} ACTIVE</span>
        </div>

        <div className="quant-panel-body" style={{ padding: '16px' }}>
          {items.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
              Watchlist is empty. Add instruments above or via Telegram /add command.
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
                gap: '14px',
              }}
            >
              {items.map(item => {
                const cap = capMap.get(item.symbol.toUpperCase());
                const dailyCount = cap ? cap.daily_count : 0;
                const dailyLimit = cap ? cap.daily_limit : 20;
                const isCapped = dailyCount >= dailyLimit;
                const isNearCap = !isCapped && dailyCount >= dailyLimit * 0.8;
                const percent = Math.min(100, Math.round((dailyCount / dailyLimit) * 100));
                const resetAtFormatted = cap ? formatUtcTime(cap.reset_at) : 'Tomorrow 00:00 UTC';

                return (
                  <div
                    key={item.scope}
                    style={{
                      backgroundColor: 'var(--bg-surface)',
                      border: `1px solid ${isCapped ? 'var(--quant-red)' : isNearCap ? 'var(--quant-amber)' : 'var(--border-subtle)'}`,
                      borderRadius: 'var(--radius-sm)',
                      padding: '14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '10px',
                    }}
                  >
                    {/* Card Header: Symbol, Timeframe & Remove */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <span className="font-mono" style={{ fontSize: '15px', fontWeight: 800, color: 'var(--text-primary)' }}>
                          {item.symbol}
                        </span>
                        <span className="badge badge-neutral" style={{ marginLeft: '8px', fontSize: '9px' }}>
                          {item.timeframe}
                        </span>
                      </div>
                      <button
                        onClick={() => handleDelete(item.symbol, item.timeframe)}
                        disabled={submitting}
                        title="Remove from watchlist"
                        className="btn-quant"
                        style={{ padding: '3px 6px', height: '22px', color: 'var(--quant-red)' }}
                      >
                        <Trash2 size={11} />
                      </button>
                    </div>

                    {/* Cap Progress Bar */}
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', marginBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>DAILY SUBMISSION CAP</span>
                        <span className="font-mono" style={{ fontWeight: 700, color: isCapped ? 'var(--quant-red)' : isNearCap ? 'var(--quant-amber)' : 'var(--text-primary)' }}>
                          {dailyCount} / {dailyLimit} trades ({percent}%)
                        </span>
                      </div>
                      <div
                        style={{
                          height: '6px',
                          backgroundColor: 'rgba(255, 255, 255, 0.08)',
                          borderRadius: '99px',
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          style={{
                            width: `${percent}%`,
                            height: '100%',
                            backgroundColor: isCapped ? 'var(--quant-red)' : isNearCap ? 'var(--quant-amber)' : 'var(--quant-cyan)',
                            transition: 'width 0.3s ease',
                          }}
                        />
                      </div>
                    </div>

                    {/* Capped Warning or Available Badge */}
                    {isCapped ? (
                      <div
                        style={{
                          backgroundColor: 'rgba(255, 95, 109, 0.12)',
                          border: '1px solid var(--quant-red-border)',
                          borderRadius: 'var(--radius-sm)',
                          padding: '8px 10px',
                          fontSize: '10.5px',
                          color: 'var(--quant-red)',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                        }}
                      >
                        <ShieldAlert size={14} style={{ flexShrink: 0 }} />
                        <span>
                          <strong>Daily cap reached</strong> — submissions blocked until {resetAtFormatted}
                        </span>
                      </div>
                    ) : (
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: '10px',
                          color: 'var(--text-secondary)',
                          marginTop: 'auto',
                        }}
                      >
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: 'var(--status-green)', fontWeight: 600 }}>
                          <CheckCircle2 size={12} />
                          {dailyLimit - dailyCount} trades available
                        </span>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', color: 'var(--text-muted)' }}>
                          <Clock size={10} /> Reset: {resetAtFormatted}
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
