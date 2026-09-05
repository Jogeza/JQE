import { describe, expect, it } from 'vitest';
import type { MarketInstrumentDTO } from '../../types/research';
import { applyReplayToWorkspace, createResearchWorkspace, indicatorVisibility, initialResearchLayout,
  updateResearchLayout, updateResearchWorkspace, workspaceSelectionKey } from './researchWorkspace';

const market = (provider_symbol: string, timeframes = ['M15', 'H1']) => ({ provider: 'deriv', provider_symbol,
  canonical_symbol: provider_symbol.replace('frx', ''), display_name: provider_symbol, market: 'forex', subgroup: '',
  submarket: '', instrument_type: 'forex', pip_size: 5, exchange_is_open: true, is_trading_suspended: false,
  historical_data_supported: 'UNKNOWN', timeframes } as MarketInstrumentDTO);

describe('research workspace ownership', () => {
  it('defaults to single-chart mode', () => expect(initialResearchLayout).toEqual({ comparisonEnabled: false, activeWorkspaceId: 'primary' }));
  it('enables and disables comparison without leaving a hidden active workspace', () => {
    const enabled = updateResearchLayout(initialResearchLayout, { type: 'set-comparison', enabled: true });
    const active = updateResearchLayout(enabled, { type: 'activate', workspaceId: 'comparison' });
    expect(active.activeWorkspaceId).toBe('comparison');
    expect(updateResearchLayout(active, { type: 'set-comparison', enabled: false })).toEqual(initialResearchLayout);
  });
  it('starts as one independently identified workspace', () => {
    expect(createResearchWorkspace('primary', market('frxXAUUSD')).workspaceId).toBe('primary');
  });
  it('changes only the selected workspace instrument and preserves a supported timeframe', () => {
    const primary = createResearchWorkspace('primary', market('frxXAUUSD'));
    const secondary = createResearchWorkspace('comparison', market('frxEURUSD'));
    const changed = updateResearchWorkspace(secondary, { type: 'select-instrument', instrument: market('R_100', ['M5']) });
    expect(primary.instrument.provider_symbol).toBe('frxXAUUSD');
    expect(changed.instrument.provider_symbol).toBe('R_100'); expect(changed.timeframe).toBe('M5');
  });
  it('owns timeframe, overlays, and panes independently', () => {
    let state = createResearchWorkspace('comparison', market('frxEURUSD'));
    state = updateResearchWorkspace(state, { type: 'select-timeframe', timeframe: 'H1' });
    state = updateResearchWorkspace(state, { type: 'toggle-overlay', overlay: 'ema50' });
    state = updateResearchWorkspace(state, { type: 'toggle-pane', pane: 'rsi' });
    expect(state.timeframe).toBe('H1'); expect(indicatorVisibility(state)).toEqual({ ema50: false, ema200: true, volume: true, rsi: false });
  });
  it('changes the transient identity only for selection changes', () => {
    const state = createResearchWorkspace('primary', market('frxXAUUSD'));
    const hidden = updateResearchWorkspace(state, { type: 'toggle-pane', pane: 'volume' });
    const changed = updateResearchWorkspace(state, { type: 'select-timeframe', timeframe: 'H1' });
    expect(workspaceSelectionKey(hidden)).toBe(workspaceSelectionKey(state));
    expect(workspaceSelectionKey(changed)).not.toBe(workspaceSelectionKey(state));
  });
  it('applies replay only to the active workspace', () => {
    const result = applyReplayToWorkspace([{ workspaceId: 'primary' as const, cursor: 2 },
      { workspaceId: 'comparison' as const, cursor: 7 }], 'comparison', 1, 10);
    expect(result.map(item => item.cursor)).toEqual([2, 8]);
  });
});
