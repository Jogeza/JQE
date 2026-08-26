import React from 'react';

interface MetricCardProps {
  label: string;
  value: string | number | null | undefined;
  subtext?: string;
  trend?: 'up' | 'down' | 'neutral';
  badge?: string;
  badgeType?: 'green' | 'red' | 'amber' | 'neutral' | 'cyan';
  loading?: boolean;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subtext,
  trend,
  badge,
  badgeType = 'neutral',
  loading,
}) => {
  const formatValue = () => {
    if (loading) return '...';
    if (value === null || value === undefined) return '—';
    return String(value);
  };

  const getTrendColor = () => {
    if (trend === 'up') return 'var(--quant-green)';
    if (trend === 'down') return 'var(--quant-red)';
    return 'var(--text-primary)';
  };

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-sm)',
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Top row: Label + Badge */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '6px',
        }}
      >
        <span
          style={{
            fontSize: '10.5px',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: 'var(--text-muted)',
          }}
        >
          {label}
        </span>

        {badge && (
          <span className={`badge badge-${badgeType}`} style={{ fontSize: '9px', padding: '1px 5px' }}>
            {badge}
          </span>
        )}
      </div>

      {/* Main Metric Value */}
      <div
        className="font-mono"
        style={{
          fontSize: '18px',
          fontWeight: 700,
          color: getTrendColor(),
          letterSpacing: '-0.02em',
          lineHeight: '1.2',
        }}
      >
        {formatValue()}
      </div>

      {/* Subtext */}
      {subtext && (
        <div
          style={{
            fontSize: '10.5px',
            color: 'var(--text-dim)',
            marginTop: '4px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {subtext}
        </div>
      )}
    </div>
  );
};
