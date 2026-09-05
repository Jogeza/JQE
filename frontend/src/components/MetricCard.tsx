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
        padding: '10px 12px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        position: 'relative',
        overflow: 'hidden',
        transition: 'border-color var(--transition-fast)',
        minHeight: '72px',
      }}
    >
      {/* Top row: Label + Badge */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '4px',
          gap: '6px',
        }}
      >
        <span
          style={{
            fontSize: '9.5px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.07em',
            color: 'var(--text-muted)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {label}
        </span>

        {badge && (
          <span
            className={`badge badge-${badgeType}`}
            style={{ fontSize: '8.5px', padding: '0 4px', height: '16px', lineHeight: '16px' }}
          >
            {badge}
          </span>
        )}
      </div>

      {/* Main Metric Value */}
      <div
        className="font-mono"
        style={{
          fontSize: '17px',
          fontWeight: 800,
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
            fontSize: '9.5px',
            color: 'var(--text-dim)',
            marginTop: '3px',
            fontFamily: 'var(--font-mono)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {subtext}
        </div>
      )}
    </div>
  );
};
