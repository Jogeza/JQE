import type { ExperimentComparisonClassification, ExperimentListFilters } from '../../types/api';

export const classificationLabels: Record<ExperimentComparisonClassification, string> = {
  IDENTICAL_RESULT: 'Identical result',
  SAME_RUN_CONFIGURATION_DIFFERENT_OBSERVATION: 'Same run configuration, different observation',
  SAME_DATASET_DIFFERENT_CONFIGURATION: 'Same dataset, different configuration',
  DIFFERENT_DATASET: 'Different dataset',
  LEGACY_OR_INCOMPLETE: 'Legacy or incomplete',
};

export function catalogRange(offset: number, limit: number, total: number): string {
  if (total === 0) return '0 of 0';
  return `${offset + 1}\u2013${Math.min(offset + limit, total)} of ${total}`;
}

export function canPageNext(offset: number, limit: number, total: number): boolean {
  return offset + limit < total;
}

export function toggleComparisonSelection(selected: string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((value) => value !== id);
  return selected.length < 2 ? [...selected, id] : selected;
}

export function appliedFilters(filters: ExperimentListFilters): ExperimentListFilters {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== '' && value !== undefined)
  ) as ExperimentListFilters;
}

export function filterRequest(filters: ExperimentListFilters): { filters: ExperimentListFilters; offset: 0 } {
  return { filters: appliedFilters(filters), offset: 0 };
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '\u2014';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}
