import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
export const marketLabel = (item: MarketInstrumentDTO) => item.market_display_name || item.market || 'Other';
export function marketGroups(dto: ResearchMarketsDTO): string[] {
  return [...new Set(dto.catalogue.instruments.map(marketLabel))].sort((a, b) => a.localeCompare(b));
}
export function searchMarkets(items: MarketInstrumentDTO[], query: string, category = 'All'): MarketInstrumentDTO[] {
  const needle = query.trim().toLocaleLowerCase();
  return items.filter(item => (category === 'All' || marketLabel(item) === category) && (!needle ||
    [item.display_name, item.canonical_symbol, item.provider_symbol, item.market, item.market_display_name,
      item.submarket, item.submarket_display_name].some(value => value?.toLocaleLowerCase().includes(needle))));
}
// The durable watchlist stores upper-cased names (SFX VOL 20) while cached
// datasets carry the terminal catalogue spelling (SFX Vol 20), so the same
// instrument arrives in two spellings. Identity ignores case and punctuation,
// mirroring broker/weltrade_symbols.py:weltrade_symbol_key.
export const symbolIdentity = (value: string) => value.toUpperCase().replace(/[^A-Z0-9]/g, '');
export function isCached(dto: ResearchMarketsDTO, item: MarketInstrumentDTO, timeframe: string): boolean {
  return dto.cached_datasets.some(dataset => dataset.provider === item.provider &&
    symbolIdentity(dataset.canonical_symbol) === symbolIdentity(item.canonical_symbol) &&
    dataset.timeframe === timeframe);
}
