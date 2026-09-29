import React from 'react';
import type { AssistantStatusResponse, BrokerStatusResponse, NotificationStatusResponse, ResourceState } from '../types/api';
import type { TabType } from '../components/Sidebar';

interface Props {
  assistant: ResourceState<AssistantStatusResponse>;
  notifications: ResourceState<NotificationStatusResponse>;
  broker: ResourceState<BrokerStatusResponse>;
  onNavigate: (tab: TabType) => void;
}

export const SettingsPage: React.FC<Props> = ({ assistant, notifications, broker, onNavigate }) => {
  const status = broker.data;
  const weltrade = status?.brokers.find(item => item.broker === 'weltrade');
  const connection = broker.error || !status ? 'Unavailable' : status.connected ? 'Connected' : 'Disconnected';
  const verifiedAt = weltrade?.demo_guard_verified_at || status?.last_verified_at;
  const formattedVerifiedAt = (() => {
    if (!verifiedAt) return 'Not observed';
    const date = new Date(verifiedAt);
    if (Number.isNaN(date.getTime())) return verifiedAt;
    return `${new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }).format(date)} UTC`;
  })();

  return <main className="dashboard-page-container settings-page">
    <div className="editorial-heading"><div><span className="editorial-kicker">Workspace configuration</span><h1>Settings<span>.</span></h1></div><p>Connection and service status<small>Local configuration · read only</small></p></div>
    <div className="settings-grid">
      <section className="settings-card settings-broker-card" aria-label="Weltrade connection settings">
        <h2>Weltrade connection</h2>
        <p>Synthetic indices through the local MetaTrader 5 terminal. This installation supports the demo account only.</p>
        <dl className="settings-broker-facts">
          <div><dt>Broker</dt><dd>{weltrade?.name ?? status?.active_broker ?? 'Weltrade'}</dd></div>
          <div><dt>Transport</dt><dd>Local MT5 terminal</dd></div>
          <div><dt>Account mode</dt><dd>{(weltrade?.account_trade_mode ?? status?.account_trade_mode ?? 'Demo only · unverified').toUpperCase()}</dd></div>
          <div><dt>Connection</dt><dd>{connection}</dd></div>
          <div><dt>Availability</dt><dd>{weltrade ? weltrade.is_available ? 'Available' : 'Unavailable' : 'Unavailable'}</dd></div>
          <div><dt>Configuration</dt><dd>{weltrade ? weltrade.is_configured ? 'Configured' : 'Not configured' : 'Unavailable'}</dd></div>
          <div><dt>Demo verification</dt><dd>{weltrade?.demo_guard_status ?? status?.identity_state ?? 'Unavailable'}</dd></div>
          <div><dt>Last verified</dt><dd>{formattedVerifiedAt}</dd></div>
          <div><dt>Account ID</dt><dd>{weltrade?.account_id_masked ?? status?.account_id_masked ?? '—'}</dd></div>
          <div><dt>Server</dt><dd>{weltrade?.account_server ?? status?.account_server ?? '—'}</dd></div>
          <div><dt>Currency</dt><dd>{weltrade?.account_currency ?? status?.account_currency ?? '—'}</dd></div>
          <div><dt>Broker execution</dt><dd>{status?.broker_execution_enabled === true ? 'Enabled · guarded demo' : status?.broker_execution_enabled === false ? 'Disabled' : 'Unavailable'}</dd></div>
          <div><dt>Safety authorization</dt><dd>{status?.execution_authorization?.replace(/_/g, ' ') ?? 'Unavailable'}</dd></div>
          <div><dt>Emergency stop</dt><dd>{status?.emergency_stop_state ?? 'Unavailable'}</dd></div>
          <div><dt>Unresolved orders</dt><dd>{status?.unresolved_intent_count ?? 'Unavailable'}</dd></div>
        </dl>
        {(broker.stale || broker.error || weltrade?.error_message || weltrade?.notes) && <small className="settings-broker-note">
          {broker.stale && 'Broker status is stale. '}{broker.error && `Status error: ${broker.error}. `}{weltrade?.error_message}{weltrade?.notes && ` ${weltrade.notes}`}
        </small>}
        <small>Account identifiers are masked. Status is informational; it does not authorize a broker order.</small>
      </section>

      <section className="settings-card"><h2>JQE AI</h2><p>Generic prompts only. Workspace evidence stays local. Each question is independent.</p><dl><div><dt>Configuration</dt><dd>{assistant.error || !assistant.data ? 'Unavailable' : assistant.data.state === 'READY' ? 'Configured' : assistant.data.state}</dd></div><div><dt>Provider</dt><dd>{assistant.data?.provider ?? 'Unavailable'}</dd></div><div><dt>Model</dt><dd>{assistant.data?.model ?? 'Unavailable'}</dd></div></dl><small>Provider billing and access are checked on a question. Keys stay in the local backend environment.</small><button type="button" onClick={() => onNavigate('workspace')}>Open JQE AI in Workspace</button></section>
      <section className="settings-card"><h2>Notifications</h2><p>Use the bell for current system alerts and notification-channel status.</p><dl>{notifications.data?.channels?.map(channel => <div key={channel.channel}><dt>{channel.channel}</dt><dd>{channel.state}</dd></div>) ?? <div><dt>Channels</dt><dd>Unavailable</dd></div>}</dl><small>Channel configuration does not prove delivery. Status checks do not send messages.</small></section>
      <section className="settings-card"><h2>Risk and diagnostics</h2><p>Review account limits, stale evidence and service health in their dedicated pages.</p><div className="settings-links"><button type="button" onClick={() => onNavigate('risk')}>Risk Control</button><button type="button" onClick={() => onNavigate('system')}>System Logs</button></div><small>Changing interface settings never authorizes a broker order.</small></section>
    </div>
  </main>;
};
