// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { jqeApi } from '../../services/api';
import { ExperimentCatalog } from './ExperimentCatalog';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('ExperimentCatalog discovery warnings', () => {
  afterEach(() => vi.restoreAllMocks());

  it('renders separator dots instead of source escape text', async () => {
    const summary = (experiment_id: string, symbol: string) => ({
      experiment_id, symbol, status: 'COMPLETED' as const, created_at: '2026-08-01T10:00:00Z', timeframe: 'M15',
      effective_start: '2025-01-01T00:00:00Z', effective_end: '2025-03-01T00:00:00Z', candle_count: 1000,
      dataset_hash: `dataset-${experiment_id}`, run_fingerprint: `run-${experiment_id}`, result_hash: `result-${experiment_id}`,
      engine_version: '6.0.0', identity_schema_version: 1, initial_capital: 10000, ending_capital: 10100,
      total_return: 1, total_trades: 5, fully_reproducible: true,
    });
    vi.spyOn(jqeApi, 'listExperiments').mockResolvedValue({
      experiments: [summary('experiment-one', 'XAUUSD'), summary('experiment-two', 'EURUSD')],
      issues: [
        { file_name: 'unreadable-record.json', code: 'INVALID_EXPERIMENT_RECORD', message: 'Record could not be validated.' },
        { file_name: 'legacy-corrupt.json', code: 'INVALID_EXPERIMENT_RECORD', message: 'Record could not be validated.' },
      ],
      total: 2,
      limit: 25,
      offset: 0,
    });
    const host = document.createElement('div');
    document.body.append(host);
    const root = createRoot(host);

    await act(async () => { root.render(<ExperimentCatalog />); await Promise.resolve(); });

    const warning = host.querySelector('.catalog-warning');
    expect(warning?.textContent).toContain('unreadable-record.json · INVALID_EXPERIMENT_RECORD · Record could not be validated.');
    expect(warning?.textContent).toContain('legacy-corrupt.json · INVALID_EXPERIMENT_RECORD · Record could not be validated.');
    expect(host.textContent).toContain('XAUUSD · M15');

    vi.spyOn(jqeApi, 'compareExperiments').mockResolvedValue({
      left_experiment_id: 'experiment-one', right_experiment_id: 'experiment-two',
      classification: 'SAME_DATASET_DIFFERENT_CONFIGURATION', controlled_comparison: true,
      both_fully_reproducible: true, same_dataset: true, same_run_configuration: false, same_result: false,
      same_strategy_configuration: false, same_risk_configuration: true, same_execution_assumptions: true,
      metric_deltas: { total_return: -1, total_trades: null },
    });
    const boxes = host.querySelectorAll<HTMLInputElement>('.experiment-table input[type="checkbox"]');
    await act(async () => { boxes[0].click(); boxes[1].click(); });
    const compare = [...host.querySelectorAll('button')].find(button => button.textContent === 'Compare selected')!;
    await act(async () => { compare.click(); await Promise.resolve(); });

    expect(host.textContent).toContain('Metric deltas (left − right)');
    expect(host.textContent).not.toContain('\\u00b7');
    expect(host.textContent).not.toContain('\\u2212');

    await act(async () => root.unmount());
    host.remove();
  });
});
