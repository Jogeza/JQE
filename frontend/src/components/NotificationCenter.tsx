import React, { useEffect, useRef, useState } from 'react';
import { Bell, X } from 'lucide-react';
import type { ActiveMarketAnalysisResponse, BrokerStatusResponse, ExecutionSafetyResponse, NotificationStatusResponse, ResourceState } from '../types/api';
import { formatAge, withinAge, WORKSPACE_FRESHNESS_THRESHOLDS_MS } from '../pages/workspaceEvidence';
import './NotificationCenter.css';

interface Props {
  notifications: ResourceState<NotificationStatusResponse>;
  safety: ResourceState<ExecutionSafetyResponse>;
  broker: ResourceState<BrokerStatusResponse>;
  apiError: string | null;
  market: ResourceState<ActiveMarketAnalysisResponse>;
  resourceErrors?: { title: string; detail: string }[];
  hosted?: boolean;
}

export const NotificationCenter: React.FC<Props> = ({ notifications, safety, broker, apiError, market, resourceErrors = [], hosted = false }) => {
  const [open, setOpen] = useState(false);
  const [actionIssues, setActionIssues] = useState<{ title: string; detail: string }[]>([]);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const receive = (event: Event) => {
      const issue = (event as CustomEvent).detail;
      if (!issue || typeof issue.title !== 'string' || typeof issue.detail !== 'string') return;
      setActionIssues(previous => [...previous.filter(item => item.title !== issue.title), issue].slice(-20));
    };
    window.addEventListener('jqe:notification', receive);
    return () => window.removeEventListener('jqe:notification', receive);
  }, []);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    const closeOutside = (event: MouseEvent) => { if (root.current && !root.current.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('keydown', closeOnEscape);
    document.addEventListener('mousedown', closeOutside);
    return () => { document.removeEventListener('keydown', closeOnEscape); document.removeEventListener('mousedown', closeOutside); };
  }, [open]);

  const issues = [
    ...actionIssues,
    ...resourceErrors,
    ...(apiError ? [{ title: 'Data feed issue', detail: apiError }] : []),
    ...(!broker.data || broker.error || (broker.stale && !broker.loading) || !broker.data.connected
      ? [{ title: 'Broker connection', detail: broker.error || 'Weltrade demo connection is unavailable or stale.' }] : []),
    ...(safety.error || (safety.stale && !safety.loading) || !safety.data || safety.data.observation_state !== 'OBSERVED'
      ? [{ title: 'Execution safety evidence', detail: safety.error || 'Safety evidence is unavailable or stale. Execution remains blocked.' }] : []),
    ...(safety.data?.emergency_stop_state === 'ACTIVE'
      ? [{ title: 'Emergency stop active', detail: 'New order submissions are blocked.' }] : []),
    ...(notifications.error
      ? [{ title: 'Notification status', detail: notifications.error }] : []),
  ];
  const identity = broker.data?.active_broker_identity;
  const live = broker.data?.live_connection_state === 'CONNECTED';
  const verified = identity?.broker === broker.data?.active_broker && identity?.demo_guard_passed === true && !!identity?.verified_at && withinAge(identity.verified_at, WORKSPACE_FRESHNESS_THRESHOLDS_MS.demoVerification) && live;
  const marketFreshness = market.error || market.stale ? 'Unavailable - last request failed' : market.data?.context?.freshness_state === 'FRESH' ? 'Fresh - closed candles' : market.data?.context?.freshness_state ?? 'Unavailable';
  const channels = notifications.data?.channels ?? [];

  return <div className="notification-center" ref={root}>
    <button ref={trigger} type="button" className="notification-trigger" aria-label={`Notifications${issues.length ? `, ${issues.length} need attention` : ''}`} aria-expanded={open} onClick={() => setOpen(value => !value)}>
      <Bell size={17} aria-hidden="true" />
      {issues.length > 0 && <span className="notification-count">{issues.length}</span>}
    </button>
    {open && <section className="notification-panel" role="dialog" aria-label="System notifications">
      <div className="notification-heading"><div><strong>Notifications</strong><small>Current system evidence</small></div><button type="button" aria-label="Close notifications" onClick={() => { setOpen(false); trigger.current?.focus(); }}><X size={16} /></button></div>
      <>{hosted && <p className="notification-empty">Authenticated research access. Hosted MT5 data is unavailable; automated execution is excluded.</p>}</>
      <div className="notification-facts" aria-label="Workspace status"><strong>Workspace status</strong><dl>
        <div><dt>Live broker connection</dt><dd>{broker.data?.live_connection_state === 'CONNECTED' ? 'Yes - live' : broker.data?.live_connection_state === 'DISCONNECTED' ? 'No - live' : 'Unavailable'}</dd></div>
        <div><dt>Demo verified</dt><dd>{verified ? `Yes - age ${formatAge(identity?.verified_at)}` : 'Unverified'}</dd></div>
        <div><dt>Market data freshness</dt><dd>{marketFreshness}</dd></div>
        <div><dt>Broker execution</dt><dd>{broker.data?.broker_execution_enabled === true ? 'Enabled - guarded demo only' : broker.data?.broker_execution_enabled === false ? 'Disabled' : 'Unavailable'}</dd></div>
      </dl><small>Current evidence - updates with the dashboard</small></div>
      {issues.length ? <ul className="notification-list">{issues.map(item => <li key={item.title} className="notification-issue"><strong>{item.title}</strong><span>{item.detail}</span></li>)}</ul>
        : <p className="notification-empty">No current system alerts.</p>}
      <div className="notification-channels"><strong>Channels</strong>
        {notifications.data ? <ul>{channels.map(channel => <li key={channel.channel}><span>{channel.channel}</span><strong>{channel.state}</strong></li>)}</ul>
          : <p>Channel status unavailable.</p>}
        <small>Configuration status only; delivery reachability is not tested.</small>
      </div>
    </section>}
  </div>;
};
