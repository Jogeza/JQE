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
    <div className="metric-card"
      style={{
        backgroundColor: 'var(--bg-card)',
        border: '1px solid var(--border-card)',
        borderRadius: 'var(--radius-md)',
        boxShadow: 'var(--shadow-card)',
        padding: '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        position: 'relative',
        overflow: 'hidden',
        transition: 'border-color var(--transition-fast), box-shadow var(--transition-fast)',
        minHeight: '80px',
      }}
    >
      {/* Top row: Label + Badge */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '6px',
          gap: '8px',
        }}
      >
        <span
          style={{
            fontSize: '10px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            color: 'var(--text-secondary)',
            fontFamily: 'var(--font-sans)',
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
            style={{ fontSize: '9px', padding: '0 5px', height: '18px', lineHeight: '18px' }}
          >
            {badge}
          </span>
        )}
      </div>

      {/* Main Metric Value */}
      <div
        className="font-mono metric-value"
        style={{
          fontSize: '18px',
          fontWeight: 800,
          color: getTrendColor(),
          letterSpacing: '-0.02em',
          lineHeight: '1.2',
        }}
      >
        {trend && trend !== 'neutral' && <span aria-label={trend === 'up' ? 'Up' : 'Down'} className="metric-trend">{trend === 'up' ? '↗' : '↘'}</span>}{formatValue()}
      </div>

      {/* Subtext */}
      {subtext && (
        <div
          style={{
            fontSize: '10.5px',
            color: 'var(--text-muted)',
            marginTop: '4px',
            fontFamily: 'var(--font-sans)',
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
