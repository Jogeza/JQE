/**
 * Steady-state refreshes are staggered per resource so a 4s tick never fires a
 * whole cohort at once; bursts were saturating the relay's bounded origin
 * queue (503s for unrelated routes). Offsets only shift the success path —
 * initial loads, manual refreshes and failure backoff stay immediately due.
 */
export const RESOURCE_OFFSETS_MS: Record<string, number> = {
  activeAnalysis: 0, observationHealth: 0,
  risk: 4_000, safety: 4_000,
  terminalObservation: 8_000, execution: 8_000,
  brokerStatus: 0, watchlist: 4_000, monitoring: 8_000,
  watchlistCapUsage: 12_000, notificationStatus: 20_000, assistantStatus: 28_000,
};

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
    this.entries.set(name, {
      failures,
      next: now + (success
        ? cadence + (RESOURCE_OFFSETS_MS[name] ?? 0)
        : Math.max(cadence, 15_000 * 2 ** failures)),
    });
  }
}
