import { describe, expect, it } from 'vitest';
import { loadResearchPreferences, parseResearchPreferences, saveResearchPreferences, toggleFavourite, validateResearchPreferences } from './researchPreferences';
import type { MarketInstrumentDTO } from '../../types/research';

const instrument = { provider_symbol: 'frxEURUSD', canonical_symbol: 'EURUSD', display_name: 'EUR/USD',
  provider: 'deriv', market: 'forex', subgroup: '', submarket: 'major_pairs', instrument_type: 'forex',
  pip_size: 5, exchange_is_open: true, is_trading_suspended: false, historical_data_supported: 'UNKNOWN',
  timeframes: ['M15', 'H1'] } as MarketInstrumentDTO;

describe('research preferences', () => {
  it('fails closed for malformed persisted state', () => expect(parseResearchPreferences('{bad')).toEqual({ favourites: [] }));
  it('removes unavailable symbols and invalid timeframes', () => {
    const result = validateResearchPreferences({ favourites: ['gone', 'frxEURUSD', 'frxEURUSD'],
      selectedProviderSymbol: 'frxEURUSD', timeframe: 'D1' }, [instrument]);
    expect(result.favourites).toEqual(['frxEURUSD']);
    expect(result.timeframe).toBeUndefined();
  });
  it('toggles favourites without duplicates', () => {
    expect(toggleFavourite([], 'frxEURUSD')).toEqual(['frxEURUSD']);
    expect(toggleFavourite(['frxEURUSD'], 'frxEURUSD')).toEqual([]);
  });
  it('degrades safely when browser storage is unavailable', () => {
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    expect(loadResearchPreferences(broken)).toEqual({ favourites: [] });
    expect(() => saveResearchPreferences({ favourites: [] }, broken)).not.toThrow();
  });
  it('validates comparison preferences against the backend catalogue', () => {
    const result = validateResearchPreferences({ favourites: [], comparisonEnabled: true,
      comparisonProviderSymbol: 'frxEURUSD', comparisonTimeframe: 'H1' }, [instrument]);
    expect(result.comparisonEnabled).toBe(true); expect(result.comparisonTimeframe).toBe('H1');
  });
});
