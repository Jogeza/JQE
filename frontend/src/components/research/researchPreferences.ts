import type { MarketInstrumentDTO } from '../../types/research';

export const RESEARCH_PREFERENCES_KEY = 'jqe.research.preferences.v1';
export interface ResearchPreferences {
  favourites: string[];
  selectedProviderSymbol?: string;
  timeframe?: string;
  category?: string;
  comparisonEnabled?: boolean;
  comparisonProviderSymbol?: string;
  comparisonTimeframe?: string;
}

export function loadResearchPreferences(storage: Pick<Storage, 'getItem'> = localStorage): ResearchPreferences {
  try { return parseResearchPreferences(storage.getItem(RESEARCH_PREFERENCES_KEY)); }
  catch { return { favourites: [] }; }
}

export function saveResearchPreferences(value: ResearchPreferences,
  storage: Pick<Storage, 'setItem'> = localStorage): void {
  try { storage.setItem(RESEARCH_PREFERENCES_KEY, JSON.stringify(value)); }
  catch { /* Preferences are optional; research remains usable when storage is unavailable. */ }
}

export function parseResearchPreferences(raw: string | null): ResearchPreferences {
  if (!raw) return { favourites: [] };
  try {
    const value = JSON.parse(raw) as Record<string, unknown>;
    return {
      favourites: Array.isArray(value.favourites)
        ? value.favourites.filter((item): item is string => typeof item === 'string').slice(0, 24)
        : [],
      selectedProviderSymbol: typeof value.selectedProviderSymbol === 'string' ? value.selectedProviderSymbol : undefined,
      timeframe: typeof value.timeframe === 'string' ? value.timeframe : undefined,
      category: typeof value.category === 'string' ? value.category : undefined,
      comparisonEnabled: typeof value.comparisonEnabled === 'boolean' ? value.comparisonEnabled : undefined,
      comparisonProviderSymbol: typeof value.comparisonProviderSymbol === 'string' ? value.comparisonProviderSymbol : undefined,
      comparisonTimeframe: typeof value.comparisonTimeframe === 'string' ? value.comparisonTimeframe : undefined,
    };
  } catch { return { favourites: [] }; }
}

export function validateResearchPreferences(value: ResearchPreferences,
  instruments: MarketInstrumentDTO[]): ResearchPreferences {
  const symbols = new Set(instruments.map(item => item.provider_symbol));
  const selected = instruments.find(item => item.provider_symbol === value.selectedProviderSymbol);
  const comparison = instruments.find(item => item.provider_symbol === value.comparisonProviderSymbol);
  return {
    favourites: [...new Set(value.favourites)].filter(symbol => symbols.has(symbol)).slice(0, 24),
    selectedProviderSymbol: selected?.provider_symbol,
    timeframe: selected?.timeframes.includes(value.timeframe ?? '') ? value.timeframe : undefined,
    category: value.category,
    comparisonEnabled: value.comparisonEnabled,
    comparisonProviderSymbol: comparison?.provider_symbol,
    comparisonTimeframe: comparison?.timeframes.includes(value.comparisonTimeframe ?? '') ? value.comparisonTimeframe : undefined,
  };
}

export function toggleFavourite(values: string[], symbol: string): string[] {
  return values.includes(symbol) ? values.filter(value => value !== symbol) : [...values, symbol].slice(-24);
}
