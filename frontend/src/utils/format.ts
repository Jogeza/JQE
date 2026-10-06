export function formatMoney(value: number, currency?: string, sign = false): string {
  if (!currency) return '—';
  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: sign ? 'always' : 'auto',
  }).format(value);
  return formatted;
}

export function formatInstrumentPrice(value: number, decimals?: number): string {
  return decimals === undefined ? '—' : value.toFixed(decimals);
}

export function utcDayKey(iso: string): string | null {
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString().slice(0, 10) : null;
}

export function formatUtcDateTime(iso: string): string {
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed)
    ? `${new Date(parsed).toISOString().slice(0, 19).replace('T', ' ')} UTC`
    : iso || '—';
}
