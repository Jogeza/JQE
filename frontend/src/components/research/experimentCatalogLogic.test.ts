// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';
import { vi } from 'vitest';
import { ResearchPage } from '../../pages/ResearchPage';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
import {
  appliedFilters,
  canPageNext,
  catalogRange,
  classificationLabels,
  displayValue,
  filterRequest,
  toggleComparisonSelection,
} from './experimentCatalogLogic';

describe('experiment catalog logic', () => {
  it('renders unavailable metrics without substituting zero', () => {
    expect(displayValue(null)).toBe('\u2014');
    expect(displayValue(0)).toBe('0');
  });

  it('maps every authoritative comparison classification', () => {
    expect(classificationLabels.IDENTICAL_RESULT).toBe('Identical result');
    expect(classificationLabels.SAME_RUN_CONFIGURATION_DIFFERENT_OBSERVATION).toContain('different observation');
    expect(classificationLabels.SAME_DATASET_DIFFERENT_CONFIGURATION).toBe('Same dataset, different configuration');
    expect(classificationLabels.DIFFERENT_DATASET).toBe('Different dataset');
    expect(classificationLabels.LEGACY_OR_INCOMPLETE).toBe('Legacy or incomplete');
  });

  it('calculates pagination boundaries and factual ranges', () => {
    expect(catalogRange(0, 50, 126)).toBe('1\u201350 of 126');
    expect(catalogRange(100, 50, 126)).toBe('101\u2013126 of 126');
    expect(canPageNext(100, 50, 126)).toBe(false);
    expect(canPageNext(50, 50, 126)).toBe(true);
  });

  it('selects no more than two experiments and supports deselection', () => {
    expect(toggleComparisonSelection(['a', 'b'], 'c')).toEqual(['a', 'b']);
    expect(toggleComparisonSelection(['a', 'b'], 'a')).toEqual(['b']);
  });

  it('keeps false while omitting blank and undefined filters', () => {
    expect(appliedFilters({ symbol: '', timeframe: undefined, fully_reproducible: false }))
      .toEqual({ fully_reproducible: false });
  });

  it('resets pagination when filters are applied', () => {
    expect(filterRequest({ symbol: 'R_100' })).toEqual({
      filters: { symbol: 'R_100' },
      offset: 0,
    });
  });

  it('keeps the catalog accessible when the chart market catalogue fails', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (String(input) === '/api/v1/research/markets')
        return Promise.resolve({ ok: false, status: 500 } as Response);
      return Promise.resolve({
        ok: true,
        json: async () => ({ experiments: [], issues: [], total: 0, limit: 25, offset: 0 }),
      } as Response);
    });
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);
    await act(async () => { root.render(createElement(ResearchPage)); await Promise.resolve(); });
    const tab = [...host.querySelectorAll('button')].find((button) => button.textContent === 'Experiment catalog');
    await act(async () => { tab?.click(); await Promise.resolve(); });
    expect(host.textContent).toContain('No persisted training experiments are available yet.');
    expect(fetchMock.mock.calls.some(([url]) => String(url).startsWith('/api/v1/research/experiments'))).toBe(true);
    await act(async () => root.unmount());
    host.remove();
    fetchMock.mockRestore();
  });
});
