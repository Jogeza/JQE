import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
import { isCached, marketLabel, searchMarkets } from '../chart/marketCatalogueAdapter';

interface Props { markets: ResearchMarketsDTO; items: MarketInstrumentDTO[]; selected: MarketInstrumentDTO | null;
  timeframe: string; favourites: string[]; query: string; onSelect: (item: MarketInstrumentDTO) => void;
  onToggleFavourite: (symbol: string) => void; }

export function MarketSidebar({ markets, items, selected, timeframe, favourites, query, onSelect, onToggleFavourite }: Props) {
  const filtered = searchMarkets(items, query);
  const ordered = [...filtered].sort((a, b) => Number(favourites.includes(b.provider_symbol)) - Number(favourites.includes(a.provider_symbol)) || a.display_name.localeCompare(b.display_name));
  return <aside className="research-market-sidebar" aria-label="Research watchlist">
    <div className="research-section-title">Watchlist <span>{ordered.length}</span></div>
    <div className="research-watchlist">
      {ordered.map(item => <div className={`research-watch-row ${selected?.provider_symbol === item.provider_symbol ? 'selected' : ''}`} key={item.provider_symbol}>
        <button className="research-favourite" onClick={() => onToggleFavourite(item.provider_symbol)} aria-label={`${favourites.includes(item.provider_symbol) ? 'Unpin' : 'Pin'} ${item.display_name}`}>{favourites.includes(item.provider_symbol) ? '★' : '☆'}</button>
        <button className="research-market-switch" onClick={() => onSelect(item)} disabled={item.is_trading_suspended}>
          <strong>{item.canonical_symbol}</strong><small>{item.display_name} · {marketLabel(item)}</small>
        </button>
        <span className={isCached(markets, item, timeframe) ? 'research-cache-dot cached' : 'research-cache-dot'} title={isCached(markets, item, timeframe) ? 'Cached' : 'Not cached'} />
      </div>)}
      {!ordered.length && <p className="text-muted">No instruments match this search.</p>}
    </div>
  </aside>;
}
