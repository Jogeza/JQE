// Mirrors broker/weltrade_symbols.py SUPPORTED_WELTRADE_SYNTX. The backend
// validates every symbol against the terminal catalogue and fails closed, so a
// stale entry here cannot authorize an out-of-scope instrument.
export const SUPPORTED_WELTRADE_SYMBOLS: readonly string[] = [
  'FX Vol 20', 'FX Vol 40', 'FX Vol 60', 'FX Vol 80', 'FX Vol 99',
  'SFX Vol 20', 'SFX Vol 40', 'SFX Vol 60', 'SFX Vol 80', 'SFX Vol 99',
  'PainX 400', 'PainX 600', 'PainX 800', 'PainX 999', 'PainX 1200',
  'MAX PainX 1000', 'MAX PainX 2000',
  'GainX 400', 'GainX 600', 'GainX 800', 'GainX 999', 'GainX 1200',
  'MAX GainX 1000', 'MAX GainX 2000',
  'FlipX 1', 'FlipX 2', 'FlipX 3', 'FlipX 4', 'FlipX 5',
  'SwitchX 600', 'SwitchX 1200', 'SwitchX 1800',
  'BreakX 600', 'BreakX 1200', 'BreakX 1800',
  'FiboX',
];

export interface SymbolFamily {
  id: string;
  name: string;
  aliases: readonly string[];
}

// Order mirrors the families in weltrade_symbols.py.
const FAMILIES: readonly SymbolFamily[] = [
  { id: 'fx_vol', name: 'FX Volatility', aliases: ['fx', 'vol'] },
  { id: 'sfx_vol', name: 'SFX Volatility', aliases: ['sfx', 'smooth'] },
  { id: 'painx', name: 'PainX (Crash)', aliases: ['crash'] },
  { id: 'max_painx', name: 'MAX PainX', aliases: ['crash'] },
  { id: 'gainx', name: 'GainX (Boom)', aliases: ['boom'] },
  { id: 'max_gainx', name: 'MAX GainX', aliases: ['boom'] },
  { id: 'flipx', name: 'FlipX', aliases: ['flip', 'regime'] },
  { id: 'switchx', name: 'SwitchX', aliases: ['switch', 'mean reversion'] },
  { id: 'breakx', name: 'BreakX', aliases: ['break', 'breakout'] },
  { id: 'fibox', name: 'FiboX', aliases: ['fib', 'fibonacci'] },
];

export function symbolSearchKey(symbol: string): string {
  return symbol.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

export function symbolFamilyId(symbol: string): string {
  const key = symbolSearchKey(symbol);
  if (key.includes('MAXPAINX')) return 'max_painx';
  if (key.includes('PAINX')) return 'painx';
  if (key.includes('MAXGAINX')) return 'max_gainx';
  if (key.includes('GAINX')) return 'gainx';
  if (key.includes('SFXVOL')) return 'sfx_vol';
  if (key.includes('FXVOL')) return 'fx_vol';
  if (key.includes('FLIPX')) return 'flipx';
  if (key.includes('SWITCHX')) return 'switchx';
  if (key.includes('BREAKX')) return 'breakx';
  if (key.includes('FIBOX')) return 'fibox';
  return 'other';
}

export function symbolFamilyName(symbol: string): string {
  const id = symbolFamilyId(symbol);
  return FAMILIES.find(family => family.id === id)?.name ?? 'Synthetic Index';
}

export function mergeSymbolOptions(...groups: ReadonlyArray<readonly (string | null | undefined)[] | null | undefined>): string[] {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const group of groups) {
    for (const symbol of group ?? []) {
      const trimmed = symbol?.trim();
      if (!trimmed) continue;
      const key = symbolSearchKey(trimmed);
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(trimmed);
    }
  }
  return merged;
}

export function filterSymbols(symbols: readonly string[], query: string): string[] {
  const needle = query.trim().toLowerCase();
  const compact = symbolSearchKey(query);
  if (!needle) return [...symbols];
  return symbols.filter(symbol => {
    if (compact && symbolSearchKey(symbol).includes(compact)) return true;
    const family = FAMILIES.find(candidate => candidate.id === symbolFamilyId(symbol));
    if (!family) return false;
    if (family.name.toLowerCase().includes(needle)) return true;
    return family.aliases.some(alias => alias.includes(needle));
  });
}

export interface SymbolGroup {
  family: string;
  symbols: string[];
}

export function groupSymbolsByFamily(symbols: readonly string[]): SymbolGroup[] {
  const groups: SymbolGroup[] = [];
  for (const symbol of symbols) {
    const family = symbolFamilyName(symbol);
    const existing = groups.find(group => group.family === family);
    if (existing) existing.symbols.push(symbol);
    else groups.push({ family, symbols: [symbol] });
  }
  return groups;
}
