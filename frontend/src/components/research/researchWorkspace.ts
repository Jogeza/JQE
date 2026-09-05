import type { IndicatorVisibility } from '../chart/JQEChart';
import type { MarketInstrumentDTO } from '../../types/research';

export type ResearchWorkspaceId = 'primary' | 'comparison';
export interface ResearchLayoutState { comparisonEnabled: boolean; activeWorkspaceId: ResearchWorkspaceId; }
export type ResearchLayoutAction = { type: 'set-comparison'; enabled: boolean } | { type: 'activate'; workspaceId: ResearchWorkspaceId };
export const initialResearchLayout: ResearchLayoutState = { comparisonEnabled: false, activeWorkspaceId: 'primary' };
export function updateResearchLayout(state: ResearchLayoutState, action: ResearchLayoutAction): ResearchLayoutState {
  if (action.type === 'set-comparison') return { comparisonEnabled: action.enabled,
    activeWorkspaceId: action.enabled ? state.activeWorkspaceId : 'primary' };
  return action.workspaceId === 'comparison' && !state.comparisonEnabled ? state : { ...state, activeWorkspaceId: action.workspaceId };
}
export interface PaneVisibility { price: true; volume: boolean; rsi: boolean; }
export interface ResearchWorkspaceState {
  workspaceId: ResearchWorkspaceId;
  instrument: MarketInstrumentDTO;
  timeframe: string;
  overlays: Pick<IndicatorVisibility, 'ema50' | 'ema200'>;
  panes: PaneVisibility;
}

export type ResearchWorkspaceAction =
  | { type: 'select-instrument'; instrument: MarketInstrumentDTO }
  | { type: 'select-timeframe'; timeframe: string }
  | { type: 'toggle-overlay'; overlay: keyof ResearchWorkspaceState['overlays'] }
  | { type: 'toggle-pane'; pane: 'volume' | 'rsi' };

export function createResearchWorkspace(workspaceId: ResearchWorkspaceId, instrument: MarketInstrumentDTO,
  timeframe = 'M15'): ResearchWorkspaceState {
  return { workspaceId, instrument,
    timeframe: instrument.timeframes.includes(timeframe) ? timeframe : instrument.timeframes[0],
    overlays: { ema50: true, ema200: true }, panes: { price: true, volume: true, rsi: true } };
}

export function updateResearchWorkspace(state: ResearchWorkspaceState,
  action: ResearchWorkspaceAction): ResearchWorkspaceState {
  if (action.type === 'select-instrument') return { ...state, instrument: action.instrument,
    timeframe: action.instrument.timeframes.includes(state.timeframe) ? state.timeframe : action.instrument.timeframes[0] };
  if (action.type === 'select-timeframe') return state.instrument.timeframes.includes(action.timeframe)
    ? { ...state, timeframe: action.timeframe } : state;
  if (action.type === 'toggle-overlay') return { ...state, overlays: { ...state.overlays,
    [action.overlay]: !state.overlays[action.overlay] } };
  return { ...state, panes: { ...state.panes, [action.pane]: !state.panes[action.pane] } };
}

export function workspaceSelectionKey(state: Pick<ResearchWorkspaceState, 'workspaceId' | 'instrument' | 'timeframe'>): string {
  return `${state.workspaceId}:${state.instrument.provider}:${state.instrument.provider_symbol}:${state.timeframe}`;
}

export function indicatorVisibility(state: ResearchWorkspaceState): IndicatorVisibility {
  return { ...state.overlays, volume: state.panes.volume, rsi: state.panes.rsi };
}

export function applyReplayToWorkspace<T extends { workspaceId: ResearchWorkspaceId; cursor: number }>(
  workspaces: T[], activeWorkspaceId: ResearchWorkspaceId, delta: number, maximum: number): T[] {
  return workspaces.map(workspace => workspace.workspaceId === activeWorkspaceId
    ? { ...workspace, cursor: Math.max(0, Math.min(maximum, workspace.cursor + delta)) } : workspace);
}
