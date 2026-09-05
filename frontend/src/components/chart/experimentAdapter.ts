import type { ExperimentComparisonDTO, ResearchExperimentDTO } from '../../types/research';
export interface ExperimentDisplayRow { partition: 'Train' | 'Validation' | 'Out of sample'; baselineTrades: number; variantTrades: number; netPnlDelta: number; expectancyDelta: number; maxDrawdownDelta: number; sufficient: boolean; }
export function adaptExperiment(dto: ResearchExperimentDTO): ExperimentDisplayRow[] {
  const entries: [ExperimentDisplayRow['partition'], ExperimentComparisonDTO | null | undefined][] = [['Train', dto.train], ['Validation', dto.validation], ['Out of sample', dto.out_of_sample]];
  return entries.filter((entry): entry is [ExperimentDisplayRow['partition'], ExperimentComparisonDTO] => Boolean(entry[1])).map(([partition, value]) => ({ partition, baselineTrades: value.baseline.trade_count, variantTrades: value.variant.trade_count, netPnlDelta: value.deltas.net_pnl_delta, expectancyDelta: value.deltas.expectancy_delta, maxDrawdownDelta: value.deltas.max_drawdown_delta, sufficient: value.variant.sample_sufficient }));
}
