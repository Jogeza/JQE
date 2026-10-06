/** Per-resource cadence and capped failure backoff; no evidence or permissions cached. */
export class ObservationSchedule {
  private entries = new Map<string, { next: number; failures: number }>();

  due(name: string, now: number): boolean {
    return now >= (this.entries.get(name)?.next ?? 0);
  }

  completed(name: string, now: number, success: boolean): void {
    const failures = success ? 0 : Math.min(3, (this.entries.get(name)?.failures ?? 0) + 1);
    const cadence = ['activeAnalysis', 'terminalObservation', 'observationHealth', 'risk', 'safety', 'execution'].includes(name)
      ? 15_000 : 60_000;
    this.entries.set(name, { failures, next: now + (success ? cadence : Math.max(cadence, 15_000 * 2 ** failures)) });
  }
}
