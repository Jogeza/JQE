import { describe, expect, it } from 'vitest';
import {
  filterSymbols, groupSymbolsByFamily, mergeSymbolOptions, SUPPORTED_WELTRADE_SYMBOLS,
  symbolFamilyId, symbolFamilyName, symbolSearchKey,
} from './symbolUniverse';

describe('Weltrade symbol universe helpers', () => {
  it('mirrors only native Weltrade synthetic scope without Deriv aliases', () => {
    expect(SUPPORTED_WELTRADE_SYMBOLS).toHaveLength(36);
    expect(SUPPORTED_WELTRADE_SYMBOLS).toContain('PainX 999');
    expect(SUPPORTED_WELTRADE_SYMBOLS).toContain('FiboX');
    expect(SUPPORTED_WELTRADE_SYMBOLS).not.toContain('R_75');
    expect(SUPPORTED_WELTRADE_SYMBOLS).not.toContain('BOOM500');
  });

  it('normalizes search keys by stripping spacing and punctuation', () => {
    expect(symbolSearchKey('FX Vol 20')).toBe('FXVOL20');
    expect(symbolSearchKey('  max painx 2000 ')).toBe('MAXPAINX2000');
  });

  it('classifies MAX and base families in priority order', () => {
    expect(symbolFamilyId('MAX PainX 1000')).toBe('max_painx');
    expect(symbolFamilyId('PainX 400')).toBe('painx');
    expect(symbolFamilyId('MAX GainX 2000')).toBe('max_gainx');
    expect(symbolFamilyId('GainX 999')).toBe('gainx');
    expect(symbolFamilyId('SFX Vol 99')).toBe('sfx_vol');
    expect(symbolFamilyId('FX Vol 20')).toBe('fx_vol');
    expect(symbolFamilyId('Mystery 1')).toBe('other');
    expect(symbolFamilyName('MAX PainX 1000')).toBe('MAX PainX');
    expect(symbolFamilyName('Mystery 1')).toBe('Synthetic Index');
  });

  it('merges option groups and deduplicates by search key', () => {
    expect(mergeSymbolOptions(['FX Vol 20'], [null, 'fx vol 20', 'PainX 999'], undefined))
      .toEqual(['FX Vol 20', 'PainX 999']);
  });

  it('filters by compact symbol key, family name, and family alias', () => {
    const universe = SUPPORTED_WELTRADE_SYMBOLS;
    expect(filterSymbols(universe, 'painx999')).toContain('PainX 999');
    expect(filterSymbols(universe, 'fibonacci')).toEqual(['FiboX']);
    expect(filterSymbols(universe, 'crash')).toEqual(['PainX 400', 'PainX 600', 'PainX 800', 'PainX 999', 'PainX 1200', 'MAX PainX 1000', 'MAX PainX 2000']);
    expect(filterSymbols(universe, 'boom')).toEqual(['GainX 400', 'GainX 600', 'GainX 800', 'GainX 999', 'GainX 1200', 'MAX GainX 1000', 'MAX GainX 2000']);
    expect(filterSymbols(universe, '   ')).toEqual([...universe]);
    expect(filterSymbols(universe, 'zzz')).toEqual([]);
  });

  it('groups symbols by family while preserving scope order', () => {
    const groups = groupSymbolsByFamily(['PainX 999', 'MAX PainX 2000', 'FX Vol 20', 'PainX 400']);
    expect(groups.map(group => group.family)).toEqual(['PainX (Crash)', 'MAX PainX', 'FX Volatility']);
    expect(groups[0].symbols).toEqual(['PainX 999', 'PainX 400']);
  });
});
