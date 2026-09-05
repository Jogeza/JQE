import type { HistoricalAcquisitionJobDTO } from '../../types/research';

export function acquisitionSelectionKey(provider: string, providerSymbol: string,
  canonicalSymbol: string, timeframe: string): string {
  return [provider, providerSymbol, canonicalSymbol, timeframe].join('|');
}

export function jobSelectionKey(job: HistoricalAcquisitionJobDTO): string {
  return acquisitionSelectionKey(job.spec.provider, job.spec.provider_symbol,
    job.spec.canonical_symbol, job.spec.timeframe);
}

export function isTerminalAcquisition(job: HistoricalAcquisitionJobDTO): boolean {
  return job.state === 'COMPLETED' || job.state === 'FAILED';
}
