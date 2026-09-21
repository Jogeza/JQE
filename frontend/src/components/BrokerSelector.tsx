import React, { useState } from 'react';
import { AlertTriangle, Loader2, Plug } from 'lucide-react';
import type { BrokerItemStatusDTO, BrokerStatusResponse } from '../types/api';

const BROKER_ORDER = ['mt5', 'weltrade', 'deriv', 'simulation'] as const;

const BROKER_LABELS: Record<string, string> = {
  mt5: 'MT5 Demo',
  weltrade: 'Weltrade Demo',
  deriv: 'Deriv Demo',
  simulation: 'Simulation (Test Only)',
};

interface BrokerSelectorProps {
  brokerStatus: BrokerStatusResponse | null;
  onSelectBroker: (broker: string) => Promise<void>;
}

export const BrokerSelector: React.FC<BrokerSelectorProps> = ({
  brokerStatus,
  onSelectBroker,
}) => {
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeBroker = brokerStatus?.active_broker ?? '';
  const globallyBlocked = brokerStatus !== null && brokerStatus.can_switch === false;
  const blockedReason = brokerStatus?.switch_blocked_reason ?? null;

  const itemFor = (broker: string): BrokerItemStatusDTO | null =>
    brokerStatus?.brokers.find(b => b.broker === broker) ?? null;

  const handleChange = async (event: React.ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    if (!next || next === activeBroker || switching) return;
    setSwitching(true);
    setError(null);
    try {
      await onSelectBroker(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Broker switch failed');
    } finally {
      setSwitching(false);
    }
  };

  const title = globallyBlocked && blockedReason
    ? blockedReason
    : 'Select the active execution broker (persisted; demo only)';

  return (
    <div className="broker-selector" style={{ display: 'flex', alignItems: 'center', gap: '6px', position: 'relative' }}>
      <Plug size={12} color="var(--quant-cyan)" aria-hidden="true" />
      <select
        aria-label="Active broker"
        value={activeBroker}
        onChange={handleChange}
        disabled={switching}
        title={title}
        style={{
          background: 'var(--bg-dark-input)',
          border: '1px solid var(--border-dark-medium)',
          borderRadius: 'var(--radius-sm)',
          color: 'var(--quant-cyan)',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          fontWeight: 700,
          height: '28px',
          padding: '0 6px',
          outline: 'none',
          cursor: switching ? 'wait' : 'pointer',
          maxWidth: '190px',
        }}
      >
        {BROKER_ORDER.map(broker => {
          const item = itemFor(broker);
          const label = BROKER_LABELS[broker];
          const disabled = item ? !item.can_switch && !item.is_active : false;
          const optionTitle = item?.is_active
            ? 'Active broker'
            : item?.switch_blocked_reason ?? item?.error_message ?? label;
          return (
            <option
              key={broker}
              value={broker}
              disabled={disabled}
              title={optionTitle}
              style={{ background: '#1c1c1c', color: '#fafafa' }}
            >
              {item?.is_active ? `${label} ●` : label}
            </option>
          );
        })}
      </select>
      {switching && (
        <span
          className="broker-selector-switching font-mono"
          role="status"
          style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px', color: 'var(--quant-amber)', fontWeight: 700 }}
        >
          <Loader2 size={11} className="spin" />
          SWITCHING…
        </span>
      )}
      {!switching && globallyBlocked && blockedReason && (
        <span
          className="broker-selector-blocked font-mono"
          title={blockedReason}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px', color: 'var(--quant-amber)', fontWeight: 700, maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          <AlertTriangle size={11} />
          {blockedReason}
        </span>
      )}
      {!switching && error && (
        <span
          className="broker-selector-error font-mono"
          role="alert"
          title={error}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '10px', color: 'var(--quant-red)', fontWeight: 700, maxWidth: '220px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        >
          <AlertTriangle size={11} />
          {error}
        </span>
      )}
    </div>
  );
};
