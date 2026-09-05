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
export function isCached(dto: ResearchMarketsDTO, item: MarketInstrumentDTO, timeframe: string): boolean {
  return dto.cached_datasets.some(dataset => dataset.provider === item.provider && dataset.canonical_symbol === item.canonical_symbol && dataset.timeframe === timeframe);
}
