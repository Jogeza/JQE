import React from 'react';
import {
  LayoutDashboard,
  CandlestickChart,
  Briefcase,
  History,
  BrainCircuit,
  ShieldAlert,
  LineChart,
  PlayCircle,
  Terminal,
  Settings as SettingsIcon,
  type LucideIcon,
} from 'lucide-react';

export type TabType =
  | 'overview'
  | 'markets'
  | 'positions'
  | 'trades'
  | 'strategy'
  | 'risk'
  | 'performance'
  | 'backtesting'
  | 'system'
  | 'settings';

interface SidebarProps {
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  openPositionsCount: number;
  riskAllowed?: boolean;
  riskStale?: boolean;
}

interface NavItem {
  id: TabType;
  label: string;
  icon: LucideIcon;
  badge?: string | number;
  badgeType?: 'green' | 'red' | 'neutral' | 'amber';
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  openPositionsCount,
  riskAllowed,
  riskStale,
}) => {
  const navItems: NavItem[] = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard },
    { id: 'markets', label: 'Markets', icon: CandlestickChart },
    {
      id: 'positions',
      label: 'Positions',
      icon: Briefcase,
      badge: openPositionsCount > 0 ? openPositionsCount : undefined,
      badgeType: 'neutral',
    },
    { id: 'trades', label: 'Trades', icon: History },
    { id: 'strategy', label: 'Strategy', icon: BrainCircuit },
    {
      id: 'risk',
      label: 'Risk Control',
      icon: ShieldAlert,
      badge: riskStale ? 'STALE' : riskAllowed === undefined ? 'UNKNOWN' : riskAllowed ? 'OK' : 'LOCK',
      badgeType: riskStale || riskAllowed === undefined ? 'neutral' : riskAllowed ? 'green' : 'red',
    },
    { id: 'performance', label: 'Performance', icon: LineChart },
    { id: 'backtesting', label: 'Backtesting', icon: PlayCircle },
    { id: 'system', label: 'System Logs', icon: Terminal },
    { id: 'settings', label: 'Settings', icon: SettingsIcon },
  ];

  return (
    <aside
      style={{
        width: 'var(--sidebar-width)',
        backgroundColor: 'var(--bg-subtle)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        userSelect: 'none',
        flexShrink: 0,
      }}
    >
      {/* Navigation List */}
      <div style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
        <div
          style={{
            padding: '4px 10px',
            fontSize: '9.5px',
            fontWeight: 700,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: 'var(--text-dim)',
          }}
        >
          Navigation
        </div>

        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;

          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '8px 10px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid',
                borderColor: isActive ? 'var(--border-medium)' : 'transparent',
                backgroundColor: isActive ? 'var(--bg-surface-elevated)' : 'transparent',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontSize: '12px',
                fontWeight: isActive ? 600 : 500,
                textAlign: 'left',
                cursor: 'pointer',
                transition: 'all 0.12s ease',
                width: '100%',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'var(--bg-surface)';
                  e.currentTarget.style.color = 'var(--text-primary)';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = 'var(--text-secondary)';
                }
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Icon
                  size={14}
                  color={isActive ? 'var(--quant-cyan)' : 'currentColor'}
                  style={{ opacity: isActive ? 1 : 0.7 }}
                />
                <span>{item.label}</span>
              </div>

              {item.badge !== undefined && (
                <span
                  className={`badge badge-${item.badgeType || 'neutral'}`}
                  style={{ fontSize: '9.5px', padding: '1px 5px', height: '18px' }}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Terminal Footer Info */}
      <div
        style={{
          padding: '12px',
          borderTop: '1px solid var(--border-subtle)',
          backgroundColor: 'rgba(0,0,0,0.2)',
          fontSize: '10.5px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-muted)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
          <span>STATUS SOURCE:</span>
          <span style={{ color: 'var(--text-secondary)' }}>API TELEMETRY</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>ARCH:</span>
          <span style={{ color: 'var(--quant-cyan)' }}>BROKER-AGNOSTIC</span>
        </div>
      </div>
    </aside>
  );
};
