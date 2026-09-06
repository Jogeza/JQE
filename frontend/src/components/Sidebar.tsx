import React, { useEffect, useRef, useState } from 'react';
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
  PanelLeftClose,
  PanelLeftOpen,
  Menu,
  X,
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
  const [collapsed, setCollapsed] = useState(() => window.matchMedia('(min-width: 769px) and (max-width: 1200px)').matches);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const navItems: NavItem[] = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard },
    { id: 'markets', label: 'Markets', icon: CandlestickChart },
    { id: 'positions', label: 'Positions', icon: Briefcase, badge: openPositionsCount > 0 ? openPositionsCount : undefined },
    { id: 'trades', label: 'Trades', icon: History },
    { id: 'strategy', label: 'Strategy', icon: BrainCircuit },
    { id: 'risk', label: 'Risk Control', icon: ShieldAlert, badge: riskStale ? 'STALE' : riskAllowed === undefined ? 'UNKNOWN' : riskAllowed ? 'OK' : 'LOCK' },
    { id: 'performance', label: 'Performance', icon: LineChart },
    { id: 'backtesting', label: 'Research', icon: PlayCircle },
    { id: 'system', label: 'System Logs', icon: Terminal },
    { id: 'settings', label: 'Settings', icon: SettingsIcon },
  ];
  useEffect(() => {
    if (!drawerOpen) return;
    const dialog = drawer.current;
    if (dialog && !dialog.open) dialog.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const media = window.matchMedia('(min-width: 769px)');
    const closeOnDesktop = () => { if (media.matches) setDrawerOpen(false); };
    media.addEventListener('change', closeOnDesktop);
    return () => {
      media.removeEventListener('change', closeOnDesktop);
      if (dialog?.open) dialog.close();
      document.body.style.overflow = previousOverflow;
      opener.current?.focus();
    };
  }, [drawerOpen]);
  const navigation = (mobile = false) => (
    <nav aria-label={mobile ? 'Mobile navigation' : 'Main navigation'}>
      <p className="nav-section-label">Workspace</p>
      {navItems.map((item, index) => {
        const Icon = item.icon;
        return <React.Fragment key={item.id}>
          {index === 8 && <p className="nav-section-label">System</p>}
          <button className={activeTab === item.id ? 'nav-link active' : 'nav-link'}
            aria-current={activeTab === item.id ? 'page' : undefined}
            aria-label={`${item.label}${item.badge !== undefined ? ', ' + item.badge : ''}`}
            title={`${item.label}${item.badge !== undefined ? ' · ' + item.badge : ''}`}
            onClick={() => { onTabChange(item.id); setDrawerOpen(false); }}>
            <Icon size={19} aria-hidden="true" />
            <span className="nav-label">{item.label}</span>
            {item.badge !== undefined && <span className={`nav-badge badge badge-${item.badgeType || 'neutral'}`}>{item.badge}</span>}
          </button>
        </React.Fragment>;
      })}
    </nav>
  );
  const pageTitle = navItems.find(item => item.id === activeTab)?.label ?? 'Workspace';

  return <>
    <aside className={`desktop-sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-brand"><div className="brand-lockup"><span className="legacy-jqe-mark"><Activity size={21} aria-hidden="true" /></span><span className="jqe-mark">JQE<span>®</span></span></div><small>Research & perspective</small></div>
      {navigation()}
      <footer className="sidebar-footer">
        <div className="sidebar-metadata"><strong>Independent by design.</strong><span>Broker-agnostic architecture</span><span>Canonical telemetry</span></div>
        <button className="nav-collapse" onClick={() => setCollapsed(value => !value)}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={!collapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          <span className="nav-label">Collapse navigation</span>
        </button>
      </footer>
    </aside>
    <div className="mobile-navigation-header">
      <span className="mobile-brand-lockup"><span className="legacy-jqe-mark"><Activity size={17} aria-hidden="true" /></span><span className="jqe-mark">JQE</span></span><strong>{pageTitle}</strong>
      <button ref={opener} className="icon-button" aria-label="Open navigation" aria-haspopup="dialog"
        aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><Menu size={22} /></button>
    </div>
    <dialog ref={drawer} className="mobile-nav-drawer" aria-label="Navigation"
      onCancel={() => setDrawerOpen(false)} onClose={() => setDrawerOpen(false)}
      onClick={event => { if (event.target === event.currentTarget) {
        const bounds = event.currentTarget.getBoundingClientRect();
        if (event.clientX > bounds.right || event.clientX < bounds.left) setDrawerOpen(false);
      } }}>
      <div className="drawer-heading"><span className="brand-lockup"><span className="legacy-jqe-mark"><Activity size={20} aria-hidden="true" /></span><span className="jqe-mark">JQE</span></span>
        <button autoFocus className="icon-button" aria-label="Close navigation" onClick={() => setDrawerOpen(false)}><X size={22} /></button>
      </div>
      {navigation(true)}
      <p className="drawer-note">Financial research. Clear perspective.</p>
    </dialog>
  </>;
};
