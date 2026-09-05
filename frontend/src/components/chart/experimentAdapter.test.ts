import { describe, expect, it } from 'vitest';
import { adaptExperiment } from './experimentAdapter';
import type { ResearchExperimentDTO } from '../../types/research';
const metrics = { trade_count: 10, win_rate: 50, net_pnl: 2, expectancy: .2, profit_factor: 1.2, max_drawdown: 1, average_result: .2, median_result: .1, sample_sufficient: false };
const comparison = { baseline: metrics, variant: { ...metrics, trade_count: 8 }, deltas: { trade_count_delta: -2, net_pnl_delta: 1, win_rate_delta: 5, expectancy_delta: .1, profit_factor_delta: .2, max_drawdown_delta: -.5 } };
describe('experiment DTO adapter', () => {
  it('maps partitions, deltas, and sufficiency without financial recalculation', () => {
    const dto = { status: 'INSUFFICIENT_SAMPLE', selected_threshold: '0.5', volume_type: 'SIMULATED_VOLUME', train: comparison, validation: comparison, out_of_sample: comparison } as unknown as ResearchExperimentDTO;
    const rows = adaptExperiment(dto);
    expect(rows.map(row => row.partition)).toEqual(['Train', 'Validation', 'Out of sample']);
    expect(rows[2]).toMatchObject({ baselineTrades: 10, variantTrades: 8, netPnlDelta: 1, expectancyDelta: .1, maxDrawdownDelta: -.5, sufficient: false });
    expect(dto.selected_threshold).toBe('0.5'); expect(dto.volume_type).toBe('SIMULATED_VOLUME');
  });
  it('maps unavailable state to no comparison rows', () => {
    expect(adaptExperiment({ status: 'FRVP_EXPERIMENT_UNAVAILABLE', train: null, validation: null, out_of_sample: null } as unknown as ResearchExperimentDTO)).toEqual([]);
  });
});
