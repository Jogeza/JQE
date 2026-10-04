import { describe, expect, it } from 'vitest';
import { isCached, marketGroups, searchMarkets, symbolIdentity } from './marketCatalogueAdapter';
import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../../types/research';
const instrument = (provider_symbol: string, display_name: string, market: string, canonical_symbol=provider_symbol): MarketInstrumentDTO => ({ provider: 'deriv', provider_symbol, canonical_symbol, display_name, market, market_display_name: null, subgroup: 'x', submarket: market, submarket_display_name: null, instrument_type: market, pip_size: .01, exchange_is_open: true, is_trading_suspended: false, historical_data_supported: 'UNKNOWN', timeframes: ['M1','M5'] });
const items = [instrument('frxEURUSD','EUR/USD','forex','EURUSD'), instrument('R_100','Volatility 100 Index','synthetic_index'), instrument('NEW','Future Thing','future_market')];
const weltrade = (canonical_symbol: string): MarketInstrumentDTO => ({ ...instrument(canonical_symbol, canonical_symbol, 'synthetic_index'), provider: 'weltrade' });
const dto = { catalogue: { provider: 'deriv', instruments: items, source_status: 'AVAILABLE', cache_status: 'HIT' }, cached_datasets: [{ provider: 'deriv', canonical_symbol: 'EURUSD', provider_symbol: 'frxEURUSD', timeframe: 'M5' }] } as ResearchMarketsDTO;
describe('market catalogue adapter', () => {
  it('groups provider categories including unknown future values', () => expect(marketGroups(dto)).toEqual(['forex','future_market','synthetic_index']));
  it('searches display, canonical, provider, market, and submarket metadata locally', () => { expect(searchMarkets(items,'EUR')).toEqual([items[0]]); expect(searchMarkets(items,'volatility')).toEqual([items[1]]); expect(searchMarkets(items,'','future_market')).toEqual([items[2]]); });
  it('uses provider+canonical+timeframe for cached state', () => { expect(isCached(dto,items[0],'M5')).toBe(true); expect(isCached(dto,items[0],'M1')).toBe(false); });
  it('matches cached state across watchlist and terminal spellings', () => {
    const weltradeDto = { catalogue: { provider: 'weltrade', instruments: [weltrade('SFX VOL 20'), weltrade('SFX VOL 40')], source_status: 'WATCHLIST', cache_status: 'DURABLE' }, cached_datasets: [{ provider: 'weltrade', canonical_symbol: 'SFX Vol 20', provider_symbol: 'SFX Vol 20', timeframe: 'M5' }] } as ResearchMarketsDTO;
    expect(isCached(weltradeDto, weltrade('SFX VOL 20'), 'M5')).toBe(true);
    expect(isCached(weltradeDto, weltrade('SFX Vol 20'), 'M5')).toBe(true);
    expect(isCached(weltradeDto, weltrade('SFX VOL 40'), 'M5')).toBe(false);
    expect(isCached(weltradeDto, weltrade('SFX VOL 20'), 'M1')).toBe(false);
    expect(isCached(dto, weltrade('SFX VOL 20'), 'M5')).toBe(false);
  });
  it('treats casing and punctuation as identity-neutral without merging instruments', () => {
    expect(symbolIdentity('SFX VOL 20')).toBe(symbolIdentity('SFX Vol 20'));
    expect(symbolIdentity('FX VOL. 20')).toBe(symbolIdentity('FX Vol 20'));
    expect(symbolIdentity('MAX PAINX 1000')).toBe(symbolIdentity('MAX PainX 1000'));
    expect(symbolIdentity('FX Vol 20')).not.toBe(symbolIdentity('FX Vol 40'));
    expect(symbolIdentity('FX Vol 20')).not.toBe(symbolIdentity('SFX Vol 20'));
  });
});
