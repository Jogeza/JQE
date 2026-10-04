import React, { useEffect, useRef, useState } from 'react';
import {
  LayoutDashboard,
  LayoutGrid,
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
  ListChecks,
  Activity,
  Globe,
  Moon,
  Sun,
  type LucideIcon,
} from 'lucide-react';
import { weltradeReferralUrl } from '../auth/supabase';

export type TabType =
  | 'workspace'
  | 'overview'
  | 'markets'
  | 'syntx'
  | 'watchlist'
  | 'positions'
  | 'trades'
  | 'strategy'
  | 'risk'
  | 'performance'
  | 'backtesting'
  | 'system'
  | 'settings';

interface SidebarProps {
  authenticated?: boolean;
  activeTab: TabType;
  onTabChange: (tab: TabType) => void;
  openPositionsCount?: number;
  riskAllowed?: boolean;
  riskStale?: boolean;
  siteTheme?: 'light' | 'dark';
  onToggleTheme?: () => void;
}

interface NavItem {
  id: TabType;
  label: string;
  icon: LucideIcon;
  group: 'Overview' | 'Markets' | 'Analysis' | 'System';
  badge?: string | number;
  badgeType?: 'green' | 'red' | 'neutral' | 'amber' | 'cyan';
}

export const Sidebar: React.FC<SidebarProps> = ({
  authenticated = false,
  activeTab,
  onTabChange,
  openPositionsCount,
  riskAllowed,
  riskStale,
  siteTheme = 'light',
  onToggleTheme,
}) => {
  const [collapsed, setCollapsed] = useState(() =>
    window.matchMedia('(min-width: 769px) and (max-width: 1200px)').matches
  );
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawer = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLButtonElement>(null);

  const navItems: NavItem[] = [
    { id: 'workspace',   label: 'Workspace',    icon: LayoutGrid,       group: 'Overview' },
    { id: 'overview',    label: 'Overview',     icon: LayoutDashboard,  group: 'Overview' },
    { id: 'markets',     label: 'Markets',      icon: CandlestickChart, group: 'Markets'      },
    { id: 'syntx',       label: 'SyntX Markets',icon: Globe,            group: 'Markets'      },
    { id: 'watchlist',   label: 'Watchlist',    icon: ListChecks,       group: 'Markets'      },
    {
      id: 'positions', label: 'Positions', icon: Briefcase, group: 'Analysis',
      badge: openPositionsCount !== undefined && openPositionsCount > 0 ? openPositionsCount : undefined,
      badgeType: 'cyan',
    },
    { id: 'trades',      label: 'Trades',       icon: History,          group: 'Analysis'     },
    { id: 'strategy',    label: 'Strategy',     icon: BrainCircuit,     group: 'Analysis'     },
    {
      id: 'risk', label: 'Risk Control', icon: ShieldAlert, group: 'Analysis',
      badge: riskStale ? 'STALE' : riskAllowed === undefined ? 'UNKNOWN' : riskAllowed ? 'OK' : undefined,
      badgeType: riskStale ? 'amber' : riskAllowed ? 'green' : 'neutral',
    },
    { id: 'performance', label: 'Performance',  icon: LineChart,        group: 'Analysis'     },
    { id: 'backtesting', label: 'Research',     icon: PlayCircle,       group: 'Analysis'     },
    { id: 'system',      label: 'System Logs',  icon: Terminal,         group: 'System'       },
    { id: 'settings',    label: 'Settings',     icon: SettingsIcon,     group: 'System'       },
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
    <nav aria-label={mobile ? 'Mobile navigation' : 'Main navigation'} className="sidebar-nav">
      {navItems.map((item, index) => {
        const Icon = item.icon;
        const isActive = activeTab === item.id;
        return (
          <React.Fragment key={item.id}>
            {(index === 0 || navItems[index - 1].group !== item.group) && (
              <p className="nav-section-label">{item.group}</p>
            )}
            <button
              className={`nav-link${isActive ? ' active' : ''}`}
              aria-current={isActive ? 'page' : undefined}
              aria-label={`${item.label}${item.badge !== undefined ? ', ' + item.badge : ''}`}
              title={collapsed && !mobile ? item.label : `${item.label}${item.badge !== undefined ? ' · ' + item.badge : ''}`}
              onClick={() => { onTabChange(item.id); setDrawerOpen(false); }}
            >
              <Icon size={17} aria-hidden="true" className="nav-icon" />
              <span className="nav-label">{item.label}</span>
              {item.badge !== undefined && (
                <span className={`nav-badge badge badge-${item.badgeType || 'neutral'}`}>
                  {item.badge}
                </span>
              )}
            </button>
          </React.Fragment>
        );
      })}
    </nav>
  );

  const pageTitle = navItems.find(item => item.id === activeTab)?.label ?? 'Workspace';

  return (
    <div className={`sidebar-surfaces${authenticated ? " authenticated" : ""}`} aria-label={authenticated ? "Authenticated JQE account" : undefined}>
      {/* ── Desktop sidebar ─────────────────────────────────────── */}
      <aside className={`desktop-sidebar${collapsed ? ' collapsed' : ''}`} aria-label="JQE Navigation">

        <div className="sidebar-brand">
          <div className="brand-lockup"><span className="legacy-jqe-mark"><Activity size={21} aria-hidden="true" /></span><span className="jqe-mark">JQE<span>®</span></span></div>
          <small>Research &amp; perspective</small>
          <a className="weltrade-logo-link" href={weltradeReferralUrl} target="_blank" rel="noopener noreferrer" aria-label="Register with Weltrade, opens in a new tab">
            <img className="weltrade-logo" src="/weltrade-logo.svg" alt="" width="136" height="28" />
          </a>
        </div>

        {navigation()}

        {/* Footer */}
        <footer className="sidebar-footer">
          <button className="site-theme-toggle" type="button" onClick={onToggleTheme}
            aria-label={siteTheme === 'dark' ? 'Switch site to light mode' : 'Switch site to dark mode'}
            aria-pressed={siteTheme === 'dark'} title={siteTheme === 'dark' ? 'Light mode' : 'Dark mode'}>
            {siteTheme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            <span className="nav-label">{siteTheme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
          </button>
          {!collapsed && (
            <div className="sidebar-metadata">
              <span className="sidebar-meta-provider">Weltrade · MT5</span>
              <span className="sidebar-meta-mode">demo · observation only</span>
            </div>
          )}
          <button
            className="nav-collapse"
            onClick={() => setCollapsed(v => !v)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            <span className="nav-label">Collapse</span>
          </button>
        </footer>
      </aside>

      {/* ── Mobile header ────────────────────────────────────────── */}
      <div className="mobile-navigation-header">
        <span className="mobile-brand-lockup">
          <span className="legacy-jqe-mark"><Activity size={17} aria-hidden="true" /></span><span className="jqe-mark">JQE</span>
        </span>
        <strong className="mobile-page-title">{pageTitle}</strong>
        <button type="button" className="site-theme-toggle mobile-theme-toggle" onClick={onToggleTheme}
          aria-label={siteTheme === 'dark' ? 'Switch site to light mode' : 'Switch site to dark mode'}
          aria-pressed={siteTheme === 'dark'}>
          {siteTheme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <button
          ref={opener}
          className="icon-button"
          aria-label="Open navigation"
          aria-haspopup="dialog"
          aria-expanded={drawerOpen}
          onClick={() => setDrawerOpen(true)}
        >
          <Menu size={22} />
        </button>
      </div>

      {/* ── Mobile drawer ────────────────────────────────────────── */}
      <dialog
        ref={drawer}
        className="mobile-nav-drawer"
        aria-label="Navigation"
        onCancel={() => setDrawerOpen(false)}
        onClose={() => setDrawerOpen(false)}
        onClick={event => {
          if (event.target === event.currentTarget) {
            const bounds = event.currentTarget.getBoundingClientRect();
            if (event.clientX > bounds.right || event.clientX < bounds.left) setDrawerOpen(false);
          }
        }}
      >
        <div className="drawer-heading">
          <span className="brand-lockup"><span className="legacy-jqe-mark"><Activity size={20} aria-hidden="true" /></span><span className="jqe-mark">JQE</span></span>
          <button
            autoFocus
            className="icon-button"
            aria-label="Close navigation"
            onClick={() => setDrawerOpen(false)}
          >
            <X size={22} />
          </button>
        </div>
        {navigation(true)}
        <div className="sidebar-metadata" style={{ padding: '12px 16px', borderTop: '1px solid var(--border-dark)' }}>
          <a className="weltrade-logo-link" href={weltradeReferralUrl} target="_blank" rel="noopener noreferrer" aria-label="Register with Weltrade, opens in a new tab">
            <img className="weltrade-logo" src="/weltrade-logo.svg" alt="" width="136" height="28" />
          </a>
          <span className="sidebar-meta-provider">Weltrade · MT5 demo</span>
        </div>
      </dialog>
    </div>
  );
};
