import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
import { isCached, marketLabel, searchMarkets } from '../chart/marketCatalogueAdapter';

interface Props {
  markets: ResearchMarketsDTO;
  items: MarketInstrumentDTO[];
  selected: MarketInstrumentDTO | null;
  timeframe: string;
  favourites: string[];
  query: string;
  onSelect: (item: MarketInstrumentDTO) => void;
  onToggleFavourite: (symbol: string) => void;
}

export function MarketSidebar({
  markets,
  items,
  selected,
  timeframe,
  favourites,
  query,
  onSelect,
  onToggleFavourite,
}: Props) {
  const filtered = searchMarkets(items, query);
  const ordered = [...filtered].sort(
    (a, b) =>
      Number(favourites.includes(b.provider_symbol)) - Number(favourites.includes(a.provider_symbol)) ||
      a.display_name.localeCompare(b.display_name)
  );

  return (
    <aside className="research-market-sidebar" aria-label="Research watchlist">
      <div className="research-section-title">
        <div>
          <span>Watchlist</span>
          <small>Available research markets</small>
        </div>
        <span>{ordered.length}</span>
      </div>
      <div className="research-watchlist">
        {ordered.map((item) => {
          const isSelected = selected?.provider_symbol === item.provider_symbol;
          const cached = isCached(markets, item, timeframe);
          const isFav = favourites.includes(item.provider_symbol);

          return (
            <div
              className={`research-watch-row ${isSelected ? 'selected' : ''}`}
              key={item.provider_symbol}
            >
              <button
                className="research-favourite"
                onClick={() => onToggleFavourite(item.provider_symbol)}
                aria-label={`${isFav ? 'Unpin' : 'Pin'} ${item.display_name}`}
                title={isFav ? 'Unpin from top' : 'Pin to top'}
              >
                {isFav ? '★' : '☆'}
              </button>
              <button
                className="research-market-switch"
                onClick={() => onSelect(item)}
                disabled={item.is_trading_suspended}
                title={`${item.display_name} (${item.provider_symbol})`}
              >
                <strong>{item.canonical_symbol}</strong>
                <small>
                  {item.display_name} · {marketLabel(item)}
                </small>
              </button>
              <span
                className="research-cache-label"
                title={cached ? 'Dataset cached locally' : 'Public data only (uncached)'}
              >{cached ? 'Cached' : 'Public'}</span>
            </div>
          );
        })}
        {!ordered.length && (
          <div className="research-watchlist-empty">
            No instruments match search.
          </div>
        )}
      </div>
    </aside>
  );
}
