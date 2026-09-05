import { describe, expect, it } from 'vitest';
import { isCached, marketGroups, searchMarkets } from './marketCatalogueAdapter';
import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
const instrument = (provider_symbol: string, display_name: string, market: string, canonical_symbol=provider_symbol): MarketInstrumentDTO => ({ provider: 'deriv', provider_symbol, canonical_symbol, display_name, market, market_display_name: null, subgroup: 'x', submarket: market, submarket_display_name: null, instrument_type: market, pip_size: .01, exchange_is_open: true, is_trading_suspended: false, historical_data_supported: 'UNKNOWN', timeframes: ['M1','M5'] });
const items = [instrument('frxEURUSD','EUR/USD','forex','EURUSD'), instrument('R_100','Volatility 100 Index','synthetic_index'), instrument('NEW','Future Thing','future_market')];
const dto = { catalogue: { provider: 'deriv', instruments: items, source_status: 'AVAILABLE', cache_status: 'HIT' }, cached_datasets: [{ provider: 'deriv', canonical_symbol: 'EURUSD', provider_symbol: 'frxEURUSD', timeframe: 'M5' }] } as ResearchMarketsDTO;
describe('market catalogue adapter', () => {
  it('groups provider categories including unknown future values', () => expect(marketGroups(dto)).toEqual(['forex','future_market','synthetic_index']));
  it('searches display, canonical, provider, market, and submarket metadata locally', () => { expect(searchMarkets(items,'EUR')).toEqual([items[0]]); expect(searchMarkets(items,'volatility')).toEqual([items[1]]); expect(searchMarkets(items,'','future_market')).toEqual([items[2]]); });
  it('uses provider+canonical+timeframe for cached state', () => { expect(isCached(dto,items[0],'M5')).toBe(true); expect(isCached(dto,items[0],'M1')).toBe(false); });
});
