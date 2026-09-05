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
  Activity,
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
  badgeType?: 'green' | 'red' | 'neutral' | 'amber' | 'cyan';
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
    { id: 'backtesting', label: 'Research Terminal', icon: PlayCircle, badge: 'FLAGSHIP', badgeType: 'cyan' },
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
      {/* Brand Header & Navigation List */}
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {/* Brand Bar */}
        <div
          style={{
            height: 'var(--header-height)',
            padding: '0 14px',
            display: 'flex',
            alignItems: 'center',
            gap: '9px',
            borderBottom: '1px solid var(--border-subtle)',
            backgroundColor: 'var(--bg-surface)',
          }}
        >
          <div
            style={{
              width: '22px',
              height: '22px',
              backgroundColor: 'var(--bg-surface-elevated)',
              border: '1px solid var(--border-strong)',
              borderRadius: 'var(--radius-xs)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Activity size={13} color="var(--quant-cyan)" />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <span
              style={{
                fontWeight: 800,
                fontSize: '12.5px',
                letterSpacing: '0.1em',
                color: 'var(--text-primary)',
                lineHeight: 1.1,
              }}
            >
              JQE
            </span>
            <span
              style={{
                fontSize: '9px',
                letterSpacing: '0.06em',
                color: 'var(--text-muted)',
                fontWeight: 600,
                textTransform: 'uppercase',
                fontFamily: 'var(--font-mono)',
              }}
            >
              Quant Terminal
            </span>
          </div>
        </div>

        {/* Nav Items */}
        <div style={{ padding: '8px 6px', display: 'flex', flexDirection: 'column', gap: '2px' }}>
          <div
            style={{
              padding: '6px 8px 4px 8px',
              fontSize: '9px',
              fontWeight: 700,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--text-dim)',
            }}
          >
            Workspaces
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
                  padding: '6px 8px',
                  borderRadius: 'var(--radius-xs)',
                  border: '1px solid',
                  borderColor: isActive ? 'var(--border-medium)' : 'transparent',
                  backgroundColor: isActive ? 'var(--bg-surface-elevated)' : 'transparent',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontSize: '11.5px',
                  fontWeight: isActive ? 600 : 400,
                  textAlign: 'left',
                  cursor: 'pointer',
                  transition: 'all var(--transition-fast)',
                  width: '100%',
                  position: 'relative',
                }}
                onMouseEnter={(e) => {
                  if (!isActive) {
                    e.currentTarget.style.backgroundColor = 'var(--bg-surface-hover)';
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
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                  <Icon
                    size={13}
                    color={isActive ? 'var(--quant-cyan)' : 'currentColor'}
                    style={{ opacity: isActive ? 1 : 0.65, flexShrink: 0 }}
                  />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {item.label}
                  </span>
                </div>

                {item.badge !== undefined && (
                  <span
                    className={`badge badge-${item.badgeType || 'neutral'}`}
                    style={{ fontSize: '9px', padding: '0 4px', height: '16px', lineHeight: '16px' }}
                  >
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Terminal Footer Info */}
      <div
        style={{
          padding: '10px 12px',
          borderTop: '1px solid var(--border-subtle)',
          backgroundColor: 'rgba(0,0,0,0.18)',
          fontSize: '9.5px',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-muted)',
          display: 'flex',
          flexDirection: 'column',
          gap: '3px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>TELEMETRY:</span>
          <span style={{ color: 'var(--text-secondary)' }}>CANONICAL</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <span>ARCHITECTURE:</span>
          <span style={{ color: 'var(--quant-cyan)' }}>BROKER-AGNOSTIC</span>
        </div>
      </div>
    </aside>
  );
};
