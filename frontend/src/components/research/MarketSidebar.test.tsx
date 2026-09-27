// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
import { MarketSidebar } from './MarketSidebar';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('labels uncached Weltrade instruments without implying public data is available', async () => {
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const instrument = { provider: 'weltrade', provider_symbol: 'FX VOL 20', canonical_symbol: 'FX VOL 20', display_name: 'FX VOL 20', market: 'watched', subgroup: 'FX Vol', submarket: 'fx_vol', instrument_type: 'synthetic_index', pip_size: 0.00001, exchange_is_open: true, is_trading_suspended: false, historical_data_supported: 'UNKNOWN', timeframes: ['M1'] } as MarketInstrumentDTO;
  const markets = { catalogue: { provider: 'weltrade', instruments: [instrument], source_status: 'WATCHLIST', cache_status: 'DURABLE' }, cached_datasets: [] } as ResearchMarketsDTO;
  await act(async () => root.render(<MarketSidebar markets={markets} items={[instrument]} selected={instrument} timeframe="M1" favourites={[]} query="" onSelect={() => {}} onToggleFavourite={() => {}} />));
  expect(host.querySelector('.research-cache-label')?.getAttribute('title')).toBe('Weltrade terminal history not cached');
  expect(host.querySelector('.research-cache-label')?.textContent).toBe('Not cached');
  await act(async () => root.unmount());
  host.remove();
});
