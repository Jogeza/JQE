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
